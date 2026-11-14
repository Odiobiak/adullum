"""Shared pydantic models: the data shapes that cross module boundaries
(retrieval -> agent state -> API response). Keeping them here instead of
redefining ad hoc dicts in each module is what lets FastAPI validate request/
response bodies and lets the agent state stay typed.
"""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _without_defaults(schema: dict) -> None:
    for prop in schema.get("properties", {}).values():
        prop.pop("default", None)


class ModelDraft(BaseModel):
    """A shape the model fills in through structured output.

    OpenAI's strict structured output refuses a schema carrying a `default`,
    and a refused schema fails the whole call. Fields here may still have
    defaults for code that builds a draft by hand (a fallback, a test); they're
    only left out of the schema sent to the model, which fills every field.
    Nested shapes inherit this too, or their defaults slip through.
    """

    model_config = ConfigDict(json_schema_extra=lambda schema, _cls: _without_defaults(schema))


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

    # Long enough for a prayer request with its story; a whole pasted book is refused.
    query: str = Field(min_length=1, max_length=2000)
    translation: str | None = None  # falls back to settings.default_translation if omitted
    session_id: str | None = None  # reserved for chat_sessions/chat_messages once auth exists
    # "pray" is Pray with Aquila on the prayer list (app/agent/nodes.py::pray_with):
    # verses, a prayer and encouragement instead of a study.
    mode: Literal["study", "pray"] = "study"


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
    # Questions to carry the study further. Empty for meta/small-talk answers,
    # which skip the retrieval path entirely, and whenever the suggestion call
    # fails. See app/agent/nodes.py::suggest_followups.
    followups: list[str] = []


class PlanRequest(BaseModel):
    """Body for POST /plan."""

    start_date: date
    days: int = 365
    translation: str | None = None  # falls back to settings.default_translation if omitted


class PlanDay(BaseModel):
    """One day of a reading plan, as produced by app/plan.py::generate_schedule."""

    day: int
    date: date
    references: list[str]


class PlanResponse(BaseModel):
    """Body returned by POST /plan and GET /plan/{plan_id}."""

    plan_id: str
    start_date: date
    days: int
    translation: str
    overview: str
    schedule: list[PlanDay]
