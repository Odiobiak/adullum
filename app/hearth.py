"""The hearth: everything the signed-in home screen shows, in one request.

GET /me/home gathers the person's embers (a streak of days they came in),
where they left off, today's reading, their prayer list at a glance, how many
memory verses are due, a journal entry worth returning to, and a couple of
things Aquila remembers. Each part is fetched on its own and
degrades to null on failure, so a missing table (a migration not yet run)
blanks one card instead of the whole screen.

Days are the person's own local days: the browser sends `today`, because an
evening visit in California is already tomorrow in UTC, and a streak that
broke at 5pm would feel arbitrary.

GET /verse-of-the-day lives here too. It is public, picks from a short
hand-chosen list by date, and returns the text from the verses table, so the
verse on screen is always the real text of the translation being read.
"""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import AuthUser, require_user
from app.cave import _ensure_profile, revisit
from app.config import settings
from app.days import parse_today as _parse_today  # re-exported: reading_plans and tests read it from here
from app.db import get_supabase
from app.memorize import memorize_summary
from app.plan import plan_today  # re-exported: tests and callers read it from here
from app.prayers import prayer_summary
from app.retrieval import lookup_by_reference, parse_reference

log = logging.getLogger(__name__)

router = APIRouter()

DAY_LABELS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]

# Chosen for someone arriving tired: comfort, presence, rest, courage. Kept to
# three verses or fewer each so the card stays a single breath long.
VERSES_OF_THE_DAY = [
    "Matthew 11:28-29", "Lamentations 3:22-23", "Psalms 46:1", "Isaiah 41:10", "Psalms 34:18",
    "John 14:27", "Romans 8:38-39", "Philippians 4:6-7", "Psalms 23:1-3", "Isaiah 40:31",
    "2 Corinthians 12:9", "Joshua 1:9", "Psalms 121:1-2", "Proverbs 3:5-6", "Romans 15:13",
    "1 Peter 5:7", "Psalms 62:1-2", "Zephaniah 3:17", "Hebrews 4:16", "John 16:33",
    "Psalms 27:1", "Micah 6:8", "Isaiah 43:2", "Psalms 139:23-24", "Galatians 6:9",
    "Colossians 3:15", "1 John 4:18", "Psalms 91:1-2", "Romans 12:12", "Deuteronomy 31:8",
    "Psalms 4:8", "James 1:5", "Psalms 16:11", "Isaiah 26:3", "Matthew 6:34",
]


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_hearth.py)
# ---------------------------------------------------------------------------
def verse_of_the_day_ref(day: date) -> str:
    return VERSES_OF_THE_DAY[day.toordinal() % len(VERSES_OF_THE_DAY)]


def compute_embers(active_days: set[date], today: date) -> dict:
    """The last seven days ending today, and the current streak. A streak
    still counts when today isn't lit yet, so arriving in the morning never
    shows yesterday's streak as broken."""
    week = []
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        week.append({"day": d.isoformat(), "label": DAY_LABELS[d.weekday()], "lit": d in active_days, "today": offset == 0})
    cursor = today if today in active_days else today - timedelta(days=1)
    streak = 0
    while cursor in active_days:
        streak += 1
        cursor -= timedelta(days=1)
    return {"week": week, "streak": streak, "lit_today": today in active_days}


def _record_visit(user: AuthUser, day: date) -> None:
    try:
        get_supabase().table("user_activity").upsert(
            {"user_id": user.id, "day": day.isoformat()}, on_conflict="user_id,day", ignore_duplicates=True
        ).execute()
    except Exception:
        log.info("user_activity unavailable (run supabase/migrations/20261105_hearth.sql)")


def _part(name: str, fn):
    try:
        return fn()
    except Exception:
        log.warning("home: %s unavailable", name, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/me/home")
def home(today: str | None = Query(default=None), user: AuthUser = Depends(require_user)) -> dict:
    day = _parse_today(today)
    profile = _ensure_profile(user)
    _record_visit(user, day)
    db = get_supabase()

    def embers():
        since = (day - timedelta(days=60)).isoformat()
        rows = db.table("user_activity").select("day").eq("user_id", user.id).gte("day", since).execute().data
        return compute_embers({date.fromisoformat(r["day"]) for r in rows}, day)

    def last_session():
        rows = (
            db.table("chat_sessions").select("id, title, updated_at").eq("user_id", user.id)
            .order("updated_at", desc=True).limit(1).execute().data
        )
        if not rows:
            return None
        s = rows[0]
        last = (
            db.table("chat_messages").select("citations, followups").eq("session_id", s["id"])
            .eq("role", "assistant").order("id", desc=True).limit(1).execute().data
        )
        cites = (last[0].get("citations") or []) if last else []
        followups = (last[0].get("followups") or []) if last else []
        return {
            **s,
            "refs": [f"{c['book']} {c['chapter']}:{c['verse']}" for c in cites[:3]],
            "followup": followups[0] if followups else None,
        }

    def plan():
        rows = (
            db.table("reading_plans").select("*").eq("user_id", user.id)
            .order("created_at", desc=True).limit(1).execute().data
        )
        return plan_today(rows[0], day) if rows else None

    def prayers():
        rows = (
            db.table("prayers").select("id, body, passage_ref, status, answered_at, created_at")
            .eq("user_id", user.id).order("created_at", desc=True).limit(300).execute().data
        )
        return prayer_summary(rows, day)

    def memory_verses():
        rows = db.table("memory_verses").select("due, interval_days").eq("user_id", user.id).execute().data
        return memorize_summary(rows, day)

    def memories():
        rows = (
            db.table("user_memories").select("content").eq("user_id", user.id)
            .order("created_at", desc=True).limit(2).execute().data
        )
        return [r["content"] for r in rows]

    return {
        "profile": {"display_name": profile.get("display_name"), "memory_enabled": profile.get("memory_enabled", True)},
        "today": day.isoformat(),
        "embers": _part("embers", embers),
        "last_session": _part("last_session", last_session),
        "plan": _part("plan", plan),
        "prayers": _part("prayers", prayers),
        "memorize": _part("memorize", memory_verses),
        "revisit": (_part("revisit", lambda: revisit(user)) or {}).get("entry"),
        "memories": _part("memories", memories) or [],
    }


@router.get("/verse-of-the-day")
def verse_of_the_day(today: str | None = None, translation: str | None = None) -> dict:
    day = _parse_today(today)
    translation = translation or settings.default_translation
    ref = verse_of_the_day_ref(day)
    parsed = parse_reference(ref)
    verses = lookup_by_reference(parsed, translation) if parsed else []
    if not verses:
        raise HTTPException(status_code=404, detail="Today's verse isn't in this translation.")
    return {
        "ref": ref,
        "text": " ".join(v.text for v in verses),
        "translation": translation,
        "book": parsed.book,
        "chapter": parsed.chapter,
        "verse": parsed.verse_start,
    }

