"""The LangGraph node functions wired together in app/agent/graph.py: the
study path (classify_intent through suggest_followups) and listen(), the
gentler Aquila of Refuge.

Each function takes the current AgentState and returns only the keys it changes
(LangGraph merges the rest) — see app/agent/state.py for the full field list and
who sets what.
"""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.agent.state import AgentState, Intent
from app.care import sounds_unsafe
from app.config import settings
from app.observability import score_trace_from_config
from app.retrieval import find_references, hybrid_retrieve
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
            "cross_reference: asks how passages relate to each other. "
            "meta: asks about the assistant itself (its name, identity, what it is/can "
            "do) or is small talk/a greeting — not a Bible content question at all."
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
# Memory: notes about the person from earlier conversations (app/memory.py).
# Shared by answer_meta and synthesize so both describe them the same way.
# ---------------------------------------------------------------------------
def memory_block(state: AgentState) -> str:
    """Empty for guests and for anyone with memory off, so the prompt is
    byte-for-byte what it was before memory existed."""
    memories = state.get("memories") or []
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return (
        "\n\nWhat you remember about this person from earlier conversations. This is private "
        "context, not Scripture: never cite it, never treat it as evidence for what the Bible "
        "says, and only bring it up when it genuinely helps, the way a friend would, lightly:\n"
        f"{lines}"
    )


# ---------------------------------------------------------------------------
# answer_meta — questions about the assistant itself, not Bible content.
# Routed here straight from classify_intent, bypassing retrieve()/synthesize()
# entirely: those are hard-instructed to answer ONLY from retrieved verses,
# which made "what's your name?" retrieve unrelated verses about names (Jacob,
# Jesus asking "who do you say I am") and then dodge the question rather than
# just answering as herself.
# ---------------------------------------------------------------------------
META_SYSTEM_PROMPT = """You are Aquila, a warm and steadfast Bible study companion, \
named for the believer in Acts 18:26 who, alongside Priscilla, took Apollos aside and \
"explained the way of God more accurately" to him. Your job is to help the person you're \
talking with go deeper in their relationship with God and in Scripture.

The user just asked about you directly (your name, what you are, or similar small talk) \
rather than a Bible question. Answer warmly and briefly, in your own voice. This doesn't \
need a verse citation, since it isn't a Scripture question.

Write like a person talking to a friend, not like an AI assistant. Never use an em dash."""


def answer_meta(state: AgentState, config: RunnableConfig) -> AgentState:
    """Handles small talk / questions about the assistant itself. No verses are
    retrieved and no citations are produced — `format_citations` is skipped
    entirely for this path (see graph.py)."""
    prompt = state["query"] + memory_block(state)
    response = _llm.invoke([SystemMessage(META_SYSTEM_PROMPT), HumanMessage(prompt)], config=config)
    return {"answer": response.content, "citations": []}


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
SYNTHESIZE_SYSTEM_PROMPT = """You are Aquila, warm, welcoming, and a happy, steadfast \
believer in God. You're named for the believer in Acts 18:26 who, alongside Priscilla, \
took Apollos aside and "explained the way of God more accurately" to him. Your job is to \
help the person you're talking with build a deeper relationship with God and with \
Scripture, not just to answer a question and move on.

Speak as a humble companion pointing to the text, never as an authority pronouncing on \
your own opinion. Answer using ONLY the verses listed below; never invent a reference or \
quote text that isn't listed. Cite every claim inline as (Book Chapter:Verse).

Shape the answer as a short study, moving through these headings in order. Write each \
heading on its own line exactly as shown, hashes included. Keep each part to a few \
sentences, and skip any heading that genuinely doesn't apply rather than padding it out:

## The passage
The words that actually carry the answer, quoted from the verses provided.

## Context
Who is speaking, to whom, and what surrounds it, drawn only from the verses you were \
given. If those verses don't show you the setting, skip this heading instead of guessing \
at history you cannot see.

## What it means
The reading itself, in plain language.

## To sit with
One short question or invitation to carry away. Never make it feel like homework.

If the question touches a point where Christian traditions genuinely disagree \
(e.g. mode/timing of baptism, end-times views, predestination vs. free will), present the \
range of interpretation under "What it means", giving each side's supporting verses, \
instead of asserting one tradition's view as the answer.

If the provided verses don't actually address the question, say so plainly rather than \
stretching them to fit. Honesty about the text's limits matters more than sounding \
certain. In that case drop the headings entirely and just say so in a sentence or two.

If the question carries real pain (grief, doubt, fear, a hard season), sit with that first \
rather than rushing to a cheerful resolution. Scripture itself makes room for lament, and \
so should you.

You are a study companion, not a substitute for pastoral care, counseling, or emergency \
services. If someone's need is bigger than a conversation about Scripture, say so plainly \
and encourage them to reach a person who can actually help.

Write like a person talking to a friend, not like an AI assistant. Never use an em dash. \
Skip the hedging and the "it's not just X, it's Y" phrasing, and don't restate the question \
before answering it."""


