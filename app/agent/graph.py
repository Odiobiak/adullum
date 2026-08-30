"""Wires the nodes in app/agent/nodes.py into the state machine:

    classify_intent -> retrieve -> synthesize -> ground_check -+-> format_citations
                                        ^_______________________|          |
                                        (loops back to retrieve if         v
                                         ungrounded, up to          suggest_followups -> END
                                         MAX_RETRIES times)              (text only)

suggest_followups runs last on purpose: the answer and its citations have
already streamed to the client by then, so the extra call costs the user no
perceived latency. It only runs when the caller sets `want_followups`, which
the voice path deliberately does not.

Compiled once at import time into module-level `agent`, which is what
app/main.py invokes/streams.
"""

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    MAX_RETRIES,
    answer_meta,
    classify_intent,
    format_citations,
    ground_check,
    retrieve,
    suggest_followups,
    synthesize,
)
from app.agent.state import AgentState


def _after_classify(state: AgentState) -> str:
    """Conditional edge out of classify_intent: "meta" questions (about the
    assistant itself, small talk) skip retrieval/synthesis entirely and go
    straight to answer_meta -> END; everything else takes the normal
    grounded-retrieval path.
    """
    return "answer_meta" if state.get("intent") == "meta" else "retrieve"


def _after_citations(state: AgentState) -> str:
    """Conditional edge out of format_citations: only callers that asked for
    follow-ups pay for them. Defaults to skipping, so a new caller has to opt in
    rather than silently inheriting an extra LLM call.
    """
    return "suggest_followups" if state.get("want_followups") else END


def _after_ground_check(state: AgentState) -> str:
    """Conditional edge out of ground_check: retry (widen retrieval, re-synthesize)
    while ungrounded and under budget, otherwise move on regardless of the
    verdict — an ungrounded-but-delivered answer beats an infinite loop.
    """
    if state.get("grounded") or state.get("retries", 0) > MAX_RETRIES:
        return "format_citations"
    return "retrieve"


def build_graph():
    """Construct and compile the graph. Called once at import time below;
    exposed as a function (rather than only the compiled `agent`) so tests can
    build a fresh instance without relying on shared module state.
    """
    graph = StateGraph(AgentState)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("answer_meta", answer_meta)
    graph.add_node("retrieve", retrieve)
    graph.add_node("synthesize", synthesize)
    graph.add_node("ground_check", ground_check)
    graph.add_node("format_citations", format_citations)
    graph.add_node("suggest_followups", suggest_followups)

    graph.set_entry_point("classify_intent")
    graph.add_conditional_edges(
        "classify_intent",
        _after_classify,
        {"retrieve": "retrieve", "answer_meta": "answer_meta"},
    )
    graph.add_edge("answer_meta", END)
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", "ground_check")
    graph.add_conditional_edges(
        "ground_check",
        _after_ground_check,
        {"retrieve": "retrieve", "format_citations": "format_citations"},
    )
    graph.add_conditional_edges(
        "format_citations",
        _after_citations,
        {"suggest_followups": "suggest_followups", END: END},
    )
    graph.add_edge("suggest_followups", END)

    return graph.compile()


agent = build_graph()
