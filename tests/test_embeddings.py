"""Compact embeddings: only the search translation is embedded, at
`settings.embedding_dim` dimensions, and the other translations borrow its
embeddings. A mismatch anywhere here doesn't raise; vector search just
quietly returns nothing (or the wrong neighbours), so these pin the contract
down. Nothing here makes a real OpenAI or Supabase call.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import connections, retrieval
from app.config import settings

_spec = importlib.util.spec_from_file_location(
    "ingest", Path(__file__).resolve().parent.parent / "scripts" / "ingest.py"
)
ingest = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ingest)

VERSE = {"book": "John", "chapter": 3, "verse": 16, "text": "For God so loved the world..."}


class TestVerseRow:
    def test_text_only_row_has_no_embedding_key(self):
        # Leaving the key out (rather than sending null) means an upsert can
        # never wipe an embedding that is already stored.
        row = ingest.verse_row(VERSE, "KJV")
        assert "embedding" not in row
        assert row["translation"] == "KJV"

    def test_embedded_row_carries_the_embedding(self):
        row = ingest.verse_row(VERSE, "BSB", [0.1, 0.2])
        assert row["embedding"] == [0.1, 0.2]

    def test_book_metadata_is_attached(self):
        row = ingest.verse_row(VERSE, "BSB")
        assert (row["book_order"], row["testament"], row["genre"]) == (43, "NT", "gospel")

    def test_unknown_book_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown book name"):
            ingest.verse_row({**VERSE, "book": "Hezekiah"}, "BSB")


def test_embed_query_asks_for_the_configured_dimension(monkeypatch):
    """Query embeddings must have the same length as the stored ones, or every
    `match_verses` call fails on the type check."""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.0] * kwargs["dimensions"])])

    monkeypatch.setattr(retrieval, "_openai", SimpleNamespace(embeddings=SimpleNamespace(create=create)))

    assert len(retrieval.embed_query("rest for the weary")) == settings.embedding_dim
    assert calls[0]["dimensions"] == settings.embedding_dim
    assert calls[0]["model"] == settings.embedding_model


def test_graph_seeds_borrow_the_search_translations_embedding(monkeypatch):
    """A KJV seed has no embedding of its own; it takes BSB's for the same
    verse, and a verse BSB lacks gets None rather than someone else's."""
    by_translation = {
        "KJV": [
            {"book": "John", "chapter": 3, "verse": 16, "text": "For God so loved..."},
            {"book": "John", "chapter": 3, "verse": 17, "text": "For God sent not..."},
        ],
        settings.search_translation: [{"verse": 16, "embedding": "[0.1,0.2]"}],
    }
    requested = []

    def fake_range(book, chapter, start, end, translation, columns):
        requested.append(translation)
        return by_translation[translation]

    monkeypatch.setattr(connections, "_verse_range_rows", fake_range)

    seeds = connections._seed_rows("John 3:16-17", "KJV")

    assert requested == ["KJV", settings.search_translation]
    assert [s["text"] for s in seeds] == ["For God so loved...", "For God sent not..."]
    assert [s["embedding"] for s in seeds] == ["[0.1,0.2]", None]
