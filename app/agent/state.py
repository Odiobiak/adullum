"""The state LangGraph threads through every node in app/agent/graph.py.

Each node in nodes.py receives the full state and returns a partial dict of the
keys it updates — LangGraph merges that into the running state before calling
the next node. `total=False` reflects that the state is built up incrementally:
`intent` doesn't exist until classify_intent has run, `answer` doesn't exist
until synthesize has run, and so on.
"""

from typing import Literal, TypedDict

from app.schemas import Verse

Intent = Literal["reference_lookup", "thematic", "devotional", "cross_reference"]


class AgentState(TypedDict, total=False):
    query: str  # set by the caller (app/main.py) when the graph run starts
    translation: str  # set by retrieve(), defaulting from settings if the caller omitted it
    intent: Intent  # set by classify_intent()
    verses: list[Verse]  # set by retrieve() — the context synthesize() is allowed to use
    answer: str  # set by synthesize()
    grounded: bool  # set by ground_check() — whether answer is judged fully supported by verses
    retries: int  # incremented by ground_check(); caps the retrieve<->synthesize retry loop
    citations: list[Verse]  # set by format_citations() — the subset of verses actually cited
