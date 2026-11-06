"""Reflections: a guided time with God over a stretch of time.

A reflection looks back over a month, a quarter, a year or a season the person
names, and ahead to the stretch after it. It has three stages:
- Look back: the numbers they choose to count (some counted from their cave,
  some their own), their goals, each area of life with how it went, and where
  they saw God.
- Lay down: gratitude, what to set down, forgiveness.
- Look ahead: a word and a verse, numbers to aim for, and for each area of
  life where they'd like it to be and what they'd like to see happen there.

Kept, a reflection's look ahead is the plan for the stretch ahead. It's pinned
in the journal while that stretch runs, a goal can be tracked in Pebbles
(refuge_seeds), and the halfway check-in on the home screen shows how it's
going. The next reflection opens with "What you set out": that plan beside
what actually happened.

The page saves as the person writes (`PUT`), so a reflection can be done over
a few evenings; it's a draft until they keep it. Everything here is private to
the person and nothing feeds Aquila's memory. Every query filters by the
signed-in user's id in code, the same rule as app/cave.py. A verse is stored as
a reference only; its text is always read from the verses table.
"""

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.days import parse_today
from app.db import get_supabase
from app.prayers import normalize_passage
from app.refuge import _pebbles_db, goal_measure

log = logging.getLogger(__name__)

router = APIRouter()

Span = Literal["month", "quarter", "year", "season"]
Rating = Literal["hard", "mixed", "steady", "thriving"]
GoalKind = Literal["habit", "number", "date", "hope"]
GoalStatus = Literal["reached", "on_the_way", "not_this_time"]

# What Adullum can count for a stretch of time, read from the person's cave.
CaveCount = Literal["entries", "answered", "sermons", "verses", "plans", "days"]
CAVE_COUNTS: dict[str, str] = {
    "entries": "journal entries",
    "answered": "prayers answered",
    "sermons": "sermons noted",
    "verses": "verses learned",
    "plans": "plans finished",
    "days": "days you came in",
}
# Shown in a new reflection's look back; the rest wait as "+" chips.
DEFAULT_COUNTS = ("entries", "answered", "sermons", "verses")
# The cave numbers that make sense as something to aim for.
AIMABLE_COUNTS = ("entries", "verses", "sermons", "plans")

MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)
# A season the person names can run up to three years.
MAX_SEASON_DAYS = 3 * 366
# The halfway check-in shows for two weeks from the middle of a stretch, and
# only for stretches longer than a month.
CHECK_IN_DAYS = 14
CHECK_IN_MIN_DAYS = 60

_SETUP_HINT = (
    "Reflections need a database update. Run supabase/migrations/20261113_reflections.sql "
    "in the Supabase SQL editor."
)


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


# ---------------------------------------------------------------------------
# Stretches of time (pure, unit tested in tests/test_reflections.py)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Period:
    """The stretch looked back on and the stretch looked ahead to."""

    starts_on: date
    ends_on: date
    ahead_starts_on: date
    ahead_ends_on: date

    def as_dict(self) -> dict:
        return {
            "starts_on": self.starts_on.isoformat(),
            "ends_on": self.ends_on.isoformat(),
            "ahead_starts_on": self.ahead_starts_on.isoformat(),
            "ahead_ends_on": self.ahead_ends_on.isoformat(),
            "label": period_label(self.starts_on, self.ends_on),
            "ahead_label": period_label(self.ahead_starts_on, self.ahead_ends_on),
        }


def add_months(first_of_month: date, months: int) -> date:
    """The first of the month `months` away from a first of the month."""
    years, month_index = divmod(first_of_month.month - 1 + months, 12)
    return date(first_of_month.year + years, month_index + 1, 1)


def month_end(day: date) -> date:
    return add_months(day.replace(day=1), 1) - timedelta(days=1)


