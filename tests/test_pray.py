"""Pray with Aquila: the "pray" mode's routing, its guard against invented
verses, and how /chat/stream carries its answer. The LLM, retrieval and the
compiled agent are faked out; nothing here makes a real network call."""

import json

from fastapi.testclient import TestClient

import app.main as main
from app.agent import graph, nodes
from app.schemas import Verse

client = TestClient(main.app)


def verse(book, chapter, n):
    return Verse(book=book, chapter=chapter, verse=n, text="...", translation="KJV")


class FakeWarmLLM:
    """Hands out drafted replies in order and keeps each system prompt."""

    def __init__(self, replies):
        self.replies, self.prompts = list(replies), []

    def invoke(self, messages, config=None):
        self.prompts.append(messages[0].content)
        return type("Reply", (), {"content": self.replies.pop(0)})()


def run(monkeypatch, replies, verses):
    warm = FakeWarmLLM(replies)
    monkeypatch.setattr(nodes, "_warm_llm", warm)
    monkeypatch.setattr(nodes, "hybrid_retrieve", lambda query, translation, k: list(verses))
    state = {"mode": "pray", "query": "On Philippians 4:6: Would you pray with me about this? My sister's new job", "translation": "KJV"}
    return nodes.pray_with(state, config=None), warm


def test_pray_mode_has_its_own_entry():
    assert graph._entry({"mode": "pray"}) == "pray_with"


def test_the_verses_it_quotes_become_citations(monkeypatch):
    listed = [verse("Philippians", 4, 6), verse("Isaiah", 41, 10)]
    result, warm = run(monkeypatch, ["## Scripture to hold onto\n... (Philippians 4:6)\n\n## A prayer\nFather... Amen."], listed)
    assert result["citations"] == [listed[0]]
    assert "Philippians 4:6" in warm.prompts[0]


def test_an_invented_verse_means_a_prayer_without_scripture(monkeypatch):
    listed = [verse("Philippians", 4, 6)]
    result, warm = run(monkeypatch, ["Jeremiah 29:11", "Still Jeremiah 29:11", "## A prayer\nFather... Amen."], listed)
    assert result["answer"].startswith("## A prayer")
    assert result["citations"] == [] and result["verses"] == []
    assert "leave out the Scripture heading" in warm.prompts[-1]


def test_stream_sends_the_prayer_and_its_verses_with_no_followups(monkeypatch):
    seen = {}

    async def fake_astream(state, config=None, stream_mode=None):
        seen["state"] = state
        yield {"pray_with": {"answer": "## A prayer\nFather... Amen.", "citations": [verse("Philippians", 4, 6)]}}

    monkeypatch.setattr(main.agent, "astream", fake_astream)
    body = client.post("/chat/stream", json={"query": "Pray with me", "mode": "pray"}).text
    assert seen["state"]["mode"] == "pray" and seen["state"]["want_followups"] is False
    assert "Father... Amen." in body
    citations = next(line for line in body.splitlines() if line.startswith("data:") and "Philippians" in line)
    assert json.loads(citations.removeprefix("data:").strip()) == [
        {"book": "Philippians", "chapter": 4, "verse": 6, "translation": "KJV"}
    ]


def test_an_unknown_mode_is_rejected():
    assert client.post("/chat", json={"query": "hi", "mode": "sing"}).status_code == 422
