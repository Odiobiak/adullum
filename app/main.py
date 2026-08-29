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
from mcp.server.transport_security import TransportSecuritySettings
from sse_starlette.sse import EventSourceResponse

from app.agent.graph import agent
from app.config import settings
from app.mcp_server import mcp
from app.observability import get_langfuse_handler, trace_attributes
from app.schemas import ChatRequest, ChatResponse, Citation


def _run_config() -> dict:
    """Shared config builder for both endpoints: attaches the Langfuse callback
    handler when one is configured. Filters out the None case rather than
    passing it — LangChain rejects a bare None in the callbacks list. Trace-level
    attributes (session_id, tags, trace_name) are applied separately via
    trace_attributes() wrapping the actual invocation — see app/observability.py.
    """
    handler = get_langfuse_handler()
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
    with trace_attributes(session_id=request.session_id, tags=["chat"], trace_name="chat"):
        result = await agent.ainvoke(
            {"query": request.query, "translation": request.translation}, config=_run_config()
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
        with trace_attributes(session_id=request.session_id, tags=["chat-stream"], trace_name="chat-stream"):
            async for step in agent.astream(
                {"query": request.query, "translation": request.translation},
                config=_run_config(),
                stream_mode="updates",
            ):
                for node_name, node_output in step.items():
                    if node_name == "synthesize":
                        yield {"event": "answer", "data": node_output["answer"]}
                    elif node_name == "answer_meta":
                        # Small-talk/identity questions skip synthesize/format_citations
                        # entirely (see graph.py) — this node carries both keys at once.
                        yield {"event": "answer", "data": node_output["answer"]}
                        yield {"event": "citations", "data": json.dumps([])}
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
# The SSE transport's DNS-rebinding defense rejects any Host header not in
# this allowlist (defaults to 127.0.0.1 only) — the deployed hostname has to
# be added via MCP_ALLOWED_HOSTS or every request 400s with "Invalid Host header".
_mcp_hosts = [h.strip() for h in settings.mcp_allowed_hosts.split(",") if h.strip()]
_mcp_origins = [f"{'http' if h.split(':')[0] in ('127.0.0.1', 'localhost') else 'https'}://{h}" for h in _mcp_hosts]
app.mount(
    "/mcp",
    mcp.sse_app(transport_security=TransportSecuritySettings(allowed_hosts=_mcp_hosts, allowed_origins=_mcp_origins)),
)

# Serves web/index.html at "/" and any future static assets alongside it.
# Mounted last so it never shadows the API routes above — FastAPI matches
# explicit paths first and falls through to the mount only for anything else.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "web", html=True), name="web")