def period_for(span: str, today: date, shift: int = 0) -> Period:
    """The stretch a reflection of this length would look back on today, moved
    `shift` stretches earlier (negative) or later.

    It picks the one that's ending: the month, quarter or year today falls in,
    unless that one has only just begun, in which case the one before it.
    Early January looks back on the year just gone; so does February.
    """
    if span == "month":
        start = today.replace(day=1)
        if today.day <= 7:
            start = add_months(start, -1)
        start = add_months(start, shift)
        end = month_end(start)
        return Period(start, end, end + timedelta(days=1), month_end(end + timedelta(days=1)))
    if span == "quarter":
        start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        if (today - start).days < 14:
            start = add_months(start, -3)
        start = add_months(start, 3 * shift)
        ahead = add_months(start, 3)
        return Period(start, ahead - timedelta(days=1), ahead, add_months(ahead, 3) - timedelta(days=1))
    if span == "year":
        year = (today.year - 1 if today.month <= 2 else today.year) + shift
        return Period(date(year, 1, 1), date(year, 12, 31), date(year + 1, 1, 1), date(year + 1, 12, 31))
    raise ValueError(f"{span} needs its own dates")


def season_period(starts_on: date, ends_on: date) -> Period:
    """A season the person names, and one as long straight after it: as many
    whole months when the season is whole months (March to September, then
    October to April), otherwise as many days."""
    if ends_on < starts_on:
        raise HTTPException(status_code=422, detail="A season ends after it starts.")
    length = (ends_on - starts_on).days
    if length > MAX_SEASON_DAYS:
        raise HTTPException(status_code=422, detail="A season can run up to three years.")
    ahead = ends_on + timedelta(days=1)
    if starts_on.day == 1 and ends_on == month_end(ends_on):
        months = (ends_on.year - starts_on.year) * 12 + ends_on.month - starts_on.month + 1
        return Period(starts_on, ends_on, ahead, add_months(ahead, months) - timedelta(days=1))
    return Period(starts_on, ends_on, ahead, ahead + timedelta(days=length))


def period_label(start: date, end: date) -> str:
    """A stretch as people say it: "2026", "October 2026", "Oct to Dec 2026",
    "Nov 2026 to Feb 2027", or with days when it doesn't follow the months."""
    whole_months = start.day == 1 and end == month_end(end)
    if whole_months and (start.month, end.month) == (1, 12) and start.year == end.year:
        return str(start.year)
    if whole_months and (start.year, start.month) == (end.year, end.month):
        return f"{MONTHS[start.month - 1]} {start.year}"
    if whole_months:
        first, last = MONTHS[start.month - 1][:3], MONTHS[end.month - 1][:3]
        if start.year == end.year:
            return f"{first} to {last} {end.year}"
        return f"{first} {start.year} to {last} {end.year}"
    first = f"{start.day} {MONTHS[start.month - 1][:3]}"
    last = f"{end.day} {MONTHS[end.month - 1][:3]}"
    if start.year == end.year:
        return f"{first} to {last} {end.year}"
    return f"{first} {start.year} to {last} {end.year}"


