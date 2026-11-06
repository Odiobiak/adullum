"""Highlights: joining verses into passages for the Notes tab, and the paint
route reading verse text from the database. Supabase and auth are faked out;
nothing here makes a real network call."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, highlights
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")


def row(book, chapter, verse, color, created="2026-11-01T00:00:00+00:00", text=None):
    return {"book": book, "chapter": chapter, "verse": verse, "color": color, "translation": "KJV",
            "verse_text": text or f"v{verse}", "created_at": created}


class TestGroupHighlights:
    def test_neighbouring_verses_of_one_colour_join(self):
        passages = highlights.group_highlights([row("John", 3, 17, "gold"), row("John", 3, 16, "gold")])
        assert [p["ref"] for p in passages] == ["John 3:16-17"]
        assert passages[0]["text"] == "v16 v17"

    def test_a_gap_or_a_new_colour_starts_a_new_passage(self):
        passages = highlights.group_highlights([
            row("John", 3, 16, "gold"), row("John", 3, 17, "blue"), row("John", 3, 19, "blue"),
        ])
        assert sorted(p["ref"] for p in passages) == ["John 3:16", "John 3:17", "John 3:19"]

    def test_chapters_never_join(self):
        passages = highlights.group_highlights([row("John", 3, 36, "gold"), row("John", 4, 1, "gold")])
        assert len(passages) == 2

    def test_most_recent_first(self):
        passages = highlights.group_highlights([
            row("Genesis", 1, 1, "gold", created="2026-10-01T00:00:00+00:00"),
            row("Romans", 8, 28, "rose", created="2026-11-04T00:00:00+00:00"),
        ])
        assert [p["ref"] for p in passages] == ["Romans 8:28", "Genesis 1:1"]


class TestPaint:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    def test_one_row_per_verse_with_text_from_the_database(self, monkeypatch):
        upserted = []

        class FakeQuery:
            def __init__(self, name):
                self.name = name

            def __getattr__(self, attr):
                return lambda *a, **k: self

            def upsert(self, rows, **kwargs):
                upserted.extend(rows)
                return self

            def execute(self):
                rows = [{"verse": 16, "text": "For God so loved"}, {"verse": 17, "text": "For God sent not"}]
                return type("Result", (), {"data": rows if self.name == "verses" else []})()

        monkeypatch.setattr(highlights, "get_supabase", lambda: type("Db", (), {"table": lambda self, n: FakeQuery(n)})())
        resp = client.put(
            "/me/highlights",
            json={"book": "jn", "chapter": 3, "verse_start": 16, "verse_end": 17, "color": "gold", "translation": "kjv"},
            headers={"Authorization": "Bearer t"},
        )
        assert resp.status_code == 200
        assert [(r["book"], r["verse"], r["verse_text"]) for r in upserted] == [
            ("John", 16, "For God so loved"), ("John", 17, "For God sent not"),
        ]
        assert all(r["user_id"] == USER.id and r["translation"] == "KJV" for r in upserted)

    def test_unknown_colour_is_rejected(self):
        resp = client.put(
            "/me/highlights",
            json={"book": "John", "chapter": 3, "verse_start": 16, "color": "purple"},
            headers={"Authorization": "Bearer t"},
        )
        assert resp.status_code == 422


def test_highlights_require_sign_in():
    assert client.get("/me/highlights").status_code == 401
