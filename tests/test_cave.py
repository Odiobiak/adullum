"""My Cave, memory, and the knowledge graph: the pure helpers, plus the API's
auth gates and chat wiring with Supabase, auth, and the agent mocked out.
Nothing here makes a real network call."""

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.main as main
from app import auth, cave, connections, memory
from app.agent.nodes import memory_block
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")


class TestBookMeta:
    def test_genres_follow_ingest_buckets(self):
        assert connections.book_meta("Genesis") == {"order": 1, "testament": "OT", "genre": "law"}
        assert connections.book_meta("Psalms")["genre"] == "poetry"
        assert connections.book_meta("Malachi") == {"order": 39, "testament": "OT", "genre": "prophecy"}
        assert connections.book_meta("John")["genre"] == "gospel"
        assert connections.book_meta("Acts")["genre"] == "history"
        assert connections.book_meta("Jude")["genre"] == "epistle"
        assert connections.book_meta("Revelation") == {"order": 66, "testament": "NT", "genre": "apocalyptic"}


class TestMemoryBlock:
    def test_empty_without_memories(self):
        assert memory_block({"query": "q"}) == ""
        assert memory_block({"query": "q", "memories": []}) == ""

    def test_lists_memories_and_marks_them_not_scripture(self):
        block = memory_block({"memories": ["They are studying Romans."]})
        assert "- They are studying Romans." in block
        assert "not Scripture" in block


class TestDated:
    def test_recent_and_old(self):
        now = datetime.now(timezone.utc)
        assert memory.dated("x", now.isoformat()).startswith("(earlier today)")
        assert memory.dated("x", (now - timedelta(days=3)).isoformat()).startswith("(3 days ago)")
        assert memory.dated("x", (now - timedelta(days=21)).isoformat()).startswith("(about 3 weeks ago)")

    def test_bad_timestamp_falls_back_to_content(self):
        assert memory.dated("x", "not a date") == "x"


class TestJournalHelpers:
    def test_clean_tags(self):
        assert cave._clean_tags(["#Romans", "romans", " Prayer ", ""]) == ["romans", "prayer"]

    def test_memory_text_includes_place_mood_and_reflection(self):
        text = cave._journal_memory_text({"passage_ref": "Psalms 42:5", "mood": "waiting", "reflection": "Still hoping."})
        assert text == 'They journaled on Psalms 42:5, in a season of waiting, writing: "Still hoping."'

    def test_memory_text_truncates(self):
        text = cave._journal_memory_text({"question": "q", "reflection": "a" * 400})
        assert text.endswith('..."') and len(text) < 340

    def test_valid_uuid(self):
        assert cave._valid_uuid("sess-123") is None
        assert cave._valid_uuid(None) is None
        assert cave._valid_uuid(USER.id) == USER.id


class TestRememberJournal:
    """Journal entries become notes about the person only when the person has
    let Aquila see them and memory is on. The cave is otherwise private."""

    ENTRY = {"id": "j1", "passage_ref": "Psalms 42:5", "reflection": "Still hoping.", "aquila_sees": True}

    class FakeDb:
        """Records the chained calls made against user_memories."""

        def __init__(self):
            self.calls = []

        def table(self, name):
            self.calls.append(("table", name))
            return self

        def __getattr__(self, name):
            return lambda *args, **kwargs: self.calls.append((name, args)) or self

    def fake(self, monkeypatch, enabled):
        db, stored = self.FakeDb(), []
        monkeypatch.setattr(cave, "get_supabase", lambda: db)
        monkeypatch.setattr(memory, "memory_enabled", lambda user_id: enabled)
        monkeypatch.setattr(memory, "store_note", lambda *args, **kwargs: stored.append(kwargs))
        return db, stored

    def test_stored_when_memory_is_on(self, monkeypatch):
        _, stored = self.fake(monkeypatch, enabled=True)
        cave._remember_journal(USER, self.ENTRY)
        assert stored == [{"kind": "journal", "journal_id": "j1"}]

    def test_not_stored_when_memory_is_off(self, monkeypatch):
        _, stored = self.fake(monkeypatch, enabled=False)
        cave._remember_journal(USER, self.ENTRY)
        assert stored == []

    def test_editing_with_memory_off_still_clears_the_old_note(self, monkeypatch):
        db, stored = self.fake(monkeypatch, enabled=False)
        cave._remember_journal(USER, self.ENTRY, replace=True)
        assert ("delete", ()) in db.calls
        assert ("eq", ("journal_id", "j1")) in db.calls and ("eq", ("user_id", USER.id)) in db.calls
        assert stored == []

    def test_an_empty_reflection_is_not_stored(self, monkeypatch):
        _, stored = self.fake(monkeypatch, enabled=True)
        cave._remember_journal(USER, {**self.ENTRY, "reflection": "  "})
        assert stored == []

    def test_a_private_entry_is_not_stored(self, monkeypatch):
        _, stored = self.fake(monkeypatch, enabled=True)
        cave._remember_journal(USER, {**self.ENTRY, "aquila_sees": False})
        cave._remember_journal(USER, {k: v for k, v in self.ENTRY.items() if k != "aquila_sees"})
        assert stored == []

    def test_taking_an_entry_back_clears_its_note(self, monkeypatch):
        db, stored = self.fake(monkeypatch, enabled=True)
        cave._remember_journal(USER, {**self.ENTRY, "aquila_sees": False}, replace=True)
        assert ("delete", ()) in db.calls and ("eq", ("journal_id", "j1")) in db.calls
        assert stored == []


