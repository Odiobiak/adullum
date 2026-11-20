"""Exposes Aquila as an MCP (Model Context Protocol) server, so an external
agent platform (Cognigy's MCP Tool Node, in particular) can call her as a
tool over a standard protocol instead of a bespoke webhook.

Two tools, for Aquila's voice calls, in Refuge and on the Aquila page
(docs/cognigy-voice.md):
  find_verses  verses word for word from the database, no model call, about a
               second; what the voice agent quotes from.
  ask_aquila   the full study graph, for a real Bible question.

Mounted into app/main.py's FastAPI app at /mcp: one deploy, one process, and
the same graph run that powers /chat and /chat/stream also answers MCP tool
calls, so there's exactly one place Aquila's behavior is defined.
"""

import asyncio
import re

from mcp.server.mcpserver import MCPServer

from app import quota
from app.agent.graph import agent
from app.config import settings
from app.retrieval import hybrid_retrieve, parse_reference

# synthesize() shapes its answer with Markdown headings for the web client's
# renderer. A voice gateway speaks whatever this tool returns verbatim, so
# "## The passage" would be read out hashes and all. These turn the structure
# back into something sayable rather than stripping it out, since the movements
# of the study are just as useful spoken as they are on screen.
_HEADING_RE = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]*(.+?)[ \t]*#*[ \t]*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _spoken(answer: str) -> str:
    """Renders the answer as something a TTS voice can read aloud cleanly."""
    text = _HEADING_RE.sub(lambda m: f"{m.group(1).rstrip('.:')}.", answer)
    return _BOLD_RE.sub(r"\1", text)

mcp = MCPServer(
    name="aquila",
    description=(
        "Aquila, a warm and steadfast companion who loves God. find_verses looks up "
        "Bible verses word for word, fast enough for a voice call; ask_aquila gives a "
        "full, grounded answer to a Bible study question."
    ),
)

# How many verses find_verses returns: a few to choose from on a topic, and
# a short passage when a reference is named. Few enough to say aloud.
TOPIC_VERSES = 3
PASSAGE_VERSES = 8


@mcp.tool()
async def find_verses(topic: str, translation: str | None = None) -> dict:
    """Look up Bible verses on a topic, or at a reference, word for word.

    Built for Aquila's voice calls: it reads the verses straight from
    the database with no model call, so it answers in about a second. Quote
    only the verses this returns, exactly as written, and name each reference.
    Never quote a verse from memory.

    Args:
        topic: What to look for, in plain words ("peace when I'm anxious",
            "God's comfort in grief") or a reference ("Psalm 23", "John 14:27").
        translation: Bible translation (e.g. "BSB"). Falls back to the app's
            default when omitted.

    Returns:
        {"verses": [{"reference", "text", "translation"}]}, empty when nothing
        was found, in which case say so rather than quoting anything.
    """
    resolved = (translation or settings.default_translation).upper()
    # A named reference gets its passage; a topic gets the closest few verses.
    k = PASSAGE_VERSES if parse_reference(topic) else TOPIC_VERSES
    verses = await asyncio.to_thread(hybrid_retrieve, topic, resolved, k)
    return {
        "verses": [
            {"reference": f"{v.book} {v.chapter}:{v.verse}", "text": v.text, "translation": v.translation}
            for v in verses
        ]
    }


@mcp.tool()
async def ask_aquila(query: str, translation: str | None = None, session_id: str | None = None) -> dict:
    """Ask Aquila a Bible study question and get back a grounded answer plus
    the verse citations it's based on.

    Slower than find_verses (several model calls, often ten seconds or more)
    and longer, so on a voice call use it only for a real study question
    ("What does Romans 8:28 mean?") and share the heart of the answer briefly.

    The answer comes back as plain speakable prose (no Markdown), so a voice
    gateway can read it straight out. No follow-up questions are generated for
    this path: they are something you skim and click, and read aloud they
    become a menu the caller has to keep in their head.

    Args:
        query: The question to ask, in natural language (e.g. "What does
            Romans 8:28 mean?" or "What does the Bible say about anxiety?").
        translation: Bible translation to answer from (e.g. "BSB"). Falls
            back to the app's configured default translation if omitted.
        session_id: Optional caller-supplied id (e.g. a Cognigy conversation
            id). Accepted for callers that send one; nothing is traced, so
            it isn't used.
    """
    # Voice calls are never traced (Refuge promises it, and the study call
    # keeps the same rule), so these runs pass no Langfuse callback, like
    # app/refuge.py's.
    # A call arrives from Cognigy with no person attached (each call was
    # counted against its caller when it connected, app/refuge.py), so its
    # questions count only toward the whole app's daily budget.
    if not await asyncio.to_thread(quota.spend_shared, "question", "voice"):
        return {"answer": quota.LIMIT_MESSAGES["budget"], "citations": []}
    resolved_translation = translation or settings.default_translation
    result = await agent.ainvoke({"query": query, "translation": resolved_translation}, config={"callbacks": []})
    citations = [
        {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
        for v in result.get("citations", [])
    ]
    return {"answer": _spoken(result["answer"]), "citations": citations}
