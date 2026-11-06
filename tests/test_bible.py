"""The Bible reader, verse notes, and the translation fetcher: pure helpers,
plus the routes with Supabase and auth faked out. Nothing here makes a real
network call."""

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.main as main
from app import auth, bible, notes
from app.auth import AuthUser
from app.plan import BOOK_CHAPTER_COUNTS
from app.retrieval import parse_reference

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")

_spec = importlib.util.spec_from_file_location(
    "fetch_translation", Path(__file__).resolve().parent.parent / "scripts" / "fetch_translation.py"
)
fetch_translation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_translation)


class FakeQuery:
    """Just enough of supabase-py's chainable query builder: records every
    filter and returns canned rows from execute()."""

    def __init__(self, rows, calls):
        self.rows = rows
        self.calls = calls

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            return self

        return method

    def execute(self):
        return type("Result", (), {"data": self.rows, "count": len(self.rows)})()


class FakeSupabase:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return FakeQuery(self.rows, self.calls)


class TestNeighbours:
    def test_within_a_book(self):
        assert bible.neighbours("John", 3) == ({"book": "John", "chapter": 2}, {"book": "John", "chapter": 4})

    def test_crosses_book_boundaries(self):
        assert bible.neighbours("Matthew", 1)[0] == {"book": "Malachi", "chapter": 4}
        assert bible.neighbours("Malachi", 4)[1] == {"book": "Matthew", "chapter": 1}

    def test_ends_of_the_canon(self):
        assert bible.neighbours("Genesis", 1)[0] is None
        assert bible.neighbours("Revelation", 22)[1] is None

    def test_one_chapter_books(self):
        assert bible.neighbours("Jude", 1) == ({"book": "3 John", "chapter": 1}, {"book": "Revelation", "chapter": 1})


class TestResolveChapter:
    def test_aliases_resolve(self):
        assert bible.resolve_chapter("psalm", 23) == "Psalms"
        assert bible.resolve_chapter("Song of Songs", 2) == "Song of Solomon"

    def test_unknown_book(self):
        with pytest.raises(HTTPException) as e:
            bible.resolve_chapter("Hezekiah", 1)
        assert e.value.status_code == 404

    def test_chapter_out_of_range(self):
        with pytest.raises(HTTPException) as e:
            bible.resolve_chapter("Jude", 2)
        assert "1 chapters" in e.value.detail


class TestRoutes:
    def test_books_is_the_whole_canon(self):
        body = client.get("/bible/books").json()
        assert len(body) == 66
        assert sum(b["chapters"] for b in body) == 1189
        assert body[0] == {"name": "Genesis", "chapters": 50, "order": 1, "testament": "OT", "genre": "law"}

    def test_chapter_returns_verses_and_neighbours(self, monkeypatch):
        fake = FakeSupabase([{"verse": 1, "text": "In the beginning was the Word"}])
        monkeypatch.setattr(bible, "get_supabase", lambda: fake)
        body = client.get("/bible/chapter", params={"book": "jn", "chapter": 1, "translation": "kjv"}).json()
        assert body["book"] == "John" and body["translation"] == "KJV"
        assert body["prev"] == {"book": "Luke", "chapter": 24}
        assert ("eq", ("translation", "KJV")) in fake.calls
        assert ("eq", ("book", "John")) in fake.calls

    def test_unloaded_translation_is_a_404(self, monkeypatch):
        monkeypatch.setattr(bible, "get_supabase", lambda: FakeSupabase([]))
        resp = client.get("/bible/chapter", params={"book": "John", "chapter": 1, "translation": "WEB"})
        assert resp.status_code == 404
        assert "hasn't been loaded" in resp.json()["detail"]

    def test_unregistered_translation_is_refused(self):
        resp = client.get("/bible/chapter", params={"book": "John", "chapter": 1, "translation": "NIV"})
        assert resp.status_code == 404

    def test_translations_lists_only_loaded_ones(self, monkeypatch):
        monkeypatch.setattr(bible, "_available", None)
        monkeypatch.setattr(bible, "_loaded", lambda code: code in ("BSB", "KJV"))
        body = client.get("/bible/translations").json()
        assert [t["code"] for t in body["translations"]] == ["BSB", "KJV"]
        assert body["translations"][1]["name"] == "King James Version"

    def test_translations_fall_back_to_default_on_error(self, monkeypatch):
        def boom(code):
            raise RuntimeError("db down")

        monkeypatch.setattr(bible, "_available", None)
        monkeypatch.setattr(bible, "_loaded", boom)
        assert bible.available_translations() == ["BSB"]