class TestSelectPrivate:
    def test_reads_without_the_column_until_the_migration_runs(self):
        asked = []

        def run(fields):
            asked.append(fields)
            if "aquila_sees" in fields:
                raise APIError({"code": "42703", "message": "column journal_entries.aquila_sees does not exist"})
            return ["row"]

        assert cave.select_private(run, "id, reflection, aquila_sees") == ["row"]
        assert asked == ["id, reflection, aquila_sees", "id, reflection"]

    def test_other_errors_are_not_hidden(self):
        def run(fields):
            raise APIError({"code": "42P01", "message": "relation does not exist"})

        try:
            cave.select_private(run, "id, aquila_sees")
        except APIError as err:
            assert err.code == "42P01"
        else:
            raise AssertionError("expected the error to reach the caller")


class TestBearer:
    def test_parses_only_bearer(self):
        assert auth._bearer("Bearer abc") == "abc"
        assert auth._bearer("bearer  abc ") == "abc"
        assert auth._bearer("Basic abc") is None
        assert auth._bearer("Bearer ") is None
        assert auth._bearer(None) is None


class TestAuthGates:
    def test_me_requires_sign_in(self):
        assert client.get("/me").status_code == 401
        assert client.get("/me/journal").status_code == 401
        assert client.delete("/me/memories").status_code == 401

    def test_invalid_token_is_rejected(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: None)
        resp = client.get("/me/journal", headers={"Authorization": "Bearer nope"})
        assert resp.status_code == 401

    def test_bad_email_is_rejected_before_supabase(self):
        resp = client.post("/auth/magic-link", json={"email": "not-an-email"})
        assert resp.status_code == 422


class TestChatStreamSignedIn:
    def test_recalls_memories_and_records_the_turn(self, monkeypatch):
        seen_state = {}
        recorded = {}

        async def fake_astream(state, config=None, stream_mode=None):
            seen_state.update(state)
            yield {"synthesize": {"answer": "An answer"}}
            yield {"format_citations": {"citations": []}}

        monkeypatch.setattr(main.agent, "astream", fake_astream)
        monkeypatch.setattr(auth, "_verify", lambda token: USER if token == "good" else None)
        monkeypatch.setattr(main, "recall", lambda user_id, query: ["(3 days ago) They are studying Romans."])
        monkeypatch.setattr(cave, "record_turn", lambda *args: recorded.setdefault("args", args))

        resp = client.post(
            "/chat/stream",
            json={"query": "What next?", "session_id": USER.id},
            headers={"Authorization": "Bearer good"},
        )
        assert resp.status_code == 200
        assert "event: memory" in resp.text
        assert seen_state["memories"] == ["(3 days ago) They are studying Romans."]
        assert recorded["args"][0] == USER
        assert recorded["args"][3] == "An answer"

    def test_guest_gets_no_memories_and_nothing_recorded(self, monkeypatch):
        seen_state = {}
        called = []

        async def fake_astream(state, config=None, stream_mode=None):
            seen_state.update(state)
            yield {"synthesize": {"answer": "An answer"}}

        monkeypatch.setattr(main.agent, "astream", fake_astream)
        monkeypatch.setattr(cave, "record_turn", lambda *args: called.append(args))

        resp = client.post("/chat/stream", json={"query": "Hi"})
        assert resp.status_code == 200
        assert "event: memory" not in resp.text
        assert seen_state["memories"] == []
        assert called == []


def test_connections_needs_a_reference():
    assert client.get("/connections", params={"refs": " ; "}).status_code == 400


def test_connections_payload_is_json_serialisable():
    node = connections._node({"book": "John", "chapter": 3, "verse": 16, "text": "For God so loved"}, seed=True)
    assert json.loads(json.dumps(node))["id"] == "John 3:16"


class TestProfileRow:
    """PATCH /me's welcome flag only ever stamps the tour as seen."""

    def test_welcomed_stamps_the_time(self):
        row = cave.profile_row(cave.ProfilePatch(welcomed=True))
        assert set(row) == {"welcomed_at"}
        datetime.fromisoformat(row["welcomed_at"])

    def test_welcomed_false_changes_nothing(self):
        assert cave.profile_row(cave.ProfilePatch(welcomed=False, display_name="Ruth")) == {"display_name": "Ruth"}


class TestBetaFlag:
    """/me tells the page whether Adullam is in beta (web/welcome.js::openBeta)."""

    def test_me_reports_the_beta_setting(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        monkeypatch.setattr(cave, "_ensure_profile", lambda user: {"display_name": "Ruth"})
        monkeypatch.setattr(cave, "_db_call", lambda fn: 0)
        headers = {"Authorization": "Bearer good"}
        for beta in (True, False):
            monkeypatch.setattr(cave.settings, "beta", beta)
            assert client.get("/me", headers=headers).json()["beta"] is beta
