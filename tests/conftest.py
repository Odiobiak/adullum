"""Dummy credentials so `app.config.settings` (required, no defaults for
Supabase/OpenAI) constructs successfully in CI and on any machine without a
real .env. `setdefault` leaves a developer's actual .env-backed environment
untouched, since app/config.py's own load_dotenv() runs first via the app
import below and only fills in what os.environ doesn't already have.

Must run before any `app.*` module is imported — conftest.py is collected
before test modules, so this ordering is automatic.
"""

import os

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-service-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import pytest


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch):
    """Every test starts under its limits, with nothing cached, and never
    counts against a real database (app/quota.py, app/answer_cache.py)."""
    from app import answer_cache, quota

    monkeypatch.setattr(quota, "_record", lambda *args, **kwargs: "ok")
    quota._recent.clear()
    answer_cache.clear()
    yield
