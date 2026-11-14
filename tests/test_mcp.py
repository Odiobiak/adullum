"""The MCP tools Cognigy's voice agent calls (app/mcp_server.py). Retrieval is
stubbed, so nothing here touches the database or a model."""

import asyncio

from app import mcp_server
from app.schemas import Verse


def verse(book, chapter, number, text="..."):
    return Verse(book=book, chapter=chapter, verse=number, text=text, translation="BSB")


def run_find(monkeypatch, topic, found, translation=None):
    seen = {}

    def fake_retrieve(query, translation, k):
        seen.update(query=query, translation=translation, k=k)
        return found

    monkeypatch.setattr(mcp_server, "hybrid_retrieve", fake_retrieve)
    return asyncio.run(mcp_server.find_verses(topic, translation)), seen


def test_find_verses_returns_each_verse_word_for_word(monkeypatch):
    result, _ = run_find(monkeypatch, "peace when I'm anxious", [verse("Philippians", 4, 6, "Be anxious for nothing...")])
    assert result == {"verses": [{"reference": "Philippians 4:6", "text": "Be anxious for nothing...", "translation": "BSB"}]}


def test_a_topic_gets_a_few_verses_and_a_reference_its_passage(monkeypatch):
    _, topic = run_find(monkeypatch, "comfort in grief", [])
    _, passage = run_find(monkeypatch, "Psalm 23", [])
    assert topic["k"] == mcp_server.TOPIC_VERSES
    assert passage["k"] == mcp_server.PASSAGE_VERSES


def test_the_translation_falls_back_and_is_normalised(monkeypatch):
    _, default = run_find(monkeypatch, "hope", [])
    _, chosen = run_find(monkeypatch, "hope", [], translation="kjv")
    assert default["translation"] == mcp_server.settings.default_translation
    assert chosen["translation"] == "KJV"


def test_nothing_found_is_an_empty_list(monkeypatch):
    result, _ = run_find(monkeypatch, "zzz", [])
    assert result == {"verses": []}