def synthesize(state: AgentState, config: RunnableConfig) -> AgentState:
    """Drafts the answer from `state['verses']` only. Every claim/citation this
    produces is checked (not trusted) by ground_check() next — synthesize() is
    intentionally the "optimistic" half of a generate-then-verify pair.
    """
    verses_block = "\n".join(
        f"- {v.book} {v.chapter}:{v.verse} ({v.translation}) — {v.text}" for v in state["verses"]
    )
    prompt = f"Question: {state['query']}\n\nVerses:\n{verses_block}{memory_block(state)}"
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
    "not in the list, or draws a conclusion the verse doesn't support, is NOT grounded. "
    "If notes about the person are given, a warm remark about their own situation drawn "
    "from those notes is fine, but the notes can never support a claim about what "
    "Scripture says."
)


def judge_groundedness(
    verses: list[Verse],
    answer: str,
    config: RunnableConfig | None = None,
    memories: list[str] | None = None,
) -> GroundCheck:
    """The actual judge call, pulled out of ground_check() so scripts/evaluate.py
    can score a run's groundedness with the exact same judge production uses,
    rather than a second hand-written eval prompt drifting out of sync with it.

    `memories` is passed so a line like "since you're reading Romans with your
    group" isn't marked as an invented claim. They're labelled as notes about
    the person, so they can't be used to excuse a claim about Scripture.
    """
    verses_block = "\n".join(f"- {v.book} {v.chapter}:{v.verse} — {v.text}" for v in verses)
    notes_block = ""
    if memories:
        notes_block = "\n\nNotes about the person (not Scripture):\n" + "\n".join(f"- {m}" for m in memories)
    prompt = f"Verses:\n{verses_block}{notes_block}\n\nAnswer:\n{answer}"
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
    result = judge_groundedness(state["verses"], state["answer"], config=config, memories=state.get("memories"))
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


# ---------------------------------------------------------------------------
# suggest_followups, the "continue" movement of the study. Runs last so the
# answer and its citations are already on screen before this call adds latency.
# ---------------------------------------------------------------------------
class Followups(BaseModel):
    questions: list[str] = Field(
        description="Two or three short follow-up questions, written in the user's own voice."
    )


FOLLOWUP_SYSTEM_PROMPT = """You are helping someone continue a study they have just started. \
Given their question and the answer they received, suggest three questions they might \
genuinely want to ask next.

Each one should open a door the answer left ajar: the passage behind the passage, a tension \
worth naming, how this sits alongside another part of Scripture, or what it asks of someone \
actually living it. Go deeper rather than sideways, and never restate something the answer \
already covered.

Write them in the person's own voice, the way they would type them, and keep each under \
about twelve words. Never use an em dash."""


def suggest_followups(state: AgentState, config: RunnableConfig) -> AgentState:
    """Proposes where the study could go next. Deliberately non-fatal: follow-ups
    are a nicety on top of a good answer, so a failure here returns an empty list
    rather than taking down a response that was otherwise complete and grounded.
    """
    prompt = f"Their question: {state['query']}\n\nThe answer they received:\n{state['answer']}"
    structured = _llm.with_structured_output(Followups)
    try:
        result: Followups = structured.invoke(
            [SystemMessage(FOLLOWUP_SYSTEM_PROMPT), HumanMessage(prompt)], config=config
        )
        return {"followups": [q.strip() for q in result.questions if q.strip()][:3]}
    except Exception:
        return {"followups": []}


# ---------------------------------------------------------------------------
# listen: Aquila in Refuge. One node, reached straight from the entry point
# when the caller sets mode="listen" (app/refuge.py). People come to Refuge in
# every kind of season, so this isn't a study and it doesn't produce one: no
# headings, no follow-ups, and Scripture only when it's wanted. What stays the
# same is the rule that matters most: she only ever quotes a verse that was
# actually looked up, checked below by reference rather than trusted.
# ---------------------------------------------------------------------------
# A little warmth in the wording; the study path stays at 0 for consistency.
_warm_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0.5)

# How much of a long talk goes into each prompt.
LISTEN_HISTORY_LIMIT = 24

