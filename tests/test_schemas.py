"""These pydantic models are what FastAPI validates request/response bodies
against, so a wrong default or an overly loose type here is a contract bug
that reaches every client (web, MCP, mobile later) at once.
"""

import pytest
from pydantic import ValidationError

from app.schemas import ChatRequest, ChatResponse, Citation, Verse


class TestVerse:
    def test_defaults(self):
        v = Verse(book="John", chapter=3, verse=16, text="For God so loved...", translation="BSB")
        assert v.similarity is None
        assert v.source == "vector"

    def test_source_rejects_unknown_value(self):
        with pytest.raises(ValidationError):
            Verse(book="John", chapter=3, verse=16, text="...", translation="BSB", source="guess")


class TestChatRequest:
    def test_translation_and_session_id_are_optional(self):
        req = ChatRequest(query="What does John 3:16 mean?")
        assert req.translation is None
        assert req.session_id is None

    def test_query_is_required(self):
        with pytest.raises(ValidationError):
            ChatRequest()


class TestChatResponse:
    def test_followups_default_empty(self):
        resp = ChatResponse(
            answer="...",
            citations=[Citation(book="John", chapter=3, verse=16, translation="BSB")],
            intent="reference_lookup",
        )
        assert resp.followups == []
