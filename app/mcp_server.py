"""Exposes the LangGraph agent as an MCP (Model Context Protocol) server, so an
external agent platform — Cognigy's MCP Tool Node, in particular — can call
Aquila as a tool over a standard protocol instead of a bespoke webhook.

Mounted into app/main.py's FastAPI app at /mcp: one deploy, one process, and
the same graph run that powers /chat and /chat/stream also answers MCP tool
calls, so there's exactly one place Aquila's behavior is defined.
"""

import re

from mcp.server.mcpserver import MCPServer

from app.agent.graph import agent
from app.config import settings
from app.observability import get_langfuse_handler, trace_attributes

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
        "Aquila, a warm and steadfast Bible study companion who answers Scripture "
        "questions grounded strictly in the verses she retrieves, always citing "
        "her sources."
    ),
)


@mcp.tool()
async def ask_aquila(query: str, translation: str | None = None, session_id: str | None = None) -> dict:
    """Ask Aquila a Bible study question and get back a grounded answer plus
    the verse citations it's based on.

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
            id) to group this call with others from the same conversation in
            Langfuse. Omit if the caller has no natural session concept.
    """
    handler = get_langfuse_handler()
    config = {"callbacks": [handler] if handler else []}
    resolved_translation = translation or settings.default_translation
    with trace_attributes(session_id=session_id, tags=["mcp"], trace_name="mcp-ask-aquila"):
        result = await agent.ainvoke({"query": query, "translation": resolved_translation}, config=config)
    citations = [
        {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
        for v in result.get("citations", [])
    ]
    return {"answer": _spoken(result["answer"]), "citations": citations}
