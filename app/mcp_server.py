"""Exposes the LangGraph agent as an MCP (Model Context Protocol) server, so an
external agent platform — Cognigy's MCP Tool Node, in particular — can call
Aquila as a tool over a standard protocol instead of a bespoke webhook.

Mounted into app/main.py's FastAPI app at /mcp: one deploy, one process, and
the same graph run that powers /chat and /chat/stream also answers MCP tool
calls, so there's exactly one place Aquila's behavior is defined.
"""

from mcp.server.mcpserver import MCPServer

from app.agent.graph import agent
from app.config import settings

mcp = MCPServer(
    name="aquila",
    description=(
        "Aquila, a warm and steadfast Bible study companion who answers Scripture "
        "questions grounded strictly in the verses she retrieves, always citing "
        "her sources."
    ),
)


@mcp.tool()
async def ask_aquila(query: str, translation: str | None = None) -> dict:
    """Ask Aquila a Bible study question and get back a grounded answer plus
    the verse citations it's based on.

    Args:
        query: The question to ask, in natural language (e.g. "What does
            Romans 8:28 mean?" or "What does the Bible say about anxiety?").
        translation: Bible translation to answer from (e.g. "BSB"). Falls
            back to the app's configured default translation if omitted.
    """
    result = await agent.ainvoke(
        {"query": query, "translation": translation or settings.default_translation}
    )
    citations = [
        {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
        for v in result.get("citations", [])
    ]
    return {"answer": result["answer"], "citations": citations}
