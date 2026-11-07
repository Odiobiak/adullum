"""HTTP-contract tests for app/main.py. /chat and /chat/stream mock the
compiled agent's ainvoke/astream directly rather than running the real graph,
since a real run needs a live OpenAI key and a seeded Supabase database —
out of scope for a fast, hermetic test. What's under test here is the API's
own wiring: request validation, response shape, and the SSE event framing.
"""

import json

from fastapi.testclient import TestClient

import app.main as main
from app.schemas import Citation, Verse

client = TestClient(main.app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


class TestChat:
    def test_returns_answer_and_citations(self, monkeypatch):
        async def fake_ainvoke(state, config=None):
            return {
                "answer": "## The passage\nJohn 3:16 says...",
                # The real graph's "citations" are Verse objects (see
                # format_citations in app/agent/nodes.py); main.py reads
                # .book/.chapter/.verse/.translation off each one.
                "citations": [
                    Verse(book="John", chapter=3, verse=16, text="...", translation="BSB")
                ],
                "intent": "reference_lookup",
                "followups": ["What does 'only begotten' mean?"],
            }

        monkeypatch.setattr(main.agent, "ainvoke", fake_ainvoke)

        resp = client.post("/chat", json={"query": "What does John 3:16 mean?"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["intent"] == "reference_lookup"
        assert body["citations"] == [
            {"book": "John", "chapter": 3, "verse": 16, "translation": "BSB"}
        ]
        assert body["followups"] == ["What does 'only begotten' mean?"]

    def test_missing_query_is_rejected(self):
        resp = client.post("/chat", json={})
        assert resp.status_code == 422


class TestChatStream:
    def test_streams_answer_and_citation_events(self, monkeypatch):
        async def fake_astream(state, config=None, stream_mode=None):
            yield {"classify_intent": {"intent": "thematic"}}
            yield {"synthesize": {"answer": "## The passage\nSome answer"}}
            yield {
                "format_citations": {
                    "citations": [
                        Citation(book="Romans", chapter=8, verse=28, translation="BSB")
                    ]
                }
            }

        monkeypatch.setattr(main.agent, "astream", fake_astream)

        resp = client.post("/chat/stream", json={"query": "What does Romans 8:28 mean?"})
        assert resp.status_code == 200
        body = resp.text

        assert "event: stage" in body
        assert '"node": "classify_intent"' in body
        assert "event: answer" in body
        assert "Some answer" in body
        assert "event: citations" in body
        citations_line = next(
            line for line in body.splitlines() if line.startswith("data:") and "Romans" in line
        )
        assert json.loads(citations_line.removeprefix("data:").strip()) == [
            {"book": "Romans", "chapter": 8, "verse": 28, "translation": "BSB"}
        ]


class TestPlanOwnership:
    """A signed-in person's plan answers only to them; a guest's plan stays
    open to its link (the emailed PDF link depends on that)."""

    ROW = {"id": "p1", "start_date": "2026-11-01", "days": 1, "translation": "BSB", "overview": "", "schedule": []}

    def _plan(self, monkeypatch, owner):
        from unittest.mock import MagicMock

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{**self.ROW, "user_id": owner}]
        monkeypatch.setattr(main, "get_supabase", lambda: db)

    def test_someone_elses_plan_is_not_found(self, monkeypatch):
        from app.auth import AuthUser, optional_user

        self._plan(monkeypatch, "owner")
        main.app.dependency_overrides[optional_user] = lambda: AuthUser(id="stranger", email=None)
        try:
            assert client.get("/plan/p1").status_code == 404
        finally:
            main.app.dependency_overrides.clear()
        assert client.get("/plan/p1").status_code == 404  # signed out

    def test_a_guest_plan_opens_by_its_link(self, monkeypatch):
        self._plan(monkeypatch, None)
        assert client.get("/plan/p1").status_code == 200
