"""The person's own local day.

Streaks, reading plans and memory-verse reviews all count in the browser's
local days, because an evening visit in California is already tomorrow in
UTC and a day that ended at 5pm would feel arbitrary. The browser sends its
date as `today`; this module is the one place that decides whether to trust it.
"""

from datetime import date, timedelta

from fastapi import HTTPException

# One letter per weekday, Monday first, matching date.weekday().
WEEKDAY_LETTERS = ("M", "T", "W", "T", "F", "S", "S")

# How far back a day can be marked done (a habit, a day of prayer): this week
# so far, or the last seven days on a Monday. Never a day still to come.
MARKABLE_DAYS = 7


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


def this_week(today: date) -> list[date]:
    """The seven days of today's week, Monday first."""
    monday = today - timedelta(days=today.weekday())
    return [monday + timedelta(days=n) for n in range(7)]


def week_marks(done: set[date], today: date) -> list[dict]:
    """This week as seven marks for the page to draw as dots: which days were
    done, which one is today, and which are still to come. Shown as a week, and
    counted as "3 of 5 this week", never as a streak."""
    return [
        {
            "day": d.isoformat(),
            "label": WEEKDAY_LETTERS[d.weekday()],
            "done": d in done,
            "today": d == today,
            "future": d > today,
        }
        for d in this_week(today)
    ]


def parse_markable_day(day: str | None, today: date) -> date:
    """The day someone is marking done or undone: today when not given, else a
    day within the last MARKABLE_DAYS. A later day, or one long gone, is a 422."""
    if not day:
        return today
    try:
        d = date.fromisoformat(day)
    except ValueError:
        raise HTTPException(status_code=422, detail="day must be YYYY-MM-DD")
    if d > today or (today - d).days >= MARKABLE_DAYS:
        raise HTTPException(status_code=422, detail="Only the last week can be marked.")
    return d
