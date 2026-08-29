"""Shared pydantic models: the data shapes that cross module boundaries
(retrieval -> agent state -> API response). Keeping them here instead of
redefining ad hoc dicts in each module is what lets FastAPI validate request/
response bodies and lets the agent state stay typed.
"""

from typing import Literal

from pydantic import BaseModel


class Verse(BaseModel):
    """One verse row, as returned by any of the three retrieval paths in app/retrieval.py."""

    book: str
    chapter: int
    verse: int
    text: str
    translation: str
    similarity: float | None = None  # only set by vector_search; None for reference/keyword hits
    source: Literal["reference", "vector", "keyword"] = "vector"


class ChatRequest(BaseModel):
    """Body for both POST /chat and POST /chat/stream."""

    query: str
    translation: str | None = None  # falls back to settings.default_translation if omitted
    session_id: str | None = None  # reserved for chat_sessions/chat_messages once auth exists


class Citation(BaseModel):
    """A verse reference the answer actually relied on — the subset of retrieved
    verses that survive app/agent/nodes.py::format_citations.
    """

    book: str
    chapter: int
    verse: int
    translation: str


class ChatResponse(BaseModel):
    """Body returned by the non-streaming POST /chat endpoint."""

    answer: str
    citations: list[Citation]
    intent: str
