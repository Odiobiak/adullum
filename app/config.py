"""Central app configuration, loaded once from environment variables / .env.

Every other module imports `settings` from here rather than reading `os.environ`
directly, so there is exactly one place that knows how config is sourced.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    embedding_dim: int = 1536  # must match the `vector(N)` dimension in supabase/schema.sql
    chat_model: str = "gpt-4o-mini"

    default_translation: str = "BSB"

    # Observability (optional). Left unset, get_langfuse_handler() in
    # app/observability.py returns None and the app runs with no tracing —
    # useful for local dev without a Langfuse account. Set all three to turn
    # tracing + eval scoring on.
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"


settings = Settings()
