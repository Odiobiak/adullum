"""Verses a person is learning by heart, and when to practise each one.

A verse is added from the reader or the verse of the day. Its words are read
from the verses table here, never sent by the browser, so what someone learns
is always the real text of the translation they chose.

Practice is simple spaced repetition. After each review the person says how
it went ("again", "hard" or "good") and `next_review` picks the next date: a
verse recalled well comes back after longer and longer gaps (1 day, 3 days,
then the last gap times its ease), one that slipped comes back tomorrow. A
verse whose gap has reached `LEARNED_DAYS` counts as learned. It is the core of
the SM-2 algorithm, cut down to three answers so practice stays gentle.

Same rule as app/cave.py: every query filters by the signed-in user's id.
"""

import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_user
from app.cave import _db_call
from app.config import settings
from app.days import parse_today
from app.db import get_supabase
from app.notes import note_ref
from app.retrieval import lookup_by_reference, parse_reference

router = APIRouter()

Grade = Literal["again", "hard", "good"]

_SETUP_HINT = (
    "Memory verses aren't set up on the database yet. Run "
    "supabase/migrations/20261109_prayers_highlights_memorize.sql in the Supabase SQL editor."
)

_FIELDS = (
    "id, book, chapter, verse_start, verse_end, translation, verse_text, "
    "reps, interval_days, ease, due, last_reviewed, created_at"
)

# A passage longer than this is a chapter study, not something to recite.
MAX_VERSES = 6
LEARNED_DAYS = 21
MAX_INTERVAL_DAYS = 180
MIN_EASE = 1.3


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


class MemoryVerseIn(BaseModel):
    ref: str = Field(min_length=3, max_length=60)
    translation: str | None = Field(default=None, max_length=12)
    today: str | None = None


class ReviewIn(BaseModel):
    grade: Grade
    today: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_memorize.py)
# ---------------------------------------------------------------------------
def next_review(card: dict, grade: Grade, today: date) -> dict:
    """The schedule after one review: the new streak (`reps`), gap in days,
    ease, and the date it is next due.

    - again: it slipped. Start over, back tomorrow, and a little less ease
      so its gaps grow more slowly from now on.
    - hard: recalled with effort. A slightly longer gap than last time.
    - good: recalled. 1 day, then 3, then the last gap times the ease.
    """
    reps, interval, ease = card["reps"], card["interval_days"], card["ease"]
    if grade == "again":
        reps, interval, ease = 0, 1, ease - 0.2
    elif grade == "hard":
        reps, interval, ease = reps + 1, max(1, round(interval * 1.2)), ease - 0.15
    else:
        interval = 1 if reps == 0 else 3 if reps == 1 else round(interval * ease)
        reps += 1
    interval = min(max(interval, 1), MAX_INTERVAL_DAYS)
    ease = round(max(ease, MIN_EASE), 2)
    return {
        "reps": reps,
        "interval_days": interval,
        "ease": ease,
        "due": (today + timedelta(days=interval)).isoformat(),
        "last_reviewed": today.isoformat(),
    }


def card_status(card: dict, today: date) -> str:
    """'due' when it should be practised today, otherwise 'learned' once its
    gap has grown past LEARNED_DAYS, otherwise 'learning'."""
    if date.fromisoformat(card["due"]) <= today:
        return "due"
    return "learned" if card["interval_days"] >= LEARNED_DAYS else "learning"


def memorize_summary(rows: list[dict], today: date) -> dict:
    """Counts for the home screen and the top of the Memorize tab."""
    statuses = [card_status(r, today) for r in rows]
    return {"total": len(rows), "due": statuses.count("due"), "learned": statuses.count("learned")}


def _present(card: dict, today: date) -> dict:
    return {**card, "ref": note_ref(card), "status": card_status(card, today)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/me/memorize")
def list_verses(today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """Every verse being learned, the ones due first, plus the counts."""
    day = parse_today(today)
    rows = _db(
        lambda: get_supabase().table("memory_verses").select(_FIELDS).eq("user_id", user.id)
        .order("due").order("created_at").limit(500).execute().data
    )
    return {"verses": [_present(r, day) for r in rows], **memorize_summary(rows, day)}


@router.post("/me/memorize")
def add_verse(body: MemoryVerseIn, user: AuthUser = Depends(require_user)) -> dict:
    """Start learning a passage. Adding one that is already being learned
    returns it as it is rather than resetting its progress."""
    day = parse_today(body.today)
    parsed = parse_reference(body.ref)
    if not parsed:
        raise HTTPException(status_code=422, detail=f"{body.ref!r} doesn't look like a Bible reference.")
    if parsed.verse_start is None:
        raise HTTPException(status_code=422, detail="Pick the verses to learn, like John 3:16, rather than a whole chapter.")
    if parsed.verse_end - parsed.verse_start + 1 > MAX_VERSES:
        raise HTTPException(status_code=422, detail=f"Learn up to {MAX_VERSES} verses at a time. Try a shorter passage.")
    translation = (body.translation or settings.default_translation).upper()
    verses = lookup_by_reference(parsed, translation)
    if not verses:
        raise HTTPException(status_code=404, detail=f"{body.ref} isn't in the {translation} here.")

    row = {
        "user_id": user.id,
        "book": parsed.book,
        "chapter": parsed.chapter,
        "verse_start": parsed.verse_start,
        "verse_end": parsed.verse_end,
        "translation": translation,
        "verse_text": " ".join(v.text for v in verses),
        "due": day.isoformat(),
    }
    db = get_supabase()
    try:
        card = _db(lambda: db.table("memory_verses").insert(row).execute().data[0])
        return {**_present(card, day), "already": False}
    except APIError as err:
        if err.code != "23505":  # unique violation: already learning this one
            raise
    existing = (
        db.table("memory_verses").select(_FIELDS).eq("user_id", user.id).eq("book", parsed.book)
        .eq("chapter", parsed.chapter).eq("verse_start", parsed.verse_start).eq("verse_end", parsed.verse_end)
        .limit(1).execute().data
    )
    return {**_present(existing[0], day), "already": True}


@router.post("/me/memorize/{verse_id}/review")
def review(verse_id: uuid.UUID, body: ReviewIn, user: AuthUser = Depends(require_user)) -> dict:
    day = parse_today(body.today)
    db = get_supabase()
    rows = _db(
        lambda: db.table("memory_verses").select(_FIELDS).eq("id", str(verse_id)).eq("user_id", user.id)
        .limit(1).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Verse not found")
    schedule = next_review(rows[0], body.grade, day)
    updated = _db(
        lambda: db.table("memory_verses").update(schedule).eq("id", str(verse_id)).eq("user_id", user.id)
        .execute().data
    )
    return _present(updated[0], day)


@router.delete("/me/memorize/{verse_id}")
def remove_verse(verse_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("memory_verses").delete().eq("id", str(verse_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
