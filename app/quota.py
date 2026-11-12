"""Daily limits on what costs money: Aquila's answers, Refuge talks and voice calls.

Adullum is free and paid for by people who give, so this keeps one person,
or one script, from spending what everyone shares. Three checks, cheapest
first:
- a burst limit per minute, held in this process (it only has to stop a
  flood, so losing it on a restart is fine);
- a count per person per UTC day, and
- an estimated spend for the whole app per day,
the last two in one database call (`use_quota`, supabase/migrations/
20261121_usage_limits.sql), so a refused request is never counted.

A guest is counted by a scrambled network address, never the address itself.
If the database can't be reached, or the migration hasn't run, the request
goes through: the provider's own monthly limit is the backstop, and a person
should never lose Aquila to a counting error.
"""

import hashlib
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

from fastapi import HTTPException, Request

from app.auth import AuthUser
from app.config import settings
from app.db import get_supabase

log = logging.getLogger(__name__)

Kind = Literal["question", "talk", "voice"]

# What a person reads when they reach a limit, said gently: nothing is wrong.
LIMIT_MESSAGES: dict[str, str] = {
    "question": "You've asked Aquila a lot today. She'll be ready for more tomorrow.",
    "question_guest": "That's today's questions as a guest. Sign in to keep going, it's free.",
    "talk": "That's a lot of talking for one day. Aquila will be here again tomorrow, and Write it out is always open.",
    "voice": "That's today's calls. You can keep talking with Aquila by typing, and calling opens again tomorrow.",
    "budget": "Aquila is resting for the rest of today. Adullum is free, kept going by people who give, and today's share has been used. Please come back tomorrow.",
    "burst": "That's a lot at once. Give it a moment and try again.",
}


@dataclass(frozen=True)
class Rule:
    signed_in: int
    guest: int
    cost_usd: float


def rules() -> dict[str, Rule]:
    """Read from settings each time, so a test or a changed .env applies at once."""
    return {
        "question": Rule(settings.quota_questions_signed_in, settings.quota_questions_guest, settings.cost_question_usd),
        "talk": Rule(settings.quota_talks, 0, settings.cost_talk_usd),
        "voice": Rule(settings.quota_voice_calls, 0, settings.cost_voice_call_usd),
    }


def mills(usd: float) -> int:
    """Dollars as tenths of a cent, the unit the database counts spend in."""
    return round(usd * 1000)


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# Who is asking
# ---------------------------------------------------------------------------
def client_ip(request: Request) -> str:
    """The caller's address. Behind Render's edge the real one is in
    True-Client-IP or CF-Connecting-IP, which the edge sets itself; the first
    X-Forwarded-For entry is whatever the caller typed, so it isn't trusted."""
    for header in ("true-client-ip", "cf-connecting-ip"):
        if value := request.headers.get(header):
            return value.strip()
    return request.client.host if request.client else "unknown"


def subject_of(user: AuthUser | None, request: Request | None) -> str:
    """A signed-in person's id, or a guest's scrambled address."""
    if user:
        return user.id
    ip = client_ip(request) if request else "unknown"
    return "guest:" + hashlib.sha256(ip.encode()).hexdigest()[:20]


def is_guest(subject: str) -> bool:
    return subject.startswith("guest:")


# ---------------------------------------------------------------------------
# Burst limit
# ---------------------------------------------------------------------------
_recent: dict[str, deque[float]] = defaultdict(deque)
_recent_lock = Lock()


def check_burst(subject: str, now: float | None = None) -> None:
    """Refuses more than a handful of requests a minute from one subject."""
    allowed = settings.quota_per_minute_guest if is_guest(subject) else settings.quota_per_minute_signed_in
    if allowed <= 0:
        return
    now = time.monotonic() if now is None else now
    with _recent_lock:
        stamps = _recent[subject]
        while stamps and now - stamps[0] >= 60:
            stamps.popleft()
        if len(stamps) >= allowed:
            raise HTTPException(status_code=429, detail=LIMIT_MESSAGES["burst"])
        stamps.append(now)
        if len(_recent) > 10_000:  # forget quiet subjects so this never grows without end
            for key in [k for k, v in _recent.items() if not v]:
                del _recent[key]


# ---------------------------------------------------------------------------
# Daily count and budget
# ---------------------------------------------------------------------------
def _record(subject: str, kind: str, limit: int, cost: int, budget: int) -> str:
    """One call to use_quota. 'ok' when the database can't say otherwise."""
    try:
        params = {"p_subject": subject, "p_kind": kind, "p_day": today(), "p_limit": limit, "p_cost": cost, "p_budget": budget}
        return get_supabase().rpc("use_quota", params).execute().data or "ok"
    except Exception:
        log.warning("usage limits skipped (is 20261121_usage_limits.sql run?)", exc_info=True)
        return "ok"


def spend(kind: Kind, subject: str) -> None:
    """Counts one `kind` for `subject`, or raises a 429 with a gentle message.
    Blocking (one database call); async routes run it with asyncio.to_thread."""
    check_burst(subject)
    rule = rules()[kind]
    guest = is_guest(subject)
    limit = rule.guest if guest else rule.signed_in
    if guest and limit <= 0:
        # Talks and calls need an account, so a guest never reaches them;
        # refused here too in case a route forgets.
        raise HTTPException(status_code=429, detail=LIMIT_MESSAGES["question_guest"])
    outcome = _record(subject, kind, limit, mills(rule.cost_usd), mills(settings.daily_budget_usd))
    if outcome == "budget":
        raise HTTPException(status_code=429, detail=LIMIT_MESSAGES["budget"])
    if outcome == "limit":
        key = "question_guest" if kind == "question" and guest else kind
        raise HTTPException(status_code=429, detail=LIMIT_MESSAGES[key])


def spend_shared(kind: Kind, subject: str) -> bool:
    """Counts against the day's budget only, for callers with no person to
    count (a voice call's questions arrive from Cognigy). False once the
    budget is spent."""
    outcome = _record(subject, kind, 0, mills(rules()[kind].cost_usd), mills(settings.daily_budget_usd))
    return outcome != "budget"


def used_today(kind: Kind, subject: str) -> int:
    """How many `kind` the subject has had today (0 when it can't be read)."""
    try:
        rows = (
            get_supabase().table("usage_days").select("count")
            .eq("subject", subject).eq("kind", kind).eq("day", today()).limit(1).execute().data
        )
        return int(rows[0]["count"]) if rows else 0
    except Exception:
        return 0
