"""Refuge: the quiet room in the cave, for every kind of season.

Five ways in, each with its routes here or in app/one_another.py:
- Write it out: writing that is let go of never reaches the server. Only
  what someone chooses to keep is stored (`refuge_writings`).
- Talk with Aquila: the agent graph in listening mode (app/agent/nodes.py::
  listen). A talk vanishes by default; it's stored (`refuge_talks`) only when
  the person presses Keep. These runs are never traced to Langfuse, and
  nothing said here reaches Aquila's memory.
- Pebbles (once "Grow"): goals and habits (`refuge_seeds`, so the code still
  says seeds). A goal is reached through steps, a number (12 books), or simply
  marked reached, optionally by a date; a habit is meant for some days a week
  and its days done are `refuge_checkins`. Praying and fasting live on the
  prayer list instead (app/prayers.py, app/fasting.py).
- Be still: entirely in the browser.
- Amens: the wall, app/one_another.py.

Nothing here appears on the home screen or feeds user_memories. Every query
filters by the signed-in user's id in code, same rule as app/cave.py.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agent.graph import agent
from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.days import MARKABLE_DAYS, parse_markable_day, parse_today, week_marks
from app.db import get_supabase
from app.one_another import _db, carried_summary
from app.prayers import normalize_passage

log = logging.getLogger(__name__)

router = APIRouter()

Shape = Literal["blank", "lament", "thanks", "dream"]
SeedKind = Literal["goal", "habit"]
SeedStatus = Literal["growing", "fulfilled", "set_aside"]

MAX_STEPS = 12
MAX_TARGET = 1_000_000_000
TITLE_LENGTH = 60

# Pebbles read columns added by a later migration than the rest of Refuge, so
# their setup message names that one.
_PEBBLES_HINT = (
    "Pebbles needs a database update. Run supabase/migrations/20261112_pebbles_and_prayer_practice.sql "
    "in the Supabase SQL editor."
)


def _pebbles_db(fn):
    return _db_call(fn, _PEBBLES_HINT)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_refuge.py)
# ---------------------------------------------------------------------------
def talk_title(messages: list[dict]) -> str:
    """A kept talk's title: the start of the first thing the person said."""
    first = next((m["content"] for m in messages if m.get("role") == "user"), "") or "A talk with Aquila"
    first = " ".join(first.split())
    return first if len(first) <= TITLE_LENGTH else first[: TITLE_LENGTH - 3].rstrip() + "..."


def clean_steps(steps: list) -> list[dict]:
    """Goal steps as [{text, done}], blank ones dropped, capped at MAX_STEPS.
    Accepts plain strings (a new goal) or {text, done} (an edited one)."""
    out = []
    for step in steps or []:
        text, done = (step, False) if isinstance(step, str) else (step.get("text", ""), bool(step.get("done")))
        text = " ".join(str(text).split())[:200]
        if text:
            out.append({"text": text, "done": done})
    return out[:MAX_STEPS]


def goal_measure(seed: dict) -> dict | None:
    """How far along a goal is, for its progress bar: steps done of steps, or
    the number reached of the number set. None for a goal that is simply
    marked reached one day, which has nothing to count."""
    if seed.get("target"):
        target = float(seed["target"])
        done = float(seed.get("progress") or 0)
        return {"by": "number", "done": done, "of": target, "fraction": min(done / target, 1.0)}
    steps = seed.get("steps") or []
    if steps:
        done = sum(1 for s in steps if s.get("done"))
        return {"by": "steps", "done": done, "of": len(steps), "fraction": done / len(steps)}
    return None


def goal_tracking(steps: list | None, target: float | None) -> tuple[list[dict], float | None]:
    """A goal is tracked one way: by a number, or by steps, or neither. A
    number wins if both are sent, so a goal never shows two progress bars."""
    if target:
        return [], target
    return clean_steps(steps or []), None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class WritingIn(BaseModel):
    shape: Shape = "blank"
    body: str = Field(min_length=1, max_length=20000)


class TalkMessage(BaseModel):
    role: Literal["user", "aquila"]
    content: str = Field(min_length=1, max_length=4000)


class TalkIn(BaseModel):
    messages: list[TalkMessage] = Field(min_length=1, max_length=120)
    translation: str | None = None


class KeptTalkIn(BaseModel):
    messages: list[TalkMessage] = Field(min_length=1, max_length=120)


class Step(BaseModel):
    text: str = Field(max_length=200)
    done: bool = False


class SeedIn(BaseModel):
    kind: SeedKind
    title: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    passage_ref: str | None = Field(default=None, max_length=120)
    # Goals: steps, or a number to reach (target and its unit), and a date.
    steps: list[str] = Field(default_factory=list, max_length=MAX_STEPS)
    target: float | None = Field(default=None, gt=0, le=MAX_TARGET)
    unit: str | None = Field(default=None, max_length=30)
    due_on: date | None = None
    # Habits: how many days a week it's meant for.
    per_week: int = Field(default=7, ge=1, le=7)


class SeedPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    passage_ref: str | None = Field(default=None, max_length=120)
    steps: list[Step] | None = Field(default=None, max_length=MAX_STEPS)
    target: float | None = Field(default=None, gt=0, le=MAX_TARGET)
    progress: float | None = Field(default=None, ge=0, le=MAX_TARGET)
    unit: str | None = Field(default=None, max_length=30)
    due_on: date | None = None
    per_week: int | None = Field(default=None, ge=1, le=7)
    status: SeedStatus | None = None
    outcome_note: str | None = Field(default=None, max_length=2000)


class TendIn(BaseModel):
    today: str | None = None
    # Which day to mark: today when left out, or one of the last seven.
    day: str | None = None
    tended: bool = True


# ---------------------------------------------------------------------------
# The opening screen: one request
# ---------------------------------------------------------------------------
@router.get("/me/refuge")
def overview(user: AuthUser = Depends(require_user)) -> dict:
    """What Refuge's opening screen shows: what's been kept, and whether
    anyone has been carrying what this person shared. The first query raises
    the setup 503 if the migration hasn't run; the rest fail quietly."""
    db = get_supabase()
    writings = _db(lambda: (
        db.table("refuge_writings").select("id, shape, body, created_at")
        .eq("user_id", user.id).order("created_at", desc=True).limit(30).execute().data
    ))
    try:
        talks = (
            db.table("refuge_talks").select("id, title, created_at, updated_at")
            .eq("user_id", user.id).order("updated_at", desc=True).limit(30).execute().data
        )
    except Exception:
        log.warning("refuge talks failed", exc_info=True)
        talks = []
    try:
        carried = carried_summary(user)
    except Exception:
        log.warning("refuge carried summary failed", exc_info=True)
        carried = None
    return {"writings": writings, "talks": talks, "carried": carried}


# ---------------------------------------------------------------------------
# Writing kept
# ---------------------------------------------------------------------------
@router.post("/me/refuge/writings")
def keep_writing(body: WritingIn, user: AuthUser = Depends(require_user)) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write a little first.")
    row = {"user_id": user.id, "shape": body.shape, "body": text}
    return _db(lambda: get_supabase().table("refuge_writings").insert(row).execute().data[0])


