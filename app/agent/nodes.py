"""The five LangGraph node functions wired together in app/agent/graph.py.

Each function takes the current AgentState and returns only the keys it changes
(LangGraph merges the rest) — see app/agent/state.py for the full field list and
who sets what.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agent.state import AgentState, Intent
from app.config import settings
from app.observability import score_trace_from_config
from app.retrieval import hybrid_retrieve
from app.schemas import Verse

# temperature=0: this is a grounded Q&A agent, not a creative one — we want the
# same question to get a stable answer, and we want ground_check's judgments
# to be consistent rather than noisy.
_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0)

MAX_RETRIES = 1  # one re-retrieve-and-retry before we hand back an ungrounded answer as-is


# ---------------------------------------------------------------------------
# classify_intent — routes the query to the right retrieval strategy downstream
# ---------------------------------------------------------------------------
class IntentClassification(BaseModel):
    intent: Intent = Field(
        description=(
            "reference_lookup: asks about a specific verse/passage. "
            "thematic: asks what the Bible says about a topic or concept. "
            "devotional: asks for life application / encouragement. "
            "cross_reference: asks how passages relate to each other."
        )
    )


CLASSIFY_SYSTEM_PROMPT = (
    "Classify the user's Bible question into exactly one intent category."
)


def classify_intent(state: AgentState, config: RunnableConfig) -> AgentState:
    """First node in the graph. Labels the query's intent; currently informational
    (surfaced in the API response and available for a future node that branches
    retrieval strategy per intent), but kept as an explicit LangGraph node rather
    than folded into retrieve() so that branching stays a one-line addition to
    graph.py instead of a rewrite.

    Accepts and forwards `config` (as do synthesize/ground_check below) purely so
    the Langfuse callback handler attached in app/main.py nests this node's LLM
    call under the request's trace with full prompt/token/latency detail — without
    it, LangGraph still traces the node itself (input/output), just not what the
    LLM call inside it looked like.
    """
    structured = _llm.with_structured_output(IntentClassification)
    result: IntentClassification = structured.invoke(
        [SystemMessage(CLASSIFY_SYSTEM_PROMPT), HumanMessage(state["query"])], config=config
    )
    return {"intent": result.intent}


# ---------------------------------------------------------------------------
# retrieve — widens the search (k) on a retry after a failed ground_check
# ---------------------------------------------------------------------------
def retrieve(state: AgentState) -> AgentState:
    """Runs hybrid_retrieve() (app/retrieval.py) and stores the resulting verses
    as the context synthesize() is allowed to draw from. Also the loop target
    when ground_check() rejects an answer — on that second pass `k` widens from
    8 to 14, on the theory that the first answer wasn't grounded because the
    right verse simply wasn't in the initial result set.
    """
    retries = state.get("retries", 0)
    k = 8 if retries == 0 else 14
    translation = state.get("translation") or settings.default_translation
    verses = hybrid_retrieve(state["query"], translation, k=k)
    return {"verses": verses, "translation": translation}


# ---------------------------------------------------------------------------
# synthesize — answers strictly from the retrieved verses
# ---------------------------------------------------------------------------
SYNTHESIZE_SYSTEM_PROMPT = """You are Aquila, a warm and steadfast Bible study companion \
— named for the believer in Acts 18:26 who, alongside Priscilla, took Apollos aside and \
"explained the way of God more accurately" to him. Your job is to help the person you're \
talking with go deeper in their relationship with God and in Scripture, not just to \
answer a question and move on.

Speak as a humble companion pointing to the text, never as an authority pronouncing on \
your own opinion. Answer using ONLY the verses listed below — never invent a reference or \
quote text that isn't listed. Cite every claim inline as (Book Chapter:Verse).

If the question touches a point where Christian traditions genuinely disagree \
(e.g. mode/timing of baptism, end-times views, predestination vs. free will), briefly \
present the range of interpretation with each side's supporting verses instead of \
asserting one tradition's view as the answer.

If the provided verses don't actually address the question, say so plainly rather than \
stretching them to fit — honesty about the text's limits matters more than sounding certain.

