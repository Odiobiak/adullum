"""Single shared Supabase client for the whole app.

There is deliberately one client and one place it's constructed: every table
query, RPC call, and the ingest script all go through `get_supabase()` so
credentials and connection setup live in exactly one spot.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Callable

from supabase import Client, create_client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    """Return the process-wide Supabase client, creating it on first call.

    Uses the service_role key, which bypasses row-level security — appropriate
    here because this client only ever runs inside the FastAPI server process,
    never in a browser or mobile client. If a future client (mobile app) talks
    to Supabase directly instead of through this API, it must use the public
    anon key + Supabase Auth instead, so the RLS policies in schema.sql apply.
    """
    return create_client(settings.supabase_url, settings.supabase_service_key)


def gather(*calls: Callable[[], Any]) -> list[Any]:
    """Run independent queries at the same time and return their results in
    order. If any fail, the earliest failed call's error is raised.

    Every query is an HTTP round trip to Supabase (often 100ms or more from
    the server), so a screen built from ten queries run one after another
    waits for all ten. Run together, it waits for the slowest. The shared
    client is safe to use across threads (httpx.Client is).

    Each call gets its own small pool, so a call may gather again inside
    itself without waiting on threads its caller is holding.
    """
    if len(calls) < 2:
        return [call() for call in calls]
    with ThreadPoolExecutor(max_workers=len(calls), thread_name_prefix="db") as pool:
        futures = [pool.submit(call) for call in calls]
        return [f.result() for f in futures]