def in_check_in(today: date, starts_on: date, ends_on: date) -> bool:
    """Whether today falls in a stretch's halfway check-in: the two weeks from
    its middle. A month is too short to need one."""
    length = (ends_on - starts_on).days
    if length < CHECK_IN_MIN_DAYS:
        return False
    middle = starts_on + timedelta(days=length // 2)
    return middle <= today < middle + timedelta(days=CHECK_IN_DAYS)


# ---------------------------------------------------------------------------
# Reading the cave (pure helpers first, unit tested)
# ---------------------------------------------------------------------------
_CHAPTER = re.compile(r"^(.*\S)\s+(\d+)")


def top_passages(refs: list[str], limit: int = 5) -> list[str]:
    """The chapters someone kept coming back to, most often first. Verses of
    one chapter count together ("Psalms 23:1" and "Psalms 23:4" are Psalm 23)."""
    chapters = []
    for ref in refs:
        match = _CHAPTER.match((ref or "").strip())
        if match:
            chapters.append(f"{match.group(1)} {match.group(2)}")
    return [ref for ref, _ in Counter(chapters).most_common(limit)]


def seed_status(seed: dict) -> str:
    """A pebble's status in a reflection's words."""
    return {"fulfilled": "reached", "set_aside": "not_this_time"}.get(seed.get("status"), "on_the_way")


def seed_progress(seed: dict) -> str | None:
    """How far along a pebble goal is, as a short line ("9 of 12")."""
    measure = goal_measure(seed)
    if not measure:
        return None
    done, of = measure["done"], measure["of"]
    return f"{done:g} of {of:g}"


def weeks_kept(days: set[date], per_week: int, start: date, end: date) -> dict:
    """For a habit over a stretch: how many weeks (Monday to Sunday) it was
    kept as often as it was meant to be, out of the weeks so far."""
    if end < start:
        return {"kept": 0, "weeks": 0}
    monday = start - timedelta(days=start.weekday())
    kept = weeks = 0
    while monday <= end:
        week = {monday + timedelta(days=n) for n in range(7)}
        weeks += 1
        if len(days & week) >= per_week:
            kept += 1
        monday += timedelta(days=7)
    return {"kept": kept, "weeks": weeks}


def _span_of(start: date, end: date) -> tuple[str, str]:
    """created_at bounds for a stretch of local days: from its first day up to,
    not including, the day after its last."""
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


def cave_counts(user_id: str, start: date, end: date, keys=tuple(CAVE_COUNTS)) -> dict[str, int]:
    """What Adullum can count for a stretch of time. A count whose table isn't
    there yet (a migration not run) is left out rather than failing the rest."""
    db = get_supabase()
    since, until = _span_of(start, end)

    def counted(table: str, column: str = "created_at", select: str = "id", **eq):
        q = db.table(table).select(select, count="exact").eq("user_id", user_id)
        for name, value in eq.items():
            q = q.eq(name, value)
        return q.gte(column, since).lt(column, until).limit(1).execute().count or 0

    def finished_plans() -> int:
        rows = db.table("reading_plans").select("start_date, days, completed_days").eq("user_id", user_id).execute().data
        done = 0
        for plan in rows:
            # A plan finished when every day was read. When isn't stored, so
            # it counts in the stretch its last scheduled day falls in.
            if len(plan.get("completed_days") or []) >= plan["days"]:
                last = date.fromisoformat(plan["start_date"]) + timedelta(days=plan["days"] - 1)
                done += start <= last <= end
        return done

    def verses_learned() -> int:
        q = db.table("memory_verses").select("id", count="exact").eq("user_id", user_id).gte("reps", 1)
        return q.gte("created_at", since).lt("created_at", until).limit(1).execute().count or 0

    readers = {
        "entries": lambda: counted("journal_entries"),
        "answered": lambda: counted("prayers", "answered_at", status="answered"),
        "sermons": lambda: counted("sermon_notes"),
        "verses": verses_learned,
        "plans": finished_plans,
        "days": lambda: counted("user_activity", "day", select="day"),
    }
    counts = {}
    for key in keys:
        try:
            counts[key] = readers[key]()
        except Exception:
            log.info("reflection count %s unavailable", key, exc_info=True)
    return counts


def _pebble_goals(user_id: str, start: date, end: date) -> list[dict]:
    """Pebble goals that belong to a stretch: begun before it ended, and still
    open or reached during it."""
    since, until = _span_of(start, end)
    seeds = (
        get_supabase().table("refuge_seeds")
        .select("id, title, status, steps, target, progress, unit, fulfilled_at, created_at")
        .eq("user_id", user_id).eq("kind", "goal").lt("created_at", until)
        .order("created_at").limit(40).execute().data
    )
    goals = []
    for s in seeds:
        if s["status"] == "fulfilled" and (s.get("fulfilled_at") or "") < since:
            continue
        if s["status"] == "set_aside":
            continue
        goals.append({"seed_id": s["id"], "title": s["title"], "status": seed_status(s), "progress": seed_progress(s)})
    return goals


def look_back_summary(user_id: str, start: date, end: date) -> dict:
    """The live side of a look back: the passages someone kept coming back to
    and the prayers answered (the "stones of help", 1 Samuel 7:12). Each part
    fails to empty on its own."""
    db = get_supabase()
    since, until = _span_of(start, end)
    passages: list[str] = []
    try:
        for e in db.table("journal_entries").select("passage_ref, citations").eq("user_id", user_id).gte("created_at", since).lt("created_at", until).execute().data:
            if e.get("passage_ref"):
                passages.append(e["passage_ref"])
            passages += [f"{c['book']} {c['chapter']}:{c['verse']}" for c in e.get("citations") or []]
    except Exception:
        log.info("reflection passages from the journal unavailable", exc_info=True)
    try:
        for s in db.table("sermon_notes").select("passages").eq("user_id", user_id).gte("created_at", since).lt("created_at", until).execute().data:
            passages += s.get("passages") or []
    except Exception:
        log.info("reflection passages from sermons unavailable", exc_info=True)
    try:
        stones = [
            {"text": " ".join(p["body"].split())[:120], "answered_at": p["answered_at"]}
            for p in db.table("prayers").select("body, answered_at").eq("user_id", user_id).eq("status", "answered")
            .gte("answered_at", since).lt("answered_at", until).order("answered_at").limit(20).execute().data
        ]
    except Exception:
        log.info("reflection answered prayers unavailable", exc_info=True)
        stones = []
    return {"passages": top_passages(passages), "stones": stones}


def plan_progress(user_id: str, look_ahead: dict, start: date, end: date, today: date) -> dict:
    """How a kept plan stands: each number aimed for beside what's been done,
    and each goal tracked in Pebbles beside how far along it is. Counted up to
    today while the stretch runs, and over all of it once it's over."""
    until = min(end, today)
    numbers = look_ahead.get("numbers") or []
    areas = look_ahead.get("areas") or []
    seed_ids = [n["seed_id"] for n in numbers if n.get("seed_id")]
    seed_ids += [g["seed_id"] for a in areas for g in a.get("goals") or [] if g.get("seed_id")]

    seeds: dict[str, dict] = {}
    checkins: dict[str, set[date]] = {}
    if seed_ids:
        db = get_supabase()
        try:
            rows = db.table("refuge_seeds").select("id, kind, status, steps, target, progress, unit, per_week").eq("user_id", user_id).in_("id", seed_ids).execute().data
            seeds = {s["id"]: s for s in rows}
            habits = [s["id"] for s in rows if s["kind"] == "habit"]
            if habits:
                for c in db.table("refuge_checkins").select("seed_id, day").eq("user_id", user_id).in_("seed_id", habits).gte("day", start.isoformat()).lte("day", until.isoformat()).execute().data:
                    checkins.setdefault(c["seed_id"], set()).add(date.fromisoformat(c["day"]))
        except Exception:
            log.info("reflection pebbles unavailable", exc_info=True)

    counted = cave_counts(user_id, start, until, keys=[n["key"] for n in numbers if n.get("key")]) if until >= start else {}

    number_rows = []
    for n in numbers:
        if n.get("key"):
            done = counted.get(n["key"])
        else:
            seed = seeds.get(n.get("seed_id") or "")
            done = float(seed.get("progress") or 0) if seed else None
        number_rows.append({"label": n.get("label"), "target": n.get("target"), "done": done})

    goal_rows = []
    for area in areas:
        for g in area.get("goals") or []:
            seed = seeds.get(g.get("seed_id") or "")
            row = {"area": area.get("name"), "text": g.get("text"), "kind": g.get("kind"), "status": None}
            if seed and seed["kind"] == "habit":
                row.update(weeks_kept(checkins.get(seed["id"], set()), seed.get("per_week") or 7, start, until))
                row["status"] = seed_status(seed)
            elif seed:
                row.update(status=seed_status(seed), progress=seed_progress(seed), measure=goal_measure(seed))
            goal_rows.append(row)

    return {
        "numbers": number_rows,
        "goals": goal_rows,
        "areas": [{"name": a.get("name"), "aim": a.get("aim")} for a in areas if a.get("aim")],
    }


# ---------------------------------------------------------------------------
# What a reflection holds
# ---------------------------------------------------------------------------
class CountedNumber(BaseModel):
    """A number in the look back: counted from the cave (`key`) or the
    person's own, with the value as they want it shown ("7", "£3k")."""

    key: CaveCount | None = None
    label: str = Field(default="", max_length=60)
    value: str = Field(default="", max_length=20)


class GoalLookedBack(BaseModel):
    seed_id: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    status: GoalStatus | None = None
    progress: str | None = Field(default=None, max_length=40)


class AreaLookedBack(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    rating: Rating | None = None
    note: str = Field(default="", max_length=500)


class LookBack(BaseModel):
    numbers: list[CountedNumber] = Field(default_factory=list, max_length=24)
    goals: list[GoalLookedBack] = Field(default_factory=list, max_length=40)
    areas: list[AreaLookedBack] = Field(default_factory=list, max_length=16)
    saw_god: str = Field(default="", max_length=4000)
    taught: str = Field(default="", max_length=4000)


class LayDown(BaseModel):
    grateful: str = Field(default="", max_length=4000)
    lay_down: str = Field(default="", max_length=4000)
    forgive: str = Field(default="", max_length=4000)


class AimNumber(BaseModel):
    """A number to aim for. A cave count (`key`) is counted by Adullum; the
    person's own becomes a Pebbles goal when the reflection is kept, so they
    can move it along as they go."""

    key: CaveCount | None = None
    label: str = Field(default="", max_length=60)
    target: float | None = Field(default=None, gt=0, le=1_000_000_000)
    last: str | None = Field(default=None, max_length=20)
    seed_id: uuid.UUID | None = None


class GoalAhead(BaseModel):
    """Something the person would like to see in an area of life: a habit
    (days a week), a number to reach, something to do by a date, or a hope."""

    text: str = Field(min_length=1, max_length=200)
    kind: GoalKind = "hope"
    per_week: int | None = Field(default=None, ge=1, le=7)
    target: float | None = Field(default=None, gt=0, le=1_000_000_000)
    unit: str | None = Field(default=None, max_length=30)
    due_on: date | None = None
    track: bool = False
    seed_id: uuid.UUID | None = None


class AreaAhead(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    aim: Rating | None = None
    goals: list[GoalAhead] = Field(default_factory=list, max_length=12)


class LookAhead(BaseModel):
    word: str = Field(default="", max_length=40)
    verse_ref: str | None = Field(default=None, max_length=120)
    numbers: list[AimNumber] = Field(default_factory=list, max_length=16)
    areas: list[AreaAhead] = Field(default_factory=list, max_length=16)
    asking: str = Field(default="", max_length=4000)
    leading: str = Field(default="", max_length=4000)


TITLE_LENGTH = 80


def clean_title(title: str | None) -> str | None:
    """A reflection's own name with its spacing tidied, or None when it's
    left blank, in which case the page calls it by its dates."""
    return " ".join((title or "").split())[:TITLE_LENGTH] or None


class ReflectionIn(BaseModel):
    span: Span
    title: str | None = Field(default=None, max_length=200)
    today: str | None = None
    shift: int = Field(default=0, ge=-24, le=24)
    # A season's own dates. Ignored for the other spans.
    starts_on: date | None = None
    ends_on: date | None = None


class ReflectionPatch(BaseModel):
    # An empty name clears it; leaving it out keeps the one there.
    title: str | None = Field(default=None, max_length=200)
    look_back: LookBack | None = None
    lay_down: LayDown | None = None
    look_ahead: LookAhead | None = None


class KeepIn(BaseModel):
    today: str | None = None


def resolve_period(span: str, today: date, shift: int = 0, starts_on: date | None = None, ends_on: date | None = None) -> Period:
    if span == "season":
        if not (starts_on and ends_on):
            raise HTTPException(status_code=422, detail="Choose when the season started and ended.")
        return season_period(starts_on, ends_on)
    return period_for(span, today, shift)


def starting_look_back(counts: dict[str, int], goals: list[dict], previous: dict | None) -> dict:
    """A new reflection's look back: the usual cave numbers, the person's
    Pebbles goals, and the areas of life they planned for last time."""
    numbers = [{"key": k, "label": CAVE_COUNTS[k], "value": str(counts[k])} for k in DEFAULT_COUNTS if k in counts]
    areas = [{"name": a["name"], "rating": None, "note": ""} for a in ((previous or {}).get("look_ahead") or {}).get("areas", [])]
    return {"numbers": numbers, "goals": goals, "areas": areas, "saw_god": "", "taught": ""}


def seed_for(goal: dict, area: str, label: str) -> dict | None:
    """The Pebbles row a tracked goal becomes, or None for one that can't be
    tracked (a hope, or a number with nothing to count to)."""
    note = f"{area}, from your reflection on {label}"
    if goal["kind"] == "habit":
        return {"kind": "habit", "title": goal["text"], "note": note, "steps": [], "per_week": goal.get("per_week") or 1}
    if goal["kind"] == "number" and goal.get("target"):
        return {"kind": "goal", "title": goal["text"], "note": note, "steps": [], "target": goal["target"], "unit": goal.get("unit")}
    if goal["kind"] == "date":
        return {"kind": "goal", "title": goal["text"], "note": note, "steps": [], "due_on": goal.get("due_on")}
    return None


def seed_for_number(number: dict, label: str) -> dict | None:
    """The Pebbles goal for one of the person's own numbers to aim for."""
    if number.get("key") or not number.get("target") or not (number.get("label") or "").strip():
        return None
    title = f"{number['target']:g} {number['label'].strip()}"
    return {"kind": "goal", "title": title, "note": f"From your reflection on {label}", "steps": [], "target": number["target"], "unit": number["label"].strip()}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
_LIST_FIELDS = "id, title, span, starts_on, ends_on, ahead_starts_on, ahead_ends_on, status, look_ahead, kept_at, created_at, updated_at"


def _dates(row: dict) -> Period:
    return Period(*(date.fromisoformat(row[k]) for k in ("starts_on", "ends_on", "ahead_starts_on", "ahead_ends_on")))


def _with_labels(row: dict) -> dict:
    period = _dates(row)
    return {**row, "label": period_label(period.starts_on, period.ends_on), "ahead_label": period_label(period.ahead_starts_on, period.ahead_ends_on)}


def _own(reflection_id: str, user: AuthUser) -> dict:
    rows = _db(lambda: get_supabase().table("reflections").select("*").eq("id", reflection_id).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That reflection isn't here anymore.")
    return rows[0]


def _last_kept(user: AuthUser, span: str | None = None, before: str | None = None) -> dict | None:
    q = get_supabase().table("reflections").select(_LIST_FIELDS).eq("user_id", user.id).eq("status", "kept")
    if span:
        q = q.eq("span", span)
    if before:
        q = q.lt("ahead_starts_on", before)
    rows = q.order("ahead_ends_on", desc=True).limit(1).execute().data
    return rows[0] if rows else None


@router.get("/me/reflections/period")
def preview_period(
    span: Span,
    today: str | None = None,
    shift: int = 0,
    starts_on: date | None = None,
    ends_on: date | None = None,
    user: AuthUser = Depends(require_user),
) -> dict:
    """What a new reflection of this length would look back on and ahead to,
    and the word the person chose last time they did one this long."""
    period = resolve_period(span, parse_today(today), max(-24, min(24, shift)), starts_on, ends_on)
    last = _db(lambda: _last_kept(user, span))
    return {"span": span, **period.as_dict(), "last_word": ((last or {}).get("look_ahead") or {}).get("word") or None}


@router.get("/me/reflections")
def list_reflections(today: str | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every reflection, newest first. A kept one whose stretch ahead is
    running today is `current`, and carries how its plan stands."""
    day = parse_today(today)
    rows = _db(lambda: (
        get_supabase().table("reflections").select(_LIST_FIELDS).eq("user_id", user.id)
        .order("ahead_ends_on", desc=True).order("created_at", desc=True).limit(60).execute().data
    ))
    out = []
    for row in rows:
        row = _with_labels(row)
        period = _dates(row)
        row["current"] = row["status"] == "kept" and period.ahead_starts_on <= day <= period.ahead_ends_on
        if row["current"]:
            row["progress"] = plan_progress(user.id, row.get("look_ahead") or {}, period.ahead_starts_on, period.ahead_ends_on, day)
        out.append(row)
    return out


@router.post("/me/reflections")
def start_reflection(body: ReflectionIn, user: AuthUser = Depends(require_user)) -> dict:
    """Starts a reflection as a draft, with its look back already holding the
    usual cave numbers, the person's Pebbles goals and last time's areas."""
    period = resolve_period(body.span, parse_today(body.today), body.shift, body.starts_on, body.ends_on)
    _db(lambda: get_supabase().table("reflections").select("id").eq("user_id", user.id).limit(1).execute())
    counts = cave_counts(user.id, period.starts_on, period.ends_on, keys=DEFAULT_COUNTS)
    try:
        goals = _pebble_goals(user.id, period.starts_on, period.ends_on)
    except Exception:
        log.info("pebble goals unavailable for a new reflection", exc_info=True)
        goals = []
    previous = _last_kept(user, before=period.ahead_starts_on.isoformat())
    row = {
        "user_id": user.id,
        "title": clean_title(body.title),
        "span": body.span,
        "starts_on": period.starts_on.isoformat(),
        "ends_on": period.ends_on.isoformat(),
        "ahead_starts_on": period.ahead_starts_on.isoformat(),
        "ahead_ends_on": period.ahead_ends_on.isoformat(),
        "look_back": starting_look_back(counts, goals, previous),
        "look_ahead": {"areas": [{"name": a["name"], "aim": None, "goals": []} for a in ((previous or {}).get("look_ahead") or {}).get("areas", [])]},
    }
    created = _db(lambda: get_supabase().table("reflections").insert(row).execute().data[0])
    return open_reflection(uuid.UUID(created["id"]), body.today, user)


@router.get("/me/reflections/{reflection_id}")
def open_reflection(reflection_id: uuid.UUID, today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """A reflection as it was left, with what the cave holds for its stretch
    (every number Adullum can count, passages, answered prayers) and "What you
    set out": the plan kept for this stretch last time, beside what happened."""
    row = _with_labels(_own(str(reflection_id), user))
    period = _dates(row)
    day = parse_today(today)
    summary = look_back_summary(user.id, period.starts_on, period.ends_on)
    summary["counts"] = cave_counts(user.id, period.starts_on, period.ends_on)
    summary["aim_lasts"] = {k: summary["counts"][k] for k in AIMABLE_COUNTS if k in summary["counts"]}
    try:
        summary["goals"] = _pebble_goals(user.id, period.starts_on, period.ends_on)
    except Exception:
        summary["goals"] = []

    set_out = None
    try:
        earlier = (
            get_supabase().table("reflections").select(_LIST_FIELDS).eq("user_id", user.id).eq("status", "kept")
            .neq("id", row["id"]).lte("ahead_starts_on", row["ends_on"]).gte("ahead_ends_on", row["starts_on"])
            .order("ahead_ends_on", desc=True).limit(5).execute().data
        )
        # The plan made for exactly this stretch, else the latest that overlaps it.
        plan = next((r for r in earlier if r["span"] == row["span"]), earlier[0] if earlier else None)
        if plan:
            plan = _with_labels(plan)
            plan_dates = _dates(plan)
            set_out = {
                "label": plan["ahead_label"],
                "word": (plan.get("look_ahead") or {}).get("word"),
                **plan_progress(user.id, plan.get("look_ahead") or {}, plan_dates.ahead_starts_on, plan_dates.ahead_ends_on, day),
            }
    except Exception:
        log.info("what you set out unavailable", exc_info=True)
    return {**row, "summary": summary, "set_out": set_out, "cave_counts": CAVE_COUNTS, "aimable": list(AIMABLE_COUNTS)}


@router.put("/me/reflections/{reflection_id}")
def save_reflection(reflection_id: uuid.UUID, body: ReflectionPatch, user: AuthUser = Depends(require_user)) -> dict:
    """Saves whichever parts the page sends, as the person writes.

    The verse is put in the canonical form the reader reads back. One that
    isn't a Bible reference yet (half typed, or a typo) is kept as written and
    named in `verse_error`, so it never costs the person the rest of their
    writing."""
    patch = body.model_dump(mode="json", exclude_none=True)
    if "title" in patch:
        patch["title"] = clean_title(patch["title"])
    verse_error = None
    if "look_ahead" in patch:
        typed = patch["look_ahead"].get("verse_ref")
        try:
            patch["look_ahead"]["verse_ref"] = normalize_passage(typed)
        except HTTPException as err:
            patch["look_ahead"]["verse_ref"] = " ".join(typed.split())
            verse_error = err.detail
    patch["updated_at"] = _now()
    rows = _db(lambda: get_supabase().table("reflections").update(patch).eq("id", str(reflection_id)).eq("user_id", user.id).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That reflection isn't here anymore.")
    return {
        "id": rows[0]["id"],
        "title": rows[0].get("title"),
        "updated_at": rows[0]["updated_at"],
        "verse_ref": (rows[0].get("look_ahead") or {}).get("verse_ref"),
        "verse_error": verse_error,
    }


@router.post("/me/reflections/{reflection_id}/keep")
def keep_reflection(reflection_id: uuid.UUID, body: KeepIn, user: AuthUser = Depends(require_user)) -> dict:
    """Keeps a reflection, making its look ahead the plan for the stretch
    ahead. Each goal marked to track, and each of the person's own numbers to
    aim for, becomes a pebble (once: those already tracked keep theirs)."""
    row = _with_labels(_own(str(reflection_id), user))
    look_ahead = row.get("look_ahead") or {}
    db = get_supabase()
    planted = 0

    def plant(seed: dict) -> str:
        nonlocal planted
        created = _pebbles_db(lambda: db.table("refuge_seeds").insert({**seed, "user_id": user.id}).execute().data[0])
        planted += 1
        return created["id"]

    for number in look_ahead.get("numbers") or []:
        seed = None if number.get("seed_id") else seed_for_number(number, row["ahead_label"])
        if seed:
            number["seed_id"] = plant(seed)
    for area in look_ahead.get("areas") or []:
        for goal in area.get("goals") or []:
            seed = seed_for(goal, area["name"], row["ahead_label"]) if goal.get("track") and not goal.get("seed_id") else None
            if seed:
                goal["seed_id"] = plant(seed)

    now = datetime.now(timezone.utc).isoformat()
    kept = _db(lambda: (
        db.table("reflections").update({"status": "kept", "kept_at": row.get("kept_at") or now, "look_ahead": look_ahead, "updated_at": now})
        .eq("id", row["id"]).eq("user_id", user.id).execute().data[0]
    ))
    return {**_with_labels(kept), "planted": planted}


@router.delete("/me/reflections/{reflection_id}")
def delete_reflection(reflection_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """Deletes a reflection. Pebbles it started stay in Refuge."""
    _db(lambda: get_supabase().table("reflections").delete().eq("id", str(reflection_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# The home screen's halfway check-in (app/hearth.py)
# ---------------------------------------------------------------------------
def reflection_glance(user: AuthUser, today: date) -> dict | None:
    """The plan someone is halfway through, for two weeks from the middle of
    its stretch: their word, their verse, and how it's going. None otherwise."""
    rows = (
        get_supabase().table("reflections").select(_LIST_FIELDS).eq("user_id", user.id).eq("status", "kept")
        .lte("ahead_starts_on", today.isoformat()).gte("ahead_ends_on", today.isoformat())
        .order("ahead_ends_on", desc=True).limit(3).execute().data
    )
    for row in rows:
        period = _dates(row)
        if in_check_in(today, period.ahead_starts_on, period.ahead_ends_on):
            look_ahead = row.get("look_ahead") or {}
            return {
                "id": row["id"],
                "title": row.get("title"),
                "ahead_label": period_label(period.ahead_starts_on, period.ahead_ends_on),
                "word": look_ahead.get("word") or None,
                "verse_ref": look_ahead.get("verse_ref"),
                "progress": plan_progress(user.id, look_ahead, period.ahead_starts_on, period.ahead_ends_on, today),
            }
    return None
