"""The prayer list: what a person is praying for, and when it was answered.

A prayer starts open. Marking it answered records the date and, if the
person wants, a line on how it was answered; it can be reopened. The days
someone prayed are kept too (`prayer_days`): for one request ("Prayed today"
on its card), or just "I prayed today". The Prayers tab shows them as this
week's seven days, counted, never as a streak. Fasting is app/fasting.py. When memory
is switched on, Aquila keeps one short note per prayer (rewritten when it is
answered or edited, deleted with it) so she can bring an open request up when
it is relevant. Like every memory, that note is about the person and is never
treated as Scripture.

Same rule as app/cave.py: the server's Supabase client bypasses RLS, so every
query here filters by the signed-in user's id itself. Never drop the
`.eq("user_id", user.id)`.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app import memory
from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.days import MARKABLE_DAYS, parse_markable_day, parse_today, week_marks
from app.db import get_supabase
from app.retrieval import parse_reference

router = APIRouter()

Status = Literal["open", "answered"]

_SETUP_HINT = (
    "The prayer list isn't set up on the database yet. Run "
    "supabase/migrations/20261109_prayers_highlights_memorize.sql in the Supabase SQL editor."
)

_FIELDS = "id, body, passage_ref, status, answer_note, answered_at, created_at, updated_at"

# How far back "answered recently" reaches on the home screen.
RECENT_ANSWERS_DAYS = 30


# The week of prayer reads a table added by a later migration than the list.
PRACTICE_HINT = (
    "Tracking prayer and fasting needs a database update. Run "
    "supabase/migrations/20261112_pebbles_and_prayer_practice.sql in the Supabase SQL editor."
)


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


def _practice_db(fn):
    return _db_call(fn, PRACTICE_HINT)


class PrayerIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    passage_ref: str | None = Field(default=None, max_length=120)


class PrayedIn(BaseModel):
    """Marks a day prayed, or takes it back. With `prayer_id` it's for that
    request; without, it's simply "I prayed today"."""

    today: str | None = None
    day: str | None = None  # today when left out, or one of the last seven
    prayer_id: uuid.UUID | None = None
    prayed: bool = True


class PrayerPatch(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    passage_ref: str | None = Field(default=None, max_length=120)
    status: Status | None = None
    answer_note: str | None = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_prayers.py)
# ---------------------------------------------------------------------------
def normalize_passage(text: str | None) -> str | None:
    """A linked passage in the canonical form the reader and retrieval both
    read back ("ps 23:1" -> "Psalms 23:1"), None when left blank, and a 422
    when it isn't a Bible reference at all, so a typo never becomes a dead link."""
    text = (text or "").strip()
    if not text:
        return None
    parsed = parse_reference(text)
    if not parsed:
        raise HTTPException(status_code=422, detail=f"{text!r} doesn't look like a Bible reference. Try something like Philippians 4:6.")
    ref = f"{parsed.book} {parsed.chapter}"
    if parsed.verse_start is not None:
        end = parsed.verse_end or parsed.verse_start
        ref += f":{parsed.verse_start}" if end == parsed.verse_start else f":{parsed.verse_start}-{end}"
    return ref


def prayer_memory_text(prayer: dict) -> str:
    """The note Aquila keeps about a prayer: what it is for and, once
    answered, that it was and how."""
    body = " ".join(prayer["body"].split())
    if len(body) > 240:
        body = body[:237] + "..."
    if prayer.get("status") != "answered":
        return f'They are praying about: "{body}"'
    note = " ".join((prayer.get("answer_note") or "").split())
    answered = f'They prayed about "{body}" and count it answered'
    return f'{answered}: "{note[:240]}"' if note else f"{answered}."


def _answered_on(row: dict) -> date | None:
    stamp = row.get("answered_at") if row["status"] == "answered" else None
    return datetime.fromisoformat(stamp).date() if stamp else None


def _of_the_day(rows: list[dict], today: date) -> dict | None:
    """One of `rows`, the same all day and the next one tomorrow."""
    return rows[today.toordinal() % len(rows)] if rows else None


def prayer_summary(rows: list[dict], today: date) -> dict:
    """What the home screen shows: how many are open, how many were answered
    in the last month, and one open request to name today, a different one
    each day so every request comes round. `rows` is the person's prayers,
    newest first."""
    since = today - timedelta(days=RECENT_ANSWERS_DAYS)
    open_rows = [r for r in rows if r["status"] == "open"]
    answered_recently = [r for r in rows if (_answered_on(r) or date.min) >= since]
    return {
        "open": len(open_rows),
        "answered_recently": len(answered_recently),
        "total": len(rows),
        "latest_open": open_rows[0] if open_rows else None,
        "for_today": _of_the_day(open_rows, today),
    }


# An answer comes back to the home screen only once it's this old, so it
# reads as remembering rather than an echo of last week.
REMEMBER_AFTER_DAYS = 14


def answered_to_remember(rows: list[dict], today: date) -> dict | None:
    """An answered prayer from a while back, for the home screen's look back
    (a stone of help, 1 Samuel 7:12). A different one each day."""
    cutoff = today - timedelta(days=REMEMBER_AFTER_DAYS)
    older = [r for r in rows if (_answered_on(r) or date.max) <= cutoff]
    pick = _of_the_day(older, today)
    return {k: pick.get(k) for k in ("id", "body", "answer_note", "answered_at")} if pick else None


