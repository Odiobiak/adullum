"""Fasting: a fast someone is keeping, alongside their prayer list.

A fast has a kind (water only, a Daniel fast, skipping a meal, or something
else given up for a while), a number of days from a start date, and what it's
for. While it's active the Prayers tab shows which day it is; finishing it
records the day and, if the person wants, a line on what they noticed. It's
never judged: finishing before the planned last day is still finishing.

Nothing here feeds Aquila's memory. Same rule as app/cave.py: the server's
Supabase client bypasses RLS, so every query filters by the signed-in user's
id itself. Never drop the `.eq("user_id", user.id)`.
"""

import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_user
from app.cave import _now
from app.days import parse_today
from app.db import get_supabase
from app.prayers import _practice_db, normalize_passage

router = APIRouter()

Kind = Literal["full", "daniel", "meal", "other"]
Status = Literal["active", "finished"]

MAX_DAYS = 40  # the longest fast in Scripture (Matthew 4:2), and plenty
EARLIEST_START_DAYS = 7  # a fast begun a few days ago can still be added
LATEST_START_DAYS = 60  # and one can be planned ahead
PAST_SHOWN = 30

_FIELDS = (
    "id, kind, detail, intention, passage_ref, starts_on, days, status, "
    "finished_on, reflection, created_at, updated_at"
)


class FastIn(BaseModel):
    kind: Kind = "full"
    detail: str | None = Field(default=None, max_length=80)
    intention: str | None = Field(default=None, max_length=1000)
    passage_ref: str | None = Field(default=None, max_length=120)
    starts_on: date | None = None  # today when left out
    days: int = Field(default=1, ge=1, le=MAX_DAYS)
    today: str | None = None


class FastPatch(BaseModel):
    kind: Kind | None = None
    detail: str | None = Field(default=None, max_length=80)
    intention: str | None = Field(default=None, max_length=1000)
    passage_ref: str | None = Field(default=None, max_length=120)
    days: int | None = Field(default=None, ge=1, le=MAX_DAYS)
    status: Status | None = None
    reflection: str | None = Field(default=None, max_length=2000)
    today: str | None = None


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_fasting.py)
# ---------------------------------------------------------------------------
def fast_progress(fast: dict, today: date) -> dict:
    """Where a fast stands today: which day it is (0 before it starts), of
    how many, the planned last day, and whether that day has come. A finished
    fast counts up to the day it was finished."""
    start = date.fromisoformat(fast["starts_on"])
    days = int(fast["days"])
    ends_on = start + timedelta(days=days - 1)
    until = date.fromisoformat(fast["finished_on"]) if fast.get("finished_on") else today
    day = max(0, min((until - start).days + 1, days))
    return {
        "day": day,
        "of": days,
        "fraction": day / days,
        "ends_on": ends_on.isoformat(),
        "starts_in": max(0, (start - today).days),
        "last_day_reached": today >= ends_on,
    }


def check_start(starts_on: date, today: date) -> None:
    """A start date within reach: up to a week ago, or a couple of months ahead."""
    if (today - starts_on).days > EARLIEST_START_DAYS:
        raise HTTPException(status_code=422, detail="A fast can start up to a week ago.")
    if (starts_on - today).days > LATEST_START_DAYS:
        raise HTTPException(status_code=422, detail="A fast can be planned up to two months ahead.")


def _clean(text: str | None) -> str | None:
    return (text or "").strip() or None


def _with_progress(fast: dict, today: date) -> dict:
    return {**fast, "progress": fast_progress(fast, today)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/me/fasts")
def list_fasts(today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """Fasts underway (soonest first) and the most recent finished ones."""
    day = parse_today(today)
    rows = _practice_db(
        lambda: get_supabase().table("fasts").select(_FIELDS).eq("user_id", user.id)
        .order("starts_on", desc=True).limit(PAST_SHOWN + 10).execute().data
    )
    active = sorted((r for r in rows if r["status"] == "active"), key=lambda r: r["starts_on"])
    past = [r for r in rows if r["status"] == "finished"][:PAST_SHOWN]
    return {
        "active": [_with_progress(r, day) for r in active],
        "past": [_with_progress(r, day) for r in past],
    }


@router.post("/me/fasts")
def start_fast(body: FastIn, user: AuthUser = Depends(require_user)) -> dict:
    day = parse_today(body.today)
    starts_on = body.starts_on or day
    check_start(starts_on, day)
    row = {
        "user_id": user.id,
        "kind": body.kind,
        "detail": _clean(body.detail),
        "intention": _clean(body.intention),
        "passage_ref": normalize_passage(body.passage_ref),
        "starts_on": starts_on.isoformat(),
        "days": body.days,
    }
    fast = _practice_db(lambda: get_supabase().table("fasts").insert(row).execute().data[0])
    return _with_progress(fast, day)


@router.patch("/me/fasts/{fast_id}")
def update_fast(fast_id: uuid.UUID, body: FastPatch, user: AuthUser = Depends(require_user)) -> dict:
    """Edit a fast, finish it (with an optional reflection), or pick it back up."""
    day = parse_today(body.today)
    sent = body.model_dump(exclude_unset=True, exclude={"today"})
    patch: dict = {"updated_at": _now()}
    for field in ("detail", "intention", "reflection"):
        if field in sent:
            patch[field] = _clean(sent[field])
    if "passage_ref" in sent:
        patch["passage_ref"] = normalize_passage(sent["passage_ref"])
    for field in ("kind", "days"):
        if sent.get(field) is not None:
            patch[field] = sent[field]
    if sent.get("status") == "finished":
        patch.update(status="finished", finished_on=day.isoformat())
    elif sent.get("status") == "active":
        patch.update(status="active", finished_on=None, reflection=None)
    rows = _practice_db(
        lambda: get_supabase().table("fasts").update(patch)
        .eq("id", str(fast_id)).eq("user_id", user.id).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="That fast isn't here anymore.")
    return _with_progress(rows[0], day)


@router.delete("/me/fasts/{fast_id}")
def delete_fast(fast_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _practice_db(lambda: get_supabase().table("fasts").delete().eq("id", str(fast_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
