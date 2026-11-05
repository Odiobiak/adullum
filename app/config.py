"""Central app configuration, loaded once from environment variables / .env.

Every other module imports `settings` from here rather than reading `os.environ`
directly, so there is exactly one place that knows how config is sourced.
"""

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings reads .env into `settings` below WITHOUT touching
# os.environ — fine for every value this app reads through `settings`, but
# the Langfuse SDK reads its credentials (LANGFUSE_PUBLIC_KEY/SECRET_KEY/HOST)
# directly from os.environ itself (see app/observability.py), so those three
# must actually be loaded into the process environment. This must run before
# anything imports langfuse — app/config.py is imported first everywhere else,
# so doing it here guarantees the ordering.
load_dotenv()


class Settings(BaseSettings):
    """Typed, validated app config. Pydantic reads matching env vars (case-insensitive)
    or `.env` and raises at import time if a required field is missing — fail fast
    on misconfiguration rather than surfacing a confusing error deep in a request.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Service-role Supabase credentials — server-side only, see app/db.py.
    supabase_url: str
    supabase_service_key: str

    # LLM provider. Swapping providers means changing these three plus the
    # ChatOpenAI/OpenAI client construction in app/agent/nodes.py and app/retrieval.py.
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"
    # Requested from OpenAI through the `dimensions` parameter, which only the
    # text-embedding-3 models support. Must match the `halfvec(N)` columns in
    # supabase/schema.sql and the migrations.
    embedding_dim: int = 512
    chat_model: str = "gpt-4o-mini"

    default_translation: str = "BSB"
    # The one translation whose verses carry embeddings. Vector search runs
    # over it and returns the matching verses of whatever translation the
    # reader has open (see `match_verses` in supabase/schema.sql), so the other
    # translations need no embeddings of their own. Changing it means
    # re-ingesting the new one and the 'BSB' named in
    # supabase/migrations/20261108_compact_embeddings.sql.
    search_translation: str = "BSB"

    # Observability (optional). Left unset, get_langfuse_handler() in
    # app/observability.py returns None and the app runs with no tracing —
    # useful for local dev without a Langfuse account. Set all three to turn
    # tracing + eval scoring on.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # Comma-separated Host-header values the /mcp endpoint accepts (see
    # app/main.py) — the MCP SDK's SSE transport rejects any other Host as a
    # DNS-rebinding defense, which also blocks it by default from anywhere
    # other than 127.0.0.1. Add the deployed hostname (e.g. adullum.onrender.com)
    # via this env var once deployed; local dev works out of the box.
    mcp_allowed_hosts: str = "127.0.0.1:8000,localhost:8000"

    # Shows "Continue with Google" on the sign-in screen. Turn on only after
    # enabling the Google provider in Supabase (Auth > Providers), otherwise
    # the button leads to a Supabase error page.
    auth_google_enabled: bool = False


settings = Settings()
