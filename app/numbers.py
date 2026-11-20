"""The Numbers tab on the admin desk (#desk, web/numbers.js): how many people
use Adullam, what they use, and how the server itself is holding up.

Counts only. `admin_numbers` (supabase/migrations/20261128_admin_numbers.sql)
returns totals and never a person or anything anyone wrote, so the desk sees
how much each part is used, never by whom. The server's memory is read here,
from the process itself, so it shows even before that migration runs.
"""

import threading
import time

from fastapi import APIRouter, Depends, Query
from postgrest.exceptions import APIError

from app.auth import AuthUser, require_admin
from app.days import parse_today
from app.db import get_supabase

router = APIRouter()

NUMBERS_HINT = (
    "Numbers need a database update. Run supabase/migrations/20261128_admin_numbers.sql "
    "in the Supabase SQL editor."
)
MISSING = ("42P01", "PGRST202", "42883")  # the function isn't there yet
STARTED = time.time()


def _read_kb(path: str, field: str | None = None) -> int | None:
    """A number from a /proc or cgroup file, in KB, or None where there's none
    (anywhere but Linux, or a container that doesn't say)."""
    try:
        with open(path) as f:
            for line in f:
                if field is None:
                    value = line.strip()
                    return None if value == "max" else int(value) // 1024
                if line.startswith(field):
                    return int(line.split()[1])
    except (OSError, ValueError):
        return None
    return None


def _mb(kb: int | None) -> int | None:
    return round(kb / 1024) if kb else None


def server_health() -> dict:
    """What this process holds in memory now, against the instance's limit.
    Render restarts a service that passes its limit, so a number creeping up
    hour after hour with nobody about is a leak, not traffic."""
    rss = _read_kb("/proc/self/status", "VmRSS:")
    limit = _read_kb("/sys/fs/cgroup/memory.max") or _read_kb("/sys/fs/cgroup/memory/memory.limit_in_bytes")
    return {
        "memory_mb": _mb(rss),
        # A cgroup with no limit reports a huge number; that isn't a limit worth showing.
        "limit_mb": _mb(limit) if limit and limit < 64 * 1024 * 1024 else None,
        "threads": threading.active_count(),
        "up_hours": round((time.time() - STARTED) / 3600, 1),
    }


@router.get("/admin/numbers")
def numbers(today: str | None = Query(default=None), admin: AuthUser = Depends(require_admin)) -> dict:
    day = parse_today(today)
    try:
        counts = get_supabase().rpc("admin_numbers", {"p_today": day.isoformat()}).execute().data
        setup = None
    except APIError as err:
        if err.code not in MISSING:
            raise
        counts, setup = None, NUMBERS_HINT
    return {"today": day.isoformat(), "counts": counts, "setup": setup, "server": server_health()}
