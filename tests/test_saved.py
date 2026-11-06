"""Saved: one-tap saving of verses and Aquila's answers. Supabase, auth and
verse lookups are faked out; nothing here makes a real network call."""

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.main as main
from app import auth, saved
from app.auth import AuthUser
from app.schemas import Verse
from tests.test_refuge import FakeDb

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
HEADERS = {"Authorization": "Bearer t"}
ITEM_ID = "55555555-5555-5555-5555-555555555555"


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: USER)


def use_db(monkeypatch, db):
    monkeypatch.setattr(saved, "get_supabase", lambda: db)
    return db


def fake_lookup(monkeypatch, texts):
    """Answers lookup_by_reference with one Verse per text."""
    def lookup(parsed, translation):
        return [Verse(book=parsed.book, chapter=parsed.chapter, verse=parsed.verse_start + i, text=t, translation=translation)
                for i, t in enumerate(texts)]

    monkeypatch.setattr(saved, "lookup_by_reference", lookup)


class TestSaveVerse:
    def test_reads_the_words_from_the_database_not_the_browser(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb())
        fake_lookup(monkeypatch, ["For God so loved the world,", "that He gave His one and only Son,"])
        body = client.post("/me/saved/verse", json={"ref": "John 3:16-17", "translation": "bsb"}, headers=HEADERS).json()
        row = next(w[2] for w in db.written if w[0] == "saved_items")
        assert row["user_id"] == USER.id and row["kind"] == "verse" and row["translation"] == "BSB"
        assert (row["book"], row["chapter"], row["verse_start"], row["verse_end"]) == ("John", 3, 16, 17)
        assert row["verse_text"] == "For God so loved the world, that He gave His one and only Son,"
        assert body["ref"] == "John 3:16-17" and body["already"] is False

    def test_saving_it_again_returns_the_one_already_saved(self, monkeypatch, signed_in):
        existing = {"id": ITEM_ID, "kind": "verse", "book": "John", "chapter": 3, "verse_start": 16, "verse_end": 16}

        class AlreadySaved(FakeDb):
            """The insert hits the unique index; the lookup after it finds the row."""

            def table(self, name):
                query = super().table(name)
                execute = query.execute

                def run():
                    if self.written and self.written[-1][1] == "insert" and not self.rows.get(name):
                        self.rows[name] = [existing]
                        raise APIError({"code": "23505", "message": "duplicate key"})
                    return execute()

                query.execute = run
                return query

        db = use_db(monkeypatch, AlreadySaved())
        fake_lookup(monkeypatch, ["For God so loved the world"])
        body = client.post("/me/saved/verse", json={"ref": "John 3:16"}, headers=HEADERS).json()
        assert body["id"] == ITEM_ID and body["already"] is True
        assert db.filtered("saved_items", "user_id", USER.id)

    @pytest.mark.parametrize("ref", ["not a verse", "John 3"])
    def test_refuses_what_isnt_a_passage(self, monkeypatch, signed_in, ref):
        use_db(monkeypatch, FakeDb())
        fake_lookup(monkeypatch, ["x"])
        assert client.post("/me/saved/verse", json={"ref": ref}, headers=HEADERS).status_code == 422

    def test_refuses_more_than_a_handful_of_verses(self, monkeypatch, signed_in):
        use_db(monkeypatch, FakeDb())
        fake_lookup(monkeypatch, ["x"])
        resp = client.post("/me/saved/verse", json={"ref": "Psalm 119:1-80"}, headers=HEADERS)
        assert resp.status_code == 422


class TestSaveAnswer:
    def test_keeps_the_question_answer_and_citations(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb())
        body = {"question": " Why did Jesus weep? ", "answer": "## The passage\nJesus wept.", "citations": [{"book": "John", "chapter": 11, "verse": 35}]}
        assert client.post("/me/saved/answer", json=body, headers=HEADERS).status_code == 200
        row = next(w[2] for w in db.written if w[0] == "saved_items")
        assert row["kind"] == "answer" and row["user_id"] == USER.id
        assert row["question"] == "Why did Jesus weep?" and row["citations"] == [{"book": "John", "chapter": 11, "verse": 35}]


class TestListAndRemove:
    def test_lists_only_this_persons_items_with_verse_references(self, monkeypatch, signed_in):
        verse = {"id": "v", "kind": "verse", "book": "Psalms", "chapter": 23, "verse_start": 1, "verse_end": 3}
        answer = {"id": "a", "kind": "answer", "question": "Q", "answer": "A"}
        db = use_db(monkeypatch, FakeDb({"saved_items": [verse, answer]}))
        rows = client.get("/me/saved", headers=HEADERS).json()
        assert rows[0]["ref"] == "Psalms 23:1-3" and "ref" not in rows[1]
        assert db.filtered("saved_items", "user_id", USER.id)

    def test_remove_is_scoped_to_the_signed_in_person(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb())
        assert client.delete(f"/me/saved/{ITEM_ID}", headers=HEADERS).status_code == 200
        assert db.filtered("saved_items", "user_id", USER.id) and db.filtered("saved_items", "id", ITEM_ID)

    def test_needs_sign_in(self):
        assert client.get("/me/saved").status_code == 401