def prayer_week(marks: list[dict], today: date) -> dict:
    """The Prayers tab's week of prayer from this person's `prayer_days` rows
    (each {day, prayer_id}): this week's seven days, lit for any prayer that
    day; how many days that is; whether they've said "I prayed today"; and,
    per request, whether it was prayed for today and on how many days this week."""
    week_start = today - timedelta(days=today.weekday())
    prayed_on = {date.fromisoformat(m["day"]) for m in marks}
    week = week_marks(prayed_on, today)
    by_prayer: dict[str, dict] = {}
    for m in marks:
        if not m.get("prayer_id"):
            continue
        d = date.fromisoformat(m["day"])
        entry = by_prayer.setdefault(m["prayer_id"], {"today": False, "this_week": 0})
        entry["today"] = entry["today"] or d == today
        if week_start <= d <= today:
            entry["this_week"] += 1
    return {
        "week": week,
        "days_this_week": sum(1 for w in week if w["done"]),
        "prayed_today": any(not m.get("prayer_id") and m["day"] == today.isoformat() for m in marks),
        "by_prayer": by_prayer,
    }


def _remember(user: AuthUser, prayer: dict) -> None:
    """Replace Aquila's note about this prayer with one that says what it
    says now. Skipped entirely when the person has memory switched off, and
    never fatal, like all note-taking."""
    try:
        get_supabase().table("user_memories").delete().eq("prayer_id", prayer["id"]).eq("user_id", user.id).execute()
    except Exception:
        return  # the prayers migration hasn't run; nothing to replace
    if memory.memory_enabled(user.id):
        memory.store_note(user.id, prayer_memory_text(prayer), kind="prayer", prayer_id=prayer["id"])


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/me/prayers")
def list_prayers(status: Status | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every prayer, or only the open or answered ones. Open ones newest
    first; answered ones by when they were answered."""

    def run():
        q = get_supabase().table("prayers").select(_FIELDS).eq("user_id", user.id)
        if status:
            q = q.eq("status", status)
        order = "answered_at" if status == "answered" else "created_at"
        return q.order(order, desc=True).limit(300).execute().data

    return _db(run)


@router.get("/me/prayers/week")
def week_of_prayer(today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """This week of prayer, for the top of the Prayers tab and each card."""
    day = parse_today(today)
    since = (day - timedelta(days=MARKABLE_DAYS - 1)).isoformat()
    marks = _practice_db(
        lambda: get_supabase().table("prayer_days").select("day, prayer_id")
        .eq("user_id", user.id).gte("day", since).execute().data
    )
    return prayer_week(marks, day)


@router.post("/me/prayers/log")
def log_prayer(body: PrayedIn, user: AuthUser = Depends(require_user)) -> dict:
    """Marks a day prayed (for a request, or in general), or takes it back."""
    today = parse_today(body.today)
    day = parse_markable_day(body.day, today).isoformat()
    db = get_supabase()
    prayer_id = str(body.prayer_id) if body.prayer_id else None
    if prayer_id:
        owned = _db(lambda: db.table("prayers").select("id").eq("id", prayer_id).eq("user_id", user.id).limit(1).execute().data)
        if not owned:
            raise HTTPException(status_code=404, detail="Prayer not found")
    if body.prayed:
        try:
            _practice_db(lambda: db.table("prayer_days").insert({"user_id": user.id, "day": day, "prayer_id": prayer_id}).execute())
        except APIError as err:
            if err.code != "23505":  # already marked: nothing to do
                raise
    else:
        q = db.table("prayer_days").delete().eq("user_id", user.id).eq("day", day)
        q = q.eq("prayer_id", prayer_id) if prayer_id else q.is_("prayer_id", "null")
        _practice_db(lambda: q.execute())
    return {"day": day, "prayer_id": prayer_id, "prayed": body.prayed}


@router.post("/me/prayers")
def create_prayer(body: PrayerIn, user: AuthUser = Depends(require_user)) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write a few words about what you're praying for.")
    row = {"user_id": user.id, "body": text, "passage_ref": normalize_passage(body.passage_ref)}
    prayer = _db(lambda: get_supabase().table("prayers").insert(row).execute().data[0])
    _remember(user, prayer)
    return prayer


@router.patch("/me/prayers/{prayer_id}")
def update_prayer(prayer_id: uuid.UUID, body: PrayerPatch, user: AuthUser = Depends(require_user)) -> dict:
    """Edit the words or passage, mark it answered (with an optional line on
    how), or reopen it."""
    sent = body.model_dump(exclude_unset=True)
    patch: dict = {"updated_at": _now()}
    if "body" in sent:
        text = (sent["body"] or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="A prayer needs some words in it.")
        patch["body"] = text
    if "passage_ref" in sent:
        patch["passage_ref"] = normalize_passage(sent["passage_ref"])
    if "answer_note" in sent:
        patch["answer_note"] = (sent["answer_note"] or "").strip() or None
    if sent.get("status") == "answered":
        patch["status"] = "answered"
        patch["answered_at"] = datetime.now(timezone.utc).isoformat()
    elif sent.get("status") == "open":
        patch.update(status="open", answered_at=None, answer_note=None)

    rows = _db(
        lambda: get_supabase().table("prayers").update(patch)
        .eq("id", str(prayer_id)).eq("user_id", user.id).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Prayer not found")
    prayer = rows[0]
    if {"body", "status", "answer_note"} & sent.keys():
        _remember(user, prayer)
    return prayer


@router.delete("/me/prayers/{prayer_id}")
def delete_prayer(prayer_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    # user_memories.prayer_id cascades, so Aquila's note goes with it.
    _db(lambda: get_supabase().table("prayers").delete().eq("id", str(prayer_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
