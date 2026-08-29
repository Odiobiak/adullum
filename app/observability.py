"""Langfuse wiring: one place that knows how to build a tracing handler and how
to attach a score to a trace. Everything here degrades to a no-op when Langfuse
isn't configured (see Settings.langfuse_*), so the app runs fine without an
account — and everything here is defensive about the network call failing,
because a broken trace upload must never break the chat request it's
describing.

Integration shape: get_langfuse_handler() returns a LangChain-compatible
CallbackHandler. Passed into `agent.ainvoke(state, config={"callbacks": [h]})`
in app/main.py, LangGraph's own execution model makes every node (classify_intent,
retrieve, synthesize, ground_check, format_citations) show up as a span
automatically, since each node is itself a Runnable — no per-node instrumentation
needed. The one thing that DOES need explicit wiring is the LLM calls *inside*
synthesize/classify_intent/ground_check, which is why those node functions accept
and forward `config` (see app/agent/nodes.py) rather than relying on it propagating
implicitly.
"""

import logging
from functools import lru_cache

from langchain_core.runnables import RunnableConfig

from app.config import settings

logger = logging.getLogger(__name__)

try:
    from langfuse.langchain import CallbackHandler  # Langfuse Python SDK v3+
except ImportError:  # pragma: no cover
    from langfuse.callback import CallbackHandler  # Langfuse Python SDK v2.x

from langfuse import Langfuse

LANGFUSE_ENABLED = bool(settings.langfuse_public_key and settings.langfuse_secret_key)


@lru_cache
def get_langfuse_client() -> "Langfuse | None":
    """The low-level client, used for scoring and (in scripts/evaluate.py)
    dataset access — separate from the LangChain callback handler below, which
    only knows how to emit traces, not read/score them.
    """
    if not LANGFUSE_ENABLED:
        return None
    return Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )


def get_langfuse_handler(
    session_id: str | None = None, tags: list[str] | None = None
) -> "CallbackHandler | None":
    """Build a per-request tracing handler, or None if Langfuse isn't configured.
    Callers should filter None out of their callbacks list rather than pass it
    through — LangChain doesn't accept a bare None as a callback.
    """
    if not LANGFUSE_ENABLED:
        return None
    try:
        return CallbackHandler(session_id=session_id, tags=tags)
    except Exception:
        # Tracing must never take the chat request down with it.
        logger.warning("Failed to construct Langfuse handler; continuing untraced.", exc_info=True)
        return None


def _find_handler(config: RunnableConfig) -> "CallbackHandler | None":
    """Recover the Langfuse handler from a node's RunnableConfig. LangChain may
    have normalized config["callbacks"] into a CallbackManager (with a
    `.handlers` list) rather than leaving it as the raw list we passed in, so
    this checks both shapes.
    """
    raw = config.get("callbacks") if config else None
    handlers = getattr(raw, "handlers", raw) or []
    for handler in handlers:
        if isinstance(handler, CallbackHandler):
            return handler
    return None


def score_trace_from_config(config: RunnableConfig, name: str, value: float, comment: str | None = None) -> None:
    """Attach a score (e.g. ground_check's verdict) to the trace a node is
    running under. No-ops silently if Langfuse isn't configured or no trace_id
    is available yet — called from inside a node function, so it must never
    raise into the graph run.
    """
    client = get_langfuse_client()
    if client is None:
        return
    handler = _find_handler(config)
    trace_id = handler.get_trace_id() if handler else None
    if not trace_id:
        return
    try:
        client.score(trace_id=trace_id, name=name, value=value, comment=comment)
    except Exception:
        logger.warning("Failed to write Langfuse score %r; continuing.", name, exc_info=True)
