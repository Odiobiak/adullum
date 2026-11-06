"""Connections: loading classic cross-references, drawing them beside links by
meaning, and asking Aquila why two passages connect. Supabase and the model
are faked out; nothing here makes a real network call."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import connections
from app.agent import nodes
from app.plan import BOOK_CHAPTER_COUNTS
from app.schemas import Verse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ingest_cross_references as ingest  # noqa: E402

client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Loading the data
# ---------------------------------------------------------------------------
class TestIngest:
    def test_every_book_maps_to_the_apps_name(self):
        assert len(ingest.OSIS_BOOKS) == 66
        assert set(ingest.OSIS_BOOKS.values()) == set(BOOK_CHAPTER_COUNTS)
        assert ingest.parse_osis("Ps.23.1") == ("Psalms", 23, 1)
        assert ingest.parse_osis("1Cor.8.6") == ("1 Corinthians", 8, 6)
        assert ingest.parse_osis("Nope.1.1") is None

    def test_a_range_within_one_chapter_is_kept(self):
        row = ingest.parse_line("Gen.1.1\tProv.8.22-Prov.8.30\t78\n", min_votes=5)
        assert (row["from_book"], row["to_book"], row["to_chapter"]) == ("Genesis", "Proverbs", 8)
        assert (row["to_verse_start"], row["to_verse_end"], row["votes"]) == (22, 30, 78)

    def test_a_range_into_the_next_chapter_keeps_its_first_verse(self):
        row = ingest.parse_line("Gen.1.1\tGen.1.31-Gen.2.1\t12\n", min_votes=5)
        assert (row["to_chapter"], row["to_verse_start"], row["to_verse_end"]) == (1, 31, 31)

    def test_the_header_and_weak_links_are_skipped(self):
        assert ingest.parse_line("From Verse\tTo Verse\tVotes\t#www.openbible.info CC-BY\n", 5) is None
        assert ingest.parse_line("Gen.1.1\tRev.4.11\t4\n", min_votes=5) is None
        assert ingest.parse_line("Gen.1.1\tRev.4.11\t-3\n", min_votes=0) is None


# ---------------------------------------------------------------------------
# Building the graph
# ---------------------------------------------------------------------------
def test_one_pair_can_be_both_kinds_of_link():
    edges = {}
    connections.add_edge(edges, "Genesis 1:1", "John 1:1", "cross_ref", votes=120, passage="John 1:1-3")
    connections.add_edge(edges, "John 1:1", "Genesis 1:1", "meaning", weight=0.61)
    connections.add_edge(edges, "Genesis 1:1", "John 1:1", "meaning", weight=0.55)
    [edge] = edges.values()
    assert edge["kinds"] == ["cross_ref", "meaning"]
    assert (edge["weight"], edge["votes"], edge["passage"]) == (0.61, 120, "John 1:1-3")


def test_cross_ref_label():
    row = {"to_book": "Proverbs", "to_chapter": 8, "to_verse_start": 22, "to_verse_end": 30}
    assert connections.cross_ref_label(row) == "Proverbs 8:22-30"
    assert connections.cross_ref_label({**row, "to_verse_end": 22}) == "Proverbs 8:22"


def test_cross_references_are_drawn_even_without_an_embedding(monkeypatch):
    seed = {"book": "Genesis", "chapter": 1, "verse": 1, "text": "In the beginning", "embedding": None}
    monkeypatch.setattr(connections, "_seed_rows", lambda ref, tr: [seed])
    monkeypatch.setattr(connections, "_cross_references", lambda s, limit: [
        {"to_book": "John", "to_chapter": 1, "to_verse_start": 1, "to_verse_end": 3, "votes": 150},
    ])
    monkeypatch.setattr(connections, "_verse_range_rows", lambda book, chapter, start, end, tr, cols: [
        {"book": book, "chapter": chapter, "verse": start, "text": "In the beginning was the Word"},
    ])
    body = client.get("/connections", params={"refs": "Genesis 1:1"}).json()
    assert sorted(n["id"] for n in body["nodes"]) == ["Genesis 1:1", "John 1:1"]
    [edge] = body["edges"]
    assert edge["kinds"] == ["cross_ref"] and edge["passage"] == "John 1:1-3" and edge["weight"] is None


# ---------------------------------------------------------------------------
# "Why are these connected?"
# ---------------------------------------------------------------------------
def verse(book, chapter, n, text="..."):
    return Verse(book=book, chapter=chapter, verse=n, text=text, translation="KJV")


class TestExplainRoute:
    @pytest.fixture(autouse=True)
    def fresh_cache(self):
        connections._explained.cache_clear()
        yield
        connections._explained.cache_clear()

    def test_explains_with_both_passages_and_the_kinds_of_link(self, monkeypatch):
        calls = []
        monkeypatch.setattr(connections, "lookup_by_reference", lambda parsed, tr: [verse(parsed.book, parsed.chapter, parsed.verse_start)])

        def fake_explain(a, b, *, cross_ref, close_in_meaning, config=None):
            calls.append((a[0].book, b[0].book, cross_ref, close_in_meaning))
            return "Both speak of the beginning."

        monkeypatch.setattr(connections, "explain_link", fake_explain)
        payload = {"a": "Genesis 1:1", "b": "John 1:1", "translation": "kjv", "kinds": ["cross_ref"]}
        assert client.post("/connections/explain", json=payload).json()["explanation"] == "Both speak of the beginning."
        client.post("/connections/explain", json=payload)  # the same link again: cached
        assert calls == [("Genesis", "John", True, False)]

    def test_something_that_is_not_a_verse_is_a_404(self):
        assert client.post("/connections/explain", json={"a": "my day", "b": "John 1:1"}).status_code == 404


class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies)

    def invoke(self, messages, config=None):
        return type("Reply", (), {"content": self.replies.pop(0)})()


def test_explaining_never_names_another_verse(monkeypatch):
    monkeypatch.setattr(nodes, "_llm", FakeLLM(["Compare Jeremiah 29:11.", "Also Jeremiah 29:11."]))
    text = nodes.explain_link([verse("Genesis", 1, 1)], [verse("John", 1, 1)], cross_ref=True, close_in_meaning=False)
    assert "Jeremiah" not in text
    assert text.startswith("Genesis 1:1 and John 1:1 are linked in the classic cross-references")


def test_a_good_explanation_comes_back_as_written(monkeypatch):
    monkeypatch.setattr(nodes, "_llm", FakeLLM(["Genesis 1:1 opens with God creating; John 1:1 echoes those words."]))
    text = nodes.explain_link([verse("Genesis", 1, 1)], [verse("John", 1, 1)], cross_ref=True, close_in_meaning=True)
    assert text.startswith("Genesis 1:1 opens")
