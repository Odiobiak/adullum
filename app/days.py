"""The person's own local day.

Streaks, reading plans and memory-verse reviews all count in the browser's
local days, because an evening visit in California is already tomorrow in
UTC and a day that ended at 5pm would feel arbitrary. The browser sends its
date as `today`; this module is the one place that decides whether to trust it.
"""

from datetime import date

from fastapi import HTTPException


def parse_today(today: str | None) -> date:
    """The browser's local date, accepted only when it is within a day of the
    server's, since no timezone is further apart than that."""
    server = date.today()
    if not today:
        return server
    try:
        d = date.fromisoformat(today)
    except ValueError:
        raise HTTPException(status_code=422, detail="today must be YYYY-MM-DD")
    return d if abs((d - server).days) <= 1 else server
