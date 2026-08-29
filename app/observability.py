"""Langfuse wiring: one place that knows how to build a tracing handler, attach
trace-level attributes, and score a trace. Everything here degrades to a no-op
when Langfuse isn't configured (see Settings.langfuse_*), so the app runs fine
without an account — and everything here is defensive about the network call
failing, because a broken trace upload must never break the chat request it's
describing.

Integration shape (Langfuse Python SDK v4): get_langfuse_handler() returns a
LangChain-compatible CallbackHandler, passed into `agent.ainvoke(state,
config={"callbacks": [h]})` in app/main.py. LangGraph's own execution model
makes every node (classify_intent, retrieve, synthesize, ground_check,
format_citations) show up as a span automatically, since each node is itself a
Runnable — no per-node instrumentation needed. The one thing that DOES need
explicit wiring is the LLM calls *inside* synthesize/classify_intent/
ground_check, which is why those node functions accept and forward `config`
(see app/agent/nodes.py) rather than relying on it propagating implicitly.

Trace-level attributes (session_id, tags, trace_name) are NOT constructor args
on CallbackHandler in v4 — they're applied via `trace_attributes()` below,
which wraps the whole request (see app/main.py) in a `propagate_attributes()`
context so every observation created inside inherits them.

IMPORTANT: get_langfuse_handler() must build a FRESH handler per request, never
a shared/cached one. v4's CallbackHandler exposes the trace it created via the
plain instance attribute `last_trace_id` (see score_trace_from_config below) —
sharing one handler across concurrent requests would make that attribute a
race condition, one request's trace id clobbering another's. Confirmed the
hard way: an earlier version of this file cached the handler with @lru_cache
and also tried scoring via Langfuse's ambient "current trace" context
(get_client().score_current_trace()) from inside ground_check() — that failed
in production with "Context error: No active span in current context",
because LangGraph runs sync node functions like ground_check() on a worker
thread that doesn't inherit the main coroutine's contextvars. Pulling the
trace id explicitly off the request's own handler instance sidesteps that
entirely: it's a plain attribute read on an object already threaded through
`config["callbacks"]`, not dependent on which thread reads it.

KNOWN GAP: the root trace's input/output is whatever the LangGraph state
dict looks like going in and out (the full retrieved-verses array included),
not a clean {"answer": ..., "citations": [...]} summary — best practice
wants the latter for readability in the Traces table. Fixing this needs
`get_client().set_current_trace_io()`, but that also relies on ambient
"current trace" context, and the root span the CallbackHandler creates has
already closed by the time `agent.ainvoke()`/`astream()` returns control to
our code — confirmed empirically, there's nothing "current" left to update
at that point, and the SDK has no explicit-by-trace_id equivalent to
`create_score(trace_id=...)` for this. The real fix is wrapping the graph
call in our own manually-created root span (`get_client().
start_as_current_observation(name=..., as_type="chain")`) so the
CallbackHandler's spans nest as children of one we hold a live reference to
and can `.update(output=...)` on directly — deferred as a separate, riskier
change rather than rushed in here.
"""

import logging
from contextlib import AbstractContextManager, nullcontext

from langchain_core.runnables import RunnableConfig
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

from app.config import settings

logger = logging.getLogger(__name__)

LANGFUSE_ENABLED = bool(settings.langfuse_public_key and settings.langfuse_secret_key)


def get_langfuse_handler() -> CallbackHandler | None:
    """A fresh LangChain callback handler for one request, or None if Langfuse
    isn't configured. Must NOT be cached/shared across requests — see the
    module docstring. Callers should filter None out of their callbacks list
    rather than pass it through — LangChain doesn't accept a bare None as a
    callback.
    """
    if not LANGFUSE_ENABLED:
        return None
    try:
        return CallbackHandler()
    except Exception:
        # Tracing must never take the chat request down with it.
        logger.warning("Failed to construct Langfuse handler; continuing untraced.", exc_info=True)
        return None


def trace_attributes(
    *, session_id: str | None = None, tags: list[str] | None = None, trace_name: str | None = None
) -> AbstractContextManager:
    """Context manager applying session_id/tags/trace_name to every observation
    created inside it — wrap the actual graph invocation with this (see
    app/main.py and app/mcp_server.py). A no-op contextlib.nullcontext() when
    Langfuse isn't configured, so callers don't need their own `if` branch.
    """
    if not LANGFUSE_ENABLED:
        return nullcontext()
    return propagate_attributes(session_id=session_id, tags=tags, trace_name=trace_name)


def _find_handler(config: RunnableConfig) -> CallbackHandler | None:
    """Recover this request's Langfuse handler from a node's RunnableConfig.
    LangChain may have normalized config["callbacks"] into a CallbackManager
    (with a `.handlers` list) rather than leaving it as the raw list passed
    in, so this checks both shapes.
    """
    raw = config.get("callbacks") if config else None
    handlers = getattr(raw, "handlers", raw) or []
    for handler in handlers:
        if isinstance(handler, CallbackHandler):
            return handler
    return None


def score_trace_from_config(config: RunnableConfig, name: str, value: float, comment: str | None = None) -> None:
    """Attach a score (e.g. ground_check's verdict) to this request's trace.
    No-ops silently if Langfuse isn't configured or no trace id is available
    yet — called from inside a node function, so it must never raise into the
    graph run.
    """
    if not LANGFUSE_ENABLED:
        return
    handler = _find_handler(config)
    trace_id = getattr(handler, "last_trace_id", None) if handler else None
    if not trace_id:
        return
    try:
        get_client().create_score(trace_id=trace_id, name=name, value=value, comment=comment)
    except Exception:
        logger.warning("Failed to write Langfuse score %r; continuing.", name, exc_info=True)
