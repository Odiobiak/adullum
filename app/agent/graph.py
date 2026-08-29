"""Wires the five nodes in app/agent/nodes.py into the state machine:

    classify_intent -> retrieve -> synthesize -> ground_check -+-> format_citations -> END
                                        ^_______________________|
                                        (loops back to retrieve if ungrounded,
                                         up to MAX_RETRIES times)

Compiled once at import time into module-level `agent`, which is what
app/main.py invokes/streams.
"""

from langgraph.graph import END, StateGraph

from app.agent.nodes import (
    MAX_RETRIES,
    classify_intent,
    format_citations,
    ground_check,
    retrieve,
    synthesize,
)
from app.agent.state import AgentState


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
    graph.add_node("retrieve", retrieve)
    graph.add_node("synthesize", synthesize)
    graph.add_node("ground_check", ground_check)
    graph.add_node("format_citations", format_citations)

    graph.set_entry_point("classify_intent")
    graph.add_edge("classify_intent", "retrieve")
    graph.add_edge("retrieve", "synthesize")
    graph.add_edge("synthesize", "ground_check")
    graph.add_conditional_edges(
        "ground_check",
        _after_ground_check,
        {"retrieve": "retrieve", "format_citations": "format_citations"},
    )
    graph.add_edge("format_citations", END)

    return graph.compile()


agent = build_graph()