@router.delete("/me/refuge/writings/{writing_id}")
def let_go(writing_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("refuge_writings").delete().eq("id", str(writing_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Talk with Aquila
# ---------------------------------------------------------------------------
@router.post("/me/refuge/talk")
async def talk(body: TalkIn, user: AuthUser = Depends(require_user)) -> dict:
    """One reply from Aquila in listening mode, over the whole talk so far.
    The browser holds the talk; nothing is stored here. Deliberately run
    with no callbacks, so it is never traced to Langfuse."""
    messages = [m.model_dump() for m in body.messages]
    if messages[-1]["role"] != "user":
        raise HTTPException(status_code=422, detail="The last message should be yours.")
    state = {"mode": "listen", "history": messages, "query": messages[-1]["content"], "translation": body.translation}
    result = await agent.ainvoke(state, config={"callbacks": []})
    verses = [
        {"book": v.book, "chapter": v.chapter, "verse": v.verse, "translation": v.translation, "text": v.text}
        for v in result.get("citations", [])
    ]
    return {"reply": result["answer"], "care": bool(result.get("care")), "verses": verses}


def _own_talk(talk_id: str, user: AuthUser) -> dict:
    rows = _db(lambda: get_supabase().table("refuge_talks").select("*").eq("id", talk_id).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That talk isn't here anymore.")
    return rows[0]


@router.get("/me/refuge/talks/{talk_id}")
def open_talk(talk_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    return _own_talk(str(talk_id), user)


@router.post("/me/refuge/talks")
def keep_talk(body: KeptTalkIn, user: AuthUser = Depends(require_user)) -> dict:
    messages = [m.model_dump() for m in body.messages]
    row = {"user_id": user.id, "title": talk_title(messages), "messages": messages}
    return _db(lambda: get_supabase().table("refuge_talks").insert(row).execute().data[0])


@router.put("/me/refuge/talks/{talk_id}")
def update_talk(talk_id: uuid.UUID, body: KeptTalkIn, user: AuthUser = Depends(require_user)) -> dict:
    """Rewrites a kept talk as it goes on."""
    messages = [m.model_dump() for m in body.messages]
    rows = _db(lambda: (
        get_supabase().table("refuge_talks").update({"messages": messages, "updated_at": _now()})
        .eq("id", str(talk_id)).eq("user_id", user.id).execute().data
    ))
    if not rows:
        raise HTTPException(status_code=404, detail="That talk isn't here anymore.")
    return {"id": rows[0]["id"], "updated_at": rows[0]["updated_at"]}


@router.delete("/me/refuge/talks/{talk_id}")
def erase_talk(talk_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("refuge_talks").delete().eq("id", str(talk_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Pebbles (once "Grow"): hopes, goals, habits and prayers
# ---------------------------------------------------------------------------
_SEED_FIELDS = (
    "id, kind, title, note, passage_ref, steps, target, progress, unit, due_on, per_week, "
    "status, outcome_note, fulfilled_at, created_at, updated_at"
)


def _clean_unit(unit: str | None) -> str | None:
    return " ".join((unit or "").split()) or None


@router.get("/me/refuge/seeds")
def list_seeds(today: str | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every pebble, active ones first. A goal comes with how far along it is
    (`measure`) and how many days are left (`due_in`); a habit with this week
    as seven marks and how many of them are done."""
    day = parse_today(today)
    db = get_supabase()
    seeds = _pebbles_db(lambda: db.table("refuge_seeds").select(_SEED_FIELDS).eq("user_id", user.id).order("created_at", desc=True).execute().data)
    since = (day - timedelta(days=MARKABLE_DAYS - 1)).isoformat()
    checkins = _db(lambda: db.table("refuge_checkins").select("seed_id, day").eq("user_id", user.id).gte("day", since).execute().data)
    for s in seeds:
        if s["kind"] == "habit":
            done = {date.fromisoformat(c["day"]) for c in checkins if c["seed_id"] == s["id"]}
            s["week"] = week_marks(done, day)
            s["week_done"] = sum(1 for m in s["week"] if m["done"])
            s["tended_today"] = day in done
        else:
            s["measure"] = goal_measure(s)
            s["due_in"] = (date.fromisoformat(s["due_on"]) - day).days if s.get("due_on") else None
    order = {"growing": 0, "fulfilled": 1, "set_aside": 2}
    return sorted(seeds, key=lambda s: order[s["status"]])


@router.post("/me/refuge/seeds")
def plant(body: SeedIn, user: AuthUser = Depends(require_user)) -> dict:
    row = {
        "user_id": user.id,
        "kind": body.kind,
        "title": body.title.strip(),
        "note": (body.note or "").strip() or None,
        "passage_ref": normalize_passage(body.passage_ref),
    }
    if body.kind == "goal":
        steps, target = goal_tracking(body.steps, body.target)
        row.update(steps=steps, target=target, unit=_clean_unit(body.unit) if target else None,
                   due_on=body.due_on.isoformat() if body.due_on else None)
    else:
        row.update(steps=[], per_week=body.per_week)
    return _pebbles_db(lambda: get_supabase().table("refuge_seeds").insert(row).execute().data[0])


@router.patch("/me/refuge/seeds/{seed_id}")
def tend_seed(seed_id: uuid.UUID, body: SeedPatch, user: AuthUser = Depends(require_user)) -> dict:
    """Edit a pebble, move a goal along (steps ticked, a new number), or
    change its status. Switching a goal to a number clears its steps, and
    the other way round."""
    patch = body.model_dump(exclude_unset=True)
    if "passage_ref" in patch:
        patch["passage_ref"] = normalize_passage(patch["passage_ref"])
    # Same rule as goal_tracking: a number wins, so there's one progress bar.
    if patch.get("target"):
        patch["steps"] = []
    elif "steps" in patch:
        patch["steps"] = clean_steps(patch["steps"] or [])
        if patch["steps"]:
            patch["target"] = None
    if "unit" in patch:
        patch["unit"] = _clean_unit(patch["unit"])
    if "due_on" in patch:
        patch["due_on"] = patch["due_on"].isoformat() if patch["due_on"] else None
    if "note" in patch:
        patch["note"] = (patch["note"] or "").strip() or None
    if "outcome_note" in patch:
        patch["outcome_note"] = (patch["outcome_note"] or "").strip() or None
    if patch.get("status") == "fulfilled":
        patch["fulfilled_at"] = datetime.now(timezone.utc).isoformat()
    elif "status" in patch:
        patch["fulfilled_at"] = None
        patch.setdefault("outcome_note", None)
    patch["updated_at"] = _now()
    rows = _pebbles_db(lambda: get_supabase().table("refuge_seeds").update(patch).eq("id", str(seed_id)).eq("user_id", user.id).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That isn't here anymore.")
    return rows[0]


@router.post("/me/refuge/seeds/{seed_id}/tend")
def tend_today(seed_id: uuid.UUID, body: TendIn, user: AuthUser = Depends(require_user)) -> dict:
    """Marks a habit done on a day (today, or one of the last seven), or takes
    that back."""
    today = parse_today(body.today)
    day = parse_markable_day(body.day, today).isoformat()
    db = get_supabase()
    owned = _db(lambda: db.table("refuge_seeds").select("id, kind").eq("id", str(seed_id)).eq("user_id", user.id).limit(1).execute().data)
    if not owned:
        raise HTTPException(status_code=404, detail="That isn't here anymore.")
    if owned[0]["kind"] != "habit":
        raise HTTPException(status_code=422, detail="Only habits are marked day by day.")
    if body.tended:
        row = {"seed_id": str(seed_id), "user_id": user.id, "day": day}
        db.table("refuge_checkins").upsert(row, on_conflict="seed_id,day", ignore_duplicates=True).execute()
    else:
        db.table("refuge_checkins").delete().eq("seed_id", str(seed_id)).eq("user_id", user.id).eq("day", day).execute()
    return {"day": day, "tended": body.tended}


@router.delete("/me/refuge/seeds/{seed_id}")
def uproot(seed_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("refuge_seeds").delete().eq("id", str(seed_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
