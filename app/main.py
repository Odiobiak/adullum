"""FastAPI service exposing the LangGraph agent over HTTP.

Two endpoints share one graph and one state shape:
  - POST /chat        — waits for the full run, returns the final answer.
  - POST /chat/stream — emits SSE progress events as the graph executes.

Both exist so the graph itself never has to know or care what's calling it —
a web page today, a voice pipeline or mobile app later, all talk to the same
contract.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from mcp.server.transport_security import TransportSecuritySettings
from sse_starlette.sse import EventSourceResponse

from app import bible, cave, connections, hearth, highlights, memorize, notes, one_another, prayers, reading_plans, refuge, sermons
from app.agent.graph import agent
from app.auth import AuthUser, optional_user
from app.config import settings
from app.db import get_supabase
from app.mcp_server import mcp
from app.memory import recall
from app.observability import get_langfuse_handler, trace_attributes
from app.pdf import render_plan_pdf
from app.plan import generate_overview, generate_schedule
from app.schemas import ChatRequest, ChatResponse, Citation, PlanDay, PlanRequest, PlanResponse


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


app.include_router(bible.router)
app.include_router(cave.router)
app.include_router(connections.router)
app.include_router(hearth.router)
app.include_router(highlights.router)
app.include_router(memorize.router)
app.include_router(notes.router)
app.include_router(one_another.router)
app.include_router(sermons.router)
app.include_router(prayers.router)
app.include_router(reading_plans.router)
app.include_router(refuge.router)

# Holds a reference to each after-turn save until it finishes. asyncio only
# keeps a weak reference to a bare create_task(), so without this a save could
# be garbage collected halfway through.
_background: set[asyncio.Task] = set()


def _initial_state(request: ChatRequest, memories: list[str]) -> dict:
    return {
        "query": request.query,
        "translation": request.translation,
        "mode": request.mode,
        # Follow-ups carry a study further; a prayer doesn't need them.
        "want_followups": request.mode == "study",
        "memories": memories,
    }


async def _memories_for(user: AuthUser | None, query: str) -> list[str]:
    if not user:
        return []
    return await asyncio.to_thread(recall, user.id, query)


@app.get("/health")
def health() -> dict:
    """Liveness check — used by deploy platforms and by the test page to show a connection badge."""
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    background: BackgroundTasks,
    user: AuthUser | None = Depends(optional_user),
) -> ChatResponse:
    """Non-streaming: waits for the full graph run, returns the final answer + citations.
    Good enough for a first web/CLI client; /chat/stream below is what a voice or
    mobile front-end will actually want.
    """
    memories = await _memories_for(user, request.query)
    with trace_attributes(session_id=request.session_id, tags=["chat"], trace_name="chat"):
        result = await agent.ainvoke(_initial_state(request, memories), config=_run_config())
    citations = [
        Citation(book=v.book, chapter=v.chapter, verse=v.verse, translation=v.translation)
        for v in result.get("citations", [])
    ]
    if user:
        background.add_task(
            cave.record_turn,
            user,
            request.session_id,
            request.query,
            result["answer"],
            [c.model_dump() for c in citations],
            result.get("followups", []),
        )
    return ChatResponse(
        answer=result["answer"],
        citations=citations,
        intent=result.get("intent", request.mode),  # a prayer has no study intent
        followups=result.get("followups", []),
    )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest, user: AuthUser | None = Depends(optional_user)) -> EventSourceResponse:
    """Streams graph progress as SSE: a `stage` event per node (the web client
    uses this to light up its little strip of agents — see `stage-strip` in
    web/index.html), then `answer` and `citations` events. Same graph, same
    state — this is the shape a voice front-end (TTS as tokens arrive) or
    mobile client would consume instead of the plain /chat endpoint.
    """

    memories = await _memories_for(user, request.query)

    async def event_generator() -> AsyncIterator[dict]:
        retries = 0
        answer = ""
        citations: list[dict] = []
        followups: list[str] = []
        if memories:
            # Lets the client show a quiet "Aquila remembers" mark on this answer.
            yield {"event": "memory", "data": json.dumps({"count": len(memories)})}
        with trace_attributes(session_id=request.session_id, tags=["chat-stream"], trace_name="chat-stream"):
            async for step in agent.astream(
                _initial_state(request, memories),
                config=_run_config(),
                stream_mode="updates",
            ):
                for node_name, node_output in step.items():
                    if node_name == "ground_check":
                        # ground_check is the only node that writes retries, and
                        # retrieve's own node_output diff doesn't carry it forward
                        # (LangGraph only merges what a node returns) — so this is
                        # carried in the closure and stamped on every stage event
                        # from here on, letting the client tell a retry loop
                        # through retrieve/synthesize/ground_check apart from the
                        # first pass.
                        retries = node_output.get("retries", retries)
                    yield {"event": "stage", "data": json.dumps({"node": node_name, "retries": retries})}

                    if node_name == "synthesize":
                        answer = node_output["answer"]
                        yield {"event": "answer", "data": answer}
                    elif node_name == "pray_with":
                        # Praying for a request skips the study path (see graph.py)
                        # and carries its answer and the verses it quoted at once.
                        answer = node_output["answer"]
                        yield {"event": "answer", "data": answer}
                        citations = [
                            {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
                            for v in node_output["citations"]
                        ]
                        yield {"event": "citations", "data": json.dumps(citations)}
                    elif node_name == "answer_meta":
                        # Small-talk/identity questions skip synthesize/format_citations
                        # entirely (see graph.py) — this node carries both keys at once.
                        answer = node_output["answer"]
                        yield {"event": "answer", "data": answer}
                        yield {"event": "citations", "data": json.dumps([])}
                    elif node_name == "suggest_followups":
                        # Arrives after the answer and citations are already on
                        # screen, so the client appends rather than waits on it.
                        followups = node_output.get("followups", [])
                        yield {"event": "followups", "data": json.dumps(followups)}
                    elif node_name == "format_citations":
                        citations = [
                            {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation}
                            for v in node_output["citations"]
                        ]
                        yield {"event": "citations", "data": json.dumps(citations)}

        if user and answer:
            # Everything has been sent; saving and note-taking happen off the
            # request so the stream closes without waiting on them.
            task = asyncio.create_task(
                asyncio.to_thread(
                    cave.record_turn, user, request.session_id, request.query, answer, citations, followups
                )
            )
            _background.add(task)
            task.add_done_callback(_background.discard)

    return EventSourceResponse(event_generator())


@app.post("/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest, user: AuthUser | None = Depends(optional_user)) -> PlanResponse:
    """Builds a whole-Bible reading schedule and stores it, so the PDF route
    and any later reference to the same plan (a Cognigy xApp re-rendering it
    mid-conversation, a repeat visit) all read from the same row instead of
    regenerating it and risking drift.
    """
    translation = request.translation or settings.default_translation
    schedule = generate_schedule(request.start_date, request.days)
    overview = generate_overview(request.start_date, request.days, translation)
    row = {
        "start_date": request.start_date.isoformat(),
        "days": request.days,
        "translation": translation,
        "overview": overview,
        "schedule": [
            {"day": d.day, "date": d.date.isoformat(), "references": d.references}
            for d in schedule
        ],
    }
    if user:
        # Signed-in plans show up under My Cave. Before the migration adds
        # reading_plans.user_id this insert would fail, so the column is only
        # sent when there's a user to attach.
        row["user_id"] = user.id
    inserted = get_supabase().table("reading_plans").insert(row).execute().data[0]
    return PlanResponse(
        plan_id=inserted["id"],
        start_date=request.start_date,
        days=request.days,
        translation=translation,
        overview=overview,
        schedule=[PlanDay(**d) for d in row["schedule"]],
    )


def _get_plan_row(plan_id: str) -> dict:
    rows = get_supabase().table("reading_plans").select("*").eq("id", plan_id).limit(1).execute().data
    if not rows:
        raise HTTPException(status_code=404, detail="Plan not found")
    return rows[0]


@app.get("/plan/{plan_id}", response_model=PlanResponse)
async def get_plan(plan_id: str) -> PlanResponse:
    row = _get_plan_row(plan_id)
    return PlanResponse(
        plan_id=row["id"],
        start_date=row["start_date"],
        days=row["days"],
        translation=row["translation"],
        overview=row["overview"],
        schedule=[PlanDay(**d) for d in row["schedule"]],
    )


@app.get("/plan/{plan_id}/pdf")
async def plan_pdf(plan_id: str) -> Response:
    """Renders on demand rather than storing a file: the schedule row is the
    source of truth, the PDF is just one view of it. The same URL serves both
    the xApp's download button and the link a Cognigy send_email tool puts in
    the "email me this plan" message.
    """
    row = _get_plan_row(plan_id)
    pdf_bytes = render_plan_pdf(row)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="reading-plan-{plan_id}.pdf"'},
    )


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