LISTEN_SYSTEM_PROMPT = """You are Aquila, a warm and steadfast companion who loves God. \
Right now you're in Refuge, a quiet, private room in the app. People come here in every \
kind of season: carrying something heavy, hoping for something, planning what's next with \
God, giving thanks, or just needing to be heard.

Here you listen first.
- Reply in a few short sentences, like a friend sitting beside them. No headings, no lists, \
no lecture.
- Show you heard them, in your own words, and ask at most one gentle question.
- Don't rush to fix or explain, and never tell them how they should feel.
- When they're hopeful, planning or grateful, be glad with them, and help them think it \
through with God: what they're hoping for, what a first small step could be, what they'd \
want to pray about it.
- Offer Scripture only when they ask for it or one verse would truly meet them, and then \
only one, quoted exactly from the verses listed for you, with its reference. If no verses \
are listed, don't quote Scripture or name any reference at all.
- You aren't a counsellor, a pastor or an emergency service. If what they're carrying needs \
more than a conversation, say so gently and encourage them to reach a person.

Write like a person, not like an AI assistant. Never use an em dash. Skip the hedging and \
the "it's not just X, it's Y" phrasing, and don't repeat their words back to them."""

CARE_INSTRUCTION = """They may not be safe right now. Respond with warmth and without alarm. \
Tell them you're really glad they told you, that they deserve a real person with them right \
now, and that the people listed just below your message are free and there for exactly \
this. Ask whether they're safe at the moment. Don't quote Scripture in this reply. Keep it \
short."""

class CareCheck(BaseModel):
    at_risk: bool = Field(
        description=(
            "True if the latest message, read in context, suggests thoughts of suicide or "
            "self-harm, wanting to die or not be here, being in danger from someone, or being "
            "unable to keep themselves safe. When unsure, answer true."
        )
    )
    wants_verse: bool = Field(
        description=(
            "True if they ask for Scripture, a verse, or what the Bible or God says, or say yes "
            "to an offer of a verse."
        )
    )


CARE_CHECK_PROMPT = "Read the conversation and judge only the person's latest message."


def _listen_messages(history: list[dict]) -> list:
    """The exchange as chat messages, most recent last, trimmed to the limit."""
    out = []
    for m in history[-LISTEN_HISTORY_LIMIT:]:
        text = str(m.get("content") or "")
        out.append(AIMessage(text) if m.get("role") == "aquila" else HumanMessage(text))
    return out


def unlisted_references(reply: str, verses: list[Verse]) -> list[str]:
    """References named in `reply` that aren't among `verses`. A chapter named
    without a verse counts as listed if any listed verse is in it."""
    listed = {(v.book, v.chapter, v.verse) for v in verses}
    chapters = {(v.book, v.chapter) for v in verses}
    unlisted = []
    for ref in find_references(reply):
        if ref.verse_start is None:
            ok = (ref.book, ref.chapter) in chapters
        else:
            ok = all((ref.book, ref.chapter, n) in listed for n in range(ref.verse_start, ref.verse_end + 1))
        if not ok:
            unlisted.append(f"{ref.book} {ref.chapter}" + (f":{ref.verse_start}" if ref.verse_start else ""))
    return unlisted


def listen(state: AgentState, config: RunnableConfig) -> AgentState:
    """Reads the whole talk, checks whether the person may not be safe, looks
    up a few verses only if Scripture is wanted, and replies.

    If the reply names a verse that wasn't looked up, it is written again
    once, and if it still does, it is written with no verses at all. A reply
    with no Scripture is always better than one with an invented verse.
    """
    history = state.get("history") or [{"role": "user", "content": state["query"]}]
    latest = state["query"]
    chat = _listen_messages(history)

    check: CareCheck = _llm.with_structured_output(CareCheck).invoke(
        [SystemMessage(CARE_CHECK_PROMPT), *chat], config=config
    )
    care = check.at_risk or sounds_unsafe(latest)

    translation = state.get("translation") or settings.default_translation
    verses: list[Verse] = []
    if check.wants_verse and not care:
        # The latest message alone is often just "yes please", so the one
        # before it gives the search something to go on.
        user_turns = [m["content"] for m in history if m.get("role") != "aquila"][-2:]
        verses = hybrid_retrieve(" ".join(user_turns), translation, k=4)

    def reply_with(listed: list[Verse], extra: str = "") -> str:
        system = LISTEN_SYSTEM_PROMPT
        if care:
            system += "\n\n" + CARE_INSTRUCTION
        if listed:
            block = "\n".join(f"- {v.book} {v.chapter}:{v.verse} ({v.translation}): {v.text}" for v in listed)
            system += f"\n\nVerses you may quote, and no others:\n{block}"
        else:
            system += "\n\nNo verses are listed for this reply."
        if extra:
            system += "\n\n" + extra
        return _warm_llm.invoke([SystemMessage(system), *chat], config=config).content

    answer = reply_with(verses)
    if unlisted_references(answer, verses):
        answer = reply_with(verses, "Your last draft named a verse that isn't listed. Only quote a listed verse, or none.")
        if unlisted_references(answer, verses):
            verses = []
            answer = reply_with([], "Don't name or quote any Bible verse in this reply.")

    cited = [v for v in verses if f"{v.book} {v.chapter}:{v.verse}" in answer]
    return {"answer": answer, "care": care, "verses": verses, "citations": cited, "translation": translation}