class TestNotes:
    def test_range_defaults_to_one_verse(self):
        note = notes.NoteIn(book="John", chapter=3, verse_start=16, body="Loved.")
        assert note.verse_end == 16

    def test_backwards_range_is_refused(self):
        with pytest.raises(ValidationError):
            notes.NoteIn(book="John", chapter=3, verse_start=18, verse_end=16, body="x")

    def test_blank_body_is_refused(self):
        with pytest.raises(ValidationError):
            notes.NoteIn(book="John", chapter=3, verse_start=16, body="   ")

    def test_note_ref(self):
        assert notes.note_ref({"book": "John", "chapter": 3, "verse_start": 16, "verse_end": 16}) == "John 3:16"
        assert notes.note_ref({"book": "Song of Solomon", "chapter": 2, "verse_start": 1, "verse_end": 3}) == "Song of Solomon 2:1-3"

    def test_note_ref_reads_back_through_parse_reference(self):
        ref = parse_reference(notes.note_ref({"book": "Song of Solomon", "chapter": 2, "verse_start": 1, "verse_end": 3}))
        assert (ref.book, ref.chapter, ref.verse_start, ref.verse_end) == ("Song of Solomon", 2, 1, 3)

    def test_notes_require_sign_in(self):
        assert client.get("/me/notes").status_code == 401
        assert client.post("/me/notes", json={}).status_code == 401

    def test_create_pins_to_canonical_book_and_owner(self, monkeypatch):
        saved = {}

        class Insert(FakeSupabase):
            def table(self, name):
                fake = self

                class Q(FakeQuery):
                    def insert(self, row):
                        saved.update(row)
                        fake.rows = [{**row, "id": "n1", "created_at": "", "updated_at": ""}]
                        self.rows = fake.rows
                        return self

                return Q(self.rows, self.calls)

        monkeypatch.setattr(auth, "_verify", lambda token: USER if token == "good" else None)
        monkeypatch.setattr(notes, "get_supabase", lambda: Insert([]))
        resp = client.post(
            "/me/notes",
            headers={"Authorization": "Bearer good"},
            json={"book": "psalm", "chapter": 23, "verse_start": 1, "verse_end": 3, "translation": "kjv", "body": "  He leads me.  "},
        )
        assert resp.status_code == 200
        assert saved["user_id"] == USER.id
        assert saved["book"] == "Psalms" and saved["translation"] == "KJV" and saved["body"] == "He leads me."
        assert resp.json()["ref"] == "Psalms 23:1-3"

    def test_create_refuses_a_chapter_that_does_not_exist(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        resp = client.post(
            "/me/notes",
            headers={"Authorization": "Bearer good"},
            json={"book": "Jude", "chapter": 2, "verse_start": 1, "body": "x"},
        )
        assert resp.status_code == 404


class TestSongOfSolomonReferences:
    def test_full_name_parses(self):
        ref = parse_reference("What does Song of Solomon 2:1 mean?")
        assert (ref.book, ref.chapter, ref.verse_start) == ("Song of Solomon", 2, 1)

    def test_song_of_songs_parses(self):
        assert parse_reference("song of songs 8:6").book == "Song of Solomon"


class TestFetchTranslation:
    def test_normalize_book(self):
        assert fetch_translation.normalize_book("I Samuel") == "1 Samuel"
        assert fetch_translation.normalize_book("III John") == "3 John"
        assert fetch_translation.normalize_book("Revelation of John") == "Revelation"
        assert fetch_translation.normalize_book("Song of Solomon") == "Song of Solomon"
        with pytest.raises(ValueError):
            fetch_translation.normalize_book("Tobit")

    def test_clean_text(self):
        assert fetch_translation.clean_text("  God said,   “Let there be light.”  ") == "God said, “Let there be light.”"
        assert fetch_translation.clean_text("no help for him in God. [Selah") == "no help for him in God. Selah"
        assert fetch_translation.clean_text("a lily of the valleys. Lover", "Song of Solomon") == "a lily of the valleys."
        # Only after a sentence ends, and only in the Song.
        assert fetch_translation.clean_text("like apples, Beloved", "Song of Solomon") == "like apples, Beloved"
        assert fetch_translation.clean_text("Greet the brothers. Beloved", "3 John") == "Greet the brothers. Beloved"

    def test_flatten_drops_empty_verses_and_sorts(self):
        source = {"books": []}
        for name, count in reversed(list(BOOK_CHAPTER_COUNTS.items())):
            source["books"].append({
                "name": {"1 Samuel": "I Samuel", "Revelation": "Revelation of John"}.get(name, name),
                "chapters": [{"chapter": c, "verses": [{"verse": 1, "text": "text"}, {"verse": 2, "text": ""}]} for c in range(1, count + 1)],
            })
        verses = fetch_translation.flatten(source)
        fetch_translation.check_chapters(verses)
        assert len(verses) == 1189
        assert verses[0]["book"] == "Genesis" and verses[-1]["book"] == "Revelation"

    def test_flatten_requires_every_book(self):
        with pytest.raises(ValueError, match="missing books"):
            fetch_translation.flatten({"books": [{"name": "Genesis", "chapters": []}]})