If the question carries real pain (grief, doubt, fear, a hard season), sit with that first \
rather than rushing to a cheerful resolution — Scripture itself makes room for lament, and \
so should you. Where it fits naturally, and only where it fits, offer a next step: a verse \
worth sitting with, or a question worth journaling on — but never force one.

You are a study companion, not a substitute for pastoral care, counseling, or emergency \
services. If someone's need is bigger than a conversation about Scripture, say so plainly \
and encourage them to reach a person who can actually help."""


def synthesize(state: AgentState, config: RunnableConfig) -> AgentState:
    """Drafts the answer from `state['verses']` only. Every claim/citation this
    produces is checked (not trusted) by ground_check() next — synthesize() is
    intentionally the "optimistic" half of a generate-then-verify pair.
    """
    verses_block = "\n".join(
        f"- {v.book} {v.chapter}:{v.verse} ({v.translation}) — {v.text}" for v in state["verses"]
    )
    prompt = f"Question: {state['query']}\n\nVerses:\n{verses_block}"
    response = _llm.invoke([SystemMessage(SYNTHESIZE_SYSTEM_PROMPT), HumanMessage(prompt)], config=config)
    return {"answer": response.content}


# ---------------------------------------------------------------------------
# ground_check — LLM-as-judge catches hallucinated citations/claims before
# they reach the user. This is the step that matters most in this domain.
# ---------------------------------------------------------------------------
class GroundCheck(BaseModel):
    grounded: bool = Field(
        description=(
            "True only if every citation and claim in the answer is directly "
            "supported by the listed verses. Be strict."
        )
    )


GROUND_CHECK_PROMPT = (
    "Given the verses and the drafted answer, decide whether every citation and claim "
    "in the answer is directly supported by the verses. An answer that cites a verse "
    "not in the list, or draws a conclusion the verse doesn't support, is NOT grounded."
)


def judge_groundedness(verses: list[Verse], answer: str, config: RunnableConfig | None = None) -> GroundCheck:
    """The actual judge call, pulled out of ground_check() so scripts/evaluate.py
    can score a run's groundedness with the exact same judge production uses,
    rather than a second hand-written eval prompt drifting out of sync with it.
    """
    verses_block = "\n".join(f"- {v.book} {v.chapter}:{v.verse} — {v.text}" for v in verses)
    prompt = f"Verses:\n{verses_block}\n\nAnswer:\n{answer}"
    structured = _llm.with_structured_output(GroundCheck)
    return structured.invoke([SystemMessage(GROUND_CHECK_PROMPT), HumanMessage(prompt)], config=config)


def ground_check(state: AgentState, config: RunnableConfig) -> AgentState:
    """Second half of the generate-then-verify pair: an independent LLM call
    judges the drafted answer against the same verse list, rather than trusting
    synthesize()'s self-report. Always increments `retries` — that counter is
    what graph.py's conditional edge uses to stop looping after MAX_RETRIES
    even if the answer is still ungrounded.

    Also records the verdict as a Langfuse score on this request's trace (a
    no-op if Langfuse isn't configured) — this is what turns "did we hallucinate
    a verse" from something only visible by reading a trace by hand into a
    filterable dashboard metric.
    """
    result = judge_groundedness(state["verses"], state["answer"], config=config)
    score_trace_from_config(config, name="grounded", value=1.0 if result.grounded else 0.0)
    return {"grounded": result.grounded, "retries": state.get("retries", 0) + 1}


# ---------------------------------------------------------------------------
# format_citations — narrows the context set down to verses actually cited
# ---------------------------------------------------------------------------
def format_citations(state: AgentState) -> AgentState:
    """Last node. Narrows `state['verses']` (everything synthesize() had access
    to) down to `state['citations']` (only what it actually referenced), by a
    plain substring match on "Book Chapter:Verse" — cheap and reliable since
    synthesize() is instructed to cite in exactly that format. Falls back to the
    full verse list if none matched, so the API never returns zero citations
    for a non-empty answer.
    """
    answer = state["answer"]
    cited = [v for v in state["verses"] if f"{v.book} {v.chapter}:{v.verse}" in answer]
    return {"citations": cited or state["verses"]}
