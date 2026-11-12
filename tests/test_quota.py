"""Daily limits (app/quota.py), the answer cache (app/answer_cache.py), the
MCP key and Refuge's history trim. No database: `_record` stands in for the
use_quota call, as conftest.py does for every other test."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import HumanMessage

import app.main as main
from app import answer_cache, auth, quota
from app.agent import nodes
from app.auth import AuthUser
from app.config import settings

client = TestClient(main.app)


def answer_stream(calls):
    """A fake graph run that counts how often it actually ran."""

    async def fake_astream(state, config=None, stream_mode=None):
        calls.append(state["query"])
        yield {"synthesize": {"answer": "## The passage\nAn answer"}}
        yield {"format_citations": {"citations": []}}

    return fake_astream


class TestSpend:
    def test_a_guest_is_counted_by_a_scrambled_address(self):
        request = type("R", (), {"headers": {"cf-connecting-ip": "203.0.113.9"}, "client": None})()
        subject = quota.subject_of(None, request)
        assert subject.startswith("guest:") and "203.0.113.9" not in subject
        assert quota.subject_of(AuthUser(id="u1", email=None), request) == "u1"

    def test_the_edge_address_wins_over_a_typed_forwarded_for(self):
        request = type("R", (), {"headers": {"true-client-ip": "198.51.100.1", "x-forwarded-for": "1.1.1.1"}, "client": None})()
        assert quota.client_ip(request) == "198.51.100.1"

    @pytest.mark.parametrize("outcome, guest, expected", [
        ("limit", False, "question"),
        ("limit", True, "question_guest"),
        ("budget", False, "budget"),
    ])
    def test_a_refusal_says_why_gently(self, monkeypatch, outcome, guest, expected):
        monkeypatch.setattr(quota, "_record", lambda *a: outcome)
        with pytest.raises(HTTPException) as caught:
            quota.spend("question", "guest:abc" if guest else "u1")
        assert caught.value.status_code == 429
        assert caught.value.detail == quota.LIMIT_MESSAGES[expected]

    def test_it_sends_the_persons_limit_and_cost(self, monkeypatch):
        seen = []
        monkeypatch.setattr(quota, "_record", lambda *a: seen.append(a) or "ok")
        quota.spend("question", "guest:abc")
        quota.spend("talk", "u1")
        assert seen[0] == ("guest:abc", "question", settings.quota_questions_guest, 3, 3000)
        assert seen[1] == ("u1", "talk", settings.quota_talks, 2, 3000)

    def test_a_guest_never_reaches_talks_or_calls(self):
        with pytest.raises(HTTPException):
            quota.spend("talk", "guest:abc")

    def test_the_counter_lets_requests_through_when_the_database_fails(self, monkeypatch):
        monkeypatch.undo()  # the real _record, with a database that isn't there
        monkeypatch.setattr(quota, "get_supabase", lambda: (_ for _ in ()).throw(RuntimeError("down")))
        assert quota._record("u1", "question", 25, 3, 3000) == "ok"


class TestBurst:
    def test_a_flood_is_refused_and_a_minute_later_allowed(self):
        for second in range(settings.quota_per_minute_signed_in):
            quota.check_burst("u1", now=1000.0 + second)
        with pytest.raises(HTTPException) as caught:
            quota.check_burst("u1", now=1010.0)
        assert caught.value.detail == quota.LIMIT_MESSAGES["burst"]
        quota.check_burst("u1", now=1061.0)

    def test_guests_get_fewer(self):
        for second in range(settings.quota_per_minute_guest):
            quota.check_burst("guest:x", now=float(second))
        with pytest.raises(HTTPException):
            quota.check_burst("guest:x", now=5.0)


class TestChatLimits:
    def test_a_limit_is_a_429_before_the_stream_opens(self, monkeypatch):
        calls = []
        monkeypatch.setattr(main.agent, "astream", answer_stream(calls))
        monkeypatch.setattr(quota, "_record", lambda *a: "limit")
        resp = client.post("/chat/stream", json={"query": "Who was Ruth?"})
        assert resp.status_code == 429
        assert resp.json()["detail"] == quota.LIMIT_MESSAGES["question_guest"]
        assert calls == []

    def test_a_repeated_question_replays_without_counting(self, monkeypatch):
        calls, counted = [], []
        monkeypatch.setattr(main.agent, "astream", answer_stream(calls))
        monkeypatch.setattr(quota, "_record", lambda *a: counted.append(a) or "ok")
        first = client.post("/chat/stream", json={"query": "Who was Ruth?"}).text
        again = client.post("/chat/stream", json={"query": "  who was ruth  "}).text
        assert "An answer" in first and "An answer" in again
        assert len(calls) == 1 and len(counted) == 1

    def test_a_prayer_is_never_replayed(self, monkeypatch):
        calls = []

        async def fake_astream(state, config=None, stream_mode=None):
            calls.append(state["query"])
            yield {"pray_with": {"answer": "## A prayer\nAmen.", "citations": []}}

        monkeypatch.setattr(main.agent, "astream", fake_astream)
        for _ in range(2):
            client.post("/chat/stream", json={"query": "Pray for my mother", "mode": "pray"})
        assert len(calls) == 2

    def test_a_question_too_long_is_refused(self):
        assert client.post("/chat/stream", json={"query": "x" * 2001}).status_code == 422

    def test_the_cache_keeps_its_size(self):
        for i in range(answer_cache.MAX_ENTRIES + 5):
            answer_cache.put(("BSB", str(i)), [])
        assert answer_cache.get(("BSB", "0")) is None
        assert answer_cache.get(("BSB", str(answer_cache.MAX_ENTRIES + 4))) == []


class TestVoice:
    @pytest.fixture
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: AuthUser(id="u1", email="a@b.c"))
        return {"Authorization": "Bearer t"}

    def test_out_of_calls_says_so_before_dialling(self, monkeypatch, signed_in):
        monkeypatch.setattr(quota, "used_today", lambda kind, subject: settings.quota_voice_calls)
        body = client.get("/me/voice", headers=signed_in).json()
        assert body["calls_left"] == 0 and body["message"] == quota.LIMIT_MESSAGES["voice"]

    def test_a_connected_call_is_counted(self, monkeypatch, signed_in):
        seen = []
        monkeypatch.setattr(quota, "_record", lambda *a: seen.append(a) or "ok")
        body = client.post("/me/voice/start", headers=signed_in).json()
        assert body == {"minutes": settings.voice_call_minutes}
        assert seen[0][:3] == ("u1", "voice", settings.quota_voice_calls)


class TestMcpKey:
    def test_the_stream_needs_the_key_once_one_is_set(self, monkeypatch):
        monkeypatch.setattr(settings, "mcp_secret", "s3cret")
        assert client.get("/mcp/sse").status_code == 401
        assert client.get("/mcp/sse?key=wrong").status_code == 401

    def test_the_key_is_accepted_as_a_header_or_a_parameter(self, monkeypatch):
        monkeypatch.setattr(settings, "mcp_secret", "s3cret")
        assert main._mcp_key_ok({"headers": [(b"authorization", b"Bearer s3cret")]})
        assert main._mcp_key_ok({"headers": [], "query_string": b"key=s3cret"})
        assert not main._mcp_key_ok({"headers": [], "query_string": b""})


class TestRefugeHistory:
    def test_a_long_talk_sends_only_its_latest_part(self):
        history = [{"role": "user", "content": "x" * 3000} for _ in range(10)]
        sent = nodes._listen_messages(history)
        assert len(sent) == nodes.LISTEN_HISTORY_CHARS // 3000
        assert all(isinstance(m, HumanMessage) for m in sent)

    def test_the_newest_message_always_goes_in(self):
        sent = nodes._listen_messages([{"role": "user", "content": "y" * 20000}])
        assert len(sent) == 1
