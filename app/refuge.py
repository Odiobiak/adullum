"""Refuge: the quiet room in the cave, for every kind of season.

Five ways in, each with its routes here or in app/one_another.py:
- Write it out: writing that is let go of never reaches the server. Only
  what someone chooses to keep is stored (`refuge_writings`).
- Talk with Aquila: the agent graph in listening mode (app/agent/nodes.py::
  listen). A talk vanishes by default; it's stored (`refuge_talks`) only when
  the person presses Keep. These runs are never traced to Langfuse, and
  nothing said here reaches Aquila's memory.
- Grow: hopes, goals, habits and prayers to grow into (`refuge_seeds`), with
  the days a habit or prayer was tended (`refuge_checkins`).
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
from app.cave import _now
from app.days import parse_today
from app.db import get_supabase
from app.one_another import _db, carried_summary
from app.prayers import normalize_passage

log = logging.getLogger(__name__)

router = APIRouter()

Shape = Literal["blank", "lament", "thanks", "dream"]
SeedKind = Literal["hope", "goal", "habit", "prayer"]
SeedStatus = Literal["growing", "fulfilled", "set_aside"]

# Kinds that are tended day by day rather than worked through in steps.
TENDED_KINDS = ("habit", "prayer")
RHYTHM_DAYS = 7  # how many days of check-ins a seed card shows
MAX_STEPS = 12
TITLE_LENGTH = 60


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


def rhythm(days: list[str], today: date) -> list[bool]:
    """Whether each of the last RHYTHM_DAYS days was tended, oldest first,
    ending today. Shown as dots; never as a streak count."""
    tended = set(days)
    return [(today - timedelta(days=n)).isoformat() in tended for n in range(RHYTHM_DAYS - 1, -1, -1)]


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
    steps: list[str] = Field(default_factory=list, max_length=MAX_STEPS)


class SeedPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)
    passage_ref: str | None = Field(default=None, max_length=120)
    steps: list[Step] | None = Field(default=None, max_length=MAX_STEPS)
    status: SeedStatus | None = None
    outcome_note: str | None = Field(default=None, max_length=2000)


class TendIn(BaseModel):
    today: str | None = None
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
# Grow: hopes, goals, habits and prayers
# ---------------------------------------------------------------------------
_SEED_FIELDS = "id, kind, title, note, passage_ref, steps, status, outcome_note, fulfilled_at, created_at, updated_at"


@router.get("/me/refuge/seeds")
def list_seeds(today: str | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every seed, growing ones first, each tended kind with its last week of days."""
    day = parse_today(today)
    db = get_supabase()
    seeds = _db(lambda: db.table("refuge_seeds").select(_SEED_FIELDS).eq("user_id", user.id).order("created_at", desc=True).execute().data)
    since = (day - timedelta(days=RHYTHM_DAYS - 1)).isoformat()
    checkins = _db(lambda: db.table("refuge_checkins").select("seed_id, day").eq("user_id", user.id).gte("day", since).execute().data)
    for s in seeds:
        days = [c["day"] for c in checkins if c["seed_id"] == s["id"]]
        s["rhythm"] = rhythm(days, day) if s["kind"] in TENDED_KINDS else None
        s["tended_today"] = day.isoformat() in days
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
        "steps": clean_steps(body.steps) if body.kind == "goal" else [],
    }
    return _db(lambda: get_supabase().table("refuge_seeds").insert(row).execute().data[0])


@router.patch("/me/refuge/seeds/{seed_id}")
def tend_seed(seed_id: uuid.UUID, body: SeedPatch, user: AuthUser = Depends(require_user)) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if "passage_ref" in patch:
        patch["passage_ref"] = normalize_passage(patch["passage_ref"])
    if "steps" in patch:
        patch["steps"] = clean_steps(patch["steps"] or [])
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
    rows = _db(lambda: get_supabase().table("refuge_seeds").update(patch).eq("id", str(seed_id)).eq("user_id", user.id).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That isn't here anymore.")
    return rows[0]


@router.post("/me/refuge/seeds/{seed_id}/tend")
def tend_today(seed_id: uuid.UUID, body: TendIn, user: AuthUser = Depends(require_user)) -> dict:
    """Marks a habit or prayer as tended today, or takes that back."""
    day = parse_today(body.today).isoformat()
    db = get_supabase()
    owned = _db(lambda: db.table("refuge_seeds").select("id, kind").eq("id", str(seed_id)).eq("user_id", user.id).limit(1).execute().data)
    if not owned:
        raise HTTPException(status_code=404, detail="That isn't here anymore.")
    if owned[0]["kind"] not in TENDED_KINDS:
        raise HTTPException(status_code=422, detail="Only habits and prayers are tended day by day.")
    if body.tended:
        row = {"seed_id": str(seed_id), "user_id": user.id, "day": day}
        db.table("refuge_checkins").upsert(row, on_conflict="seed_id,day", ignore_duplicates=True).execute()
    else:
        db.table("refuge_checkins").delete().eq("seed_id", str(seed_id)).eq("user_id", user.id).eq("day", day).execute()
    return {"tended_today": body.tended}


@router.delete("/me/refuge/seeds/{seed_id}")
def uproot(seed_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("refuge_seeds").delete().eq("id", str(seed_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
