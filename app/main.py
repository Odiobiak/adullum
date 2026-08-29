"""FastAPI service exposing the LangGraph agent over HTTP.

Two endpoints share one graph and one state shape:
  - POST /chat        — waits for the full run, returns the final answer.
  - POST /chat/stream — emits SSE progress events as the graph executes.

Both exist so the graph itself never has to know or care what's calling it —
a web page today, a voice pipeline or mobile app later, all talk to the same
contract.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import agent
from app.mcp_server import mcp
from app.observability import get_langfuse_handler
from app.schemas import ChatRequest, ChatResponse, Citation


def _run_config(request: ChatRequest) -> dict:
    """Shared config builder for both endpoints: attaches a Langfuse handler
    tagged "chat" (production traffic) when one is configured, tagged with the
    caller's session_id if given. Filters out the None case rather than passing
    it — LangChain rejects a bare None in the callbacks list.
    """
    handler = get_langfuse_handler(session_id=request.session_id, tags=["chat"])
    return {"callbacks": [handler] if handler else []}

app = FastAPI(title="Adullum")

# Dev-only: lets the static test page in web/index.html (opened via file:// or a
# throwaway local server, i.e. a different origin than the API) call these
# endpoints. Tighten to specific origins before this is exposed publicly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    """Liveness check — used by deploy platforms and by the test page to show a connection badge."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Non-streaming: waits for the full graph run, returns the final answer + citations.
    Good enough for a first web/CLI client; /chat/stream below is what a voice or
    mobile front-end will actually want.
    """
    result = await agent.ainvoke(
        {"query": request.query, "translation": request.translation}, config=_run_config(request)
    )
    citations = [
        Citation(book=v.book, chapter=v.chapter, verse=v.verse, translation=v.translation)
        for v in result.get("citations", [])
    ]
    return ChatResponse(answer=result["answer"], citations=citations, intent=result["intent"])


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> EventSourceResponse:
    """Streams graph progress as SSE: a `step` event per node (useful for a chat UI
    showing "retrieving verses..." etc.), then `answer` and `citations` events.
    Same graph, same state — this is the shape a voice front-end (TTS as tokens
    arrive) or mobile client would consume instead of the plain /chat endpoint.
    """

    async def event_generator() -> AsyncIterator[dict]:
        async for step in agent.astream(
            {"query": request.query, "translation": request.translation},
            config=_run_config(request),
            stream_mode="updates",
        ):
            for node_name, node_output in step.items():
                if node_name == "synthesize":
                    yield {"event": "answer", "data": node_output["answer"]}
                elif node_name == "format_citations":
                    citations = [
                        {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
                        for v in node_output["citations"]
                    ]
                    yield {"event": "citations", "data": json.dumps(citations)}
                else:
                    yield {"event": "step", "data": node_name}

    return EventSourceResponse(event_generator())


# Exposes ask_aquila as an MCP tool at /mcp/sse — this is what Cognigy's MCP
# Tool Node (or any other MCP client) connects to, instead of a bespoke webhook.
app.mount("/mcp", mcp.sse_app())

# Serves web/index.html at "/" and any future static assets alongside it.
# Mounted last so it never shadows the API routes above — FastAPI matches
# explicit paths first and falls through to the mount only for anything else.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "web", html=True), name="web")
