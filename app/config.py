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

    # Comma-separated email addresses that can open the admin desk (#desk),
    # where posts to Refuge's Amens wall that the automatic check wasn't sure
    # of wait for a person, and reported posts come back for a second look.
    admin_emails: str = ""

    # Whether an Amens post the automatic check is clear about goes on the
    # wall straight away (app/one_another.py::goes_up_now). Set false to send
    # every post to the admin desk first, as Amens did at the start.
    amens_auto_approve: bool = True

    # Giving, shown on the Support page (#support) and everywhere that links to
    # it. Both are Stripe Payment Links (or any checkout page). Left empty, the
    # page still explains why Adullum asks, and says giving opens soon, so the
    # buttons never lead nowhere. See app/support.py.
    support_once_url: str = ""
    support_monthly_url: str = ""
    # What the monthly link charges, as the page should say it ("$3"). Stripe
    # holds the real price; keep this in step with it.
    support_monthly_amount: str = "$3"

    # Push notifications (app/push.py): reminders and "your church is live".
    # Make the key pair once with `python scripts/make_vapid_keys.py`. Left
    # empty, the bell still offers "Add to my calendar" and says notifications
    # aren't set up here, and nothing is ever sent.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    # Who push services contact about this sender: "mailto:you@example.com".
    vapid_subject: str = "mailto:hello@adullum.app"
    # Shared with the scheduled GitHub workflow that wakes the server to send
    # due reminders (POST /internal/send-reminders). Left empty, that endpoint
    # refuses every call, and reminders go out only while the server is awake.
    cron_secret: str = ""

    # Daily limits on what costs money (app/quota.py). Adullum is free and
    # paid for by people who give, so every answer is counted: per person (a
    # guest by their network address) and against one budget for the whole
    # app. A day is a UTC day. Raise any of these from .env, no deploy needed.
    quota_questions_signed_in: int = 25  # Aquila, Pray with, Declare, plan builder
    quota_questions_guest: int = 5
    quota_talks: int = 60  # Refuge talk messages
    quota_voice_calls: int = 2
    voice_call_minutes: int = 10  # the page hangs up a call at this length
    quota_per_minute_signed_in: int = 6
    quota_per_minute_guest: int = 3
    # Rough cost of one of each, in US dollars, counted against the budget.
    # Voice stays 0 until Cognigy's per-minute price is known.
    daily_budget_usd: float = 3.0  # 0 turns the budget off
    cost_question_usd: float = 0.003
    cost_talk_usd: float = 0.002
    cost_voice_call_usd: float = 0.0

    # Shared with Cognigy so only it can open the MCP server (/mcp/sse), sent
    # as "Authorization: Bearer <secret>" or "?key=<secret>". Left empty, the
    # server stays open as before.
    mcp_secret: str = ""


settings = Settings()
