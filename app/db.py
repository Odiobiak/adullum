"""Single shared Supabase client for the whole app.

There is deliberately one client and one place it's constructed: every table
query, RPC call, and the ingest script all go through `get_supabase()` so
credentials and connection setup live in exactly one spot.
"""

from functools import lru_cache

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
