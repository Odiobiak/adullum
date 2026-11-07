"""The admin desk (#desk): where the people in ADMIN_EMAILS look after the
Amens wall (app/one_another.py). Run supabase/migrations/20261120_admin_desk.sql
once; until then the desk says what to run.

Two ways onto the desk, kept apart because a post can pass one and still
meet the other later:
- the automatic check: a post it wasn't sure of waits as `pending`;
- a report: a post on the wall that someone reported comes off at once
  (`reported`) and waits for another look.
The desk can also take a live post off the wall itself while it looks into
it (`held`).

What the desk does with a post: approve it (or put it back), remove it, or
hold it. Each decision is made and written to the audit trail
(`refuge_moderation_log`) in one database call, `desk_decide`, so the trail
never disagrees with the wall. Reports go on the trail as they come in.

Urgent comes first: a report that someone may be in danger, or a post the
check noticed violence or self-harm in. Either also sends the admins a
notification (`alert_admins`), since those can't wait for someone to happen
to open the desk.

Nobody here is ever shown who wrote a post or who reported one: no select in
this module names `user_id`.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthUser, admin_emails, require_admin
from app.cave import _db_call
from app.db import get_supabase
from app.one_another import REPORT_CATEGORIES, expires_for, lifetime

log = logging.getLogger(__name__)

router = APIRouter()

DESK_HINT = (
    "The admin desk needs a database update. Run supabase/migrations/20261120_admin_desk.sql "
    "in the Supabase SQL editor."
)

QUEUE_STATUSES = ("pending", "reported", "held")
QUEUE_LIMIT = 200
PAGE = 30
ENDING_SOON = timedelta(days=2)
WEEK = timedelta(days=7)

# What the automatic check can notice that makes a post urgent.
URGENT_FLAGS = {"violence", "self-harm"}

NEW_STATUS = {"approve": "approved", "remove": "removed", "hold": "held"}

URGENT_ALERT = {
    "title": "Urgent on the admin desk",
    "body": "A post may mean someone is in danger. It's off the wall and waiting for you.",
    "url": "#desk",
    "tag": "desk-urgent",
}

# Never user_id.
POST_FIELDS = (
    "id, kind, body, status, auto_check, created_at, approved_at, expires_at, "
    "answered_at, answer_note, kept_up, amen_count, kind_word_count"
)
LOG_FIELDS = "id, post_id, action, from_status, to_status, actor_email, note, created_at"


def _desk(fn):
    return _db_call(fn, DESK_HINT)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def check_is_urgent(check: dict | None) -> bool:
    """Whether the automatic check noticed violence or self-harm."""
    flagged = {name.split("/")[0] for name in (check or {}).get("flagged", [])}
    return bool(flagged & URGENT_FLAGS)


def is_urgent(post: dict) -> bool:
    """Whether a post goes to the top of the desk."""
    return check_is_urgent(post.get("auto_check")) or any(r.get("category") == "danger" for r in post.get("reports", []))


def times_put_back(history: list[dict]) -> int:
    """How often the desk has put a post back after a report or a hold, so a
    post that keeps being reported stands out."""
    return sum(1 for e in history if e["action"] == "approve" and e.get("from_status") in ("reported", "held"))


def report_note(category: str, reason: str | None) -> str:
    """A report as one line on the trail."""
    label = REPORT_CATEGORIES.get(category, REPORT_CATEGORIES["other"])
    return f"{label}: {reason}"[:300] if reason else label


def queue_order(post: dict) -> tuple:
    """Urgent first, then whatever has waited longest."""
    return (not post["urgent"], post["created_at"])


# ---------------------------------------------------------------------------
# Reading the desk
# ---------------------------------------------------------------------------
def waiting_count() -> int:
    """How many posts are waiting on the desk, for the badge in the menu."""
    return (
        get_supabase().table("refuge_posts").select("id", count="exact")
        .in_("status", list(QUEUE_STATUSES)).limit(1).execute().count or 0
    )


def _attach_history(posts: list[dict]) -> list[dict]:
    """Gives each post its reports and its entries on the trail, oldest first."""
    ids = [p["id"] for p in posts]
    if not ids:
        return posts
    db = get_supabase()
    reports = _desk(lambda: (
        db.table("refuge_reports").select("post_id, category, reason, created_at")
        .in_("post_id", ids).order("created_at").execute().data
    ))
    trail = _desk(lambda: db.table("refuge_moderation_log").select(LOG_FIELDS).in_("post_id", ids).order("created_at").execute().data)
    for p in posts:
        p["reports"] = [{k: r[k] for k in ("category", "reason", "created_at")} for r in reports if r["post_id"] == p["id"]]
        p["history"] = [e for e in trail if e["post_id"] == p["id"]]
        p["put_back"] = times_put_back(p["history"])
        p["urgent"] = is_urgent(p)
    return posts


def stats(queue: list[dict]) -> dict:
    """The numbers across the top of the desk."""
    db = get_supabase()
    now = datetime.now(timezone.utc)

    def count(query) -> int:
        return query.limit(1).execute().count or 0

    def live():
        return db.table("refuge_posts").select("id", count="exact").eq("status", "approved")

    def by_status(status: str) -> int:
        return sum(1 for p in queue if p["status"] == status)

    return {
        "to_review": len(queue),
        "urgent": sum(1 for p in queue if p["urgent"]),
        "flagged": by_status("pending"),
        "reported": by_status("reported"),
        "held": by_status("held"),
        "on_wall": count(live().gt("expires_at", _iso(now))),
        "ending_soon": count(live().gt("expires_at", _iso(now)).lte("expires_at", _iso(now + ENDING_SOON))),
        "ended_week": count(live().gt("expires_at", _iso(now - WEEK)).lte("expires_at", _iso(now))),
        "decided_week": count(
            db.table("refuge_moderation_log").select("id", count="exact").neq("action", "report").gte("created_at", _iso(now - WEEK))
        ),
    }


@router.get("/admin/refuge")
def queue(admin: AuthUser = Depends(require_admin)) -> dict:
    """Everything waiting for a person: flagged by the check, reported, or
    held. Urgent first, then oldest first."""
    db = get_supabase()
    posts = _desk(lambda: (
        db.table("refuge_posts").select(POST_FIELDS).in_("status", list(QUEUE_STATUSES))
        .order("created_at").limit(QUEUE_LIMIT).execute().data
    ))
    posts = sorted(_attach_history(posts), key=queue_order)
    return {"stats": _desk(lambda: stats(posts)), "queue": posts}


LiveFilter = Literal["all", "ending", "burden", "rejoice", "answered", "kept_up"]


@router.get("/admin/refuge/live")
def on_the_wall(show: LiveFilter = "all", page: int = Query(default=0, ge=0, le=200), admin: AuthUser = Depends(require_admin)) -> dict:
    """What's on the wall now, the soonest to leave first, with where each
    post stands in its time there."""
    now = datetime.now(timezone.utc)
    query = get_supabase().table("refuge_posts").select(POST_FIELDS).eq("status", "approved").gt("expires_at", _iso(now))
    if show == "ending":
        query = query.lte("expires_at", _iso(now + ENDING_SOON))
    elif show in ("burden", "rejoice"):
        query = query.eq("kind", show).is_("answered_at", "null")
    elif show == "answered":
        query = query.not_.is_("answered_at", "null")
    elif show == "kept_up":
        query = query.gt("kept_up", 0)
    rows = _desk(lambda: query.order("expires_at").range(page * PAGE, page * PAGE + PAGE).execute().data)
    posts = _attach_history(rows[:PAGE])
    for p in posts:
        p.update(lifetime(p, now))
    return {"posts": posts, "has_more": len(rows) > PAGE, "page": page}


LogFilter = Literal["all", "approve", "remove", "hold", "report"]


@router.get("/admin/refuge/log")
def trail(action: LogFilter = "all", page: int = Query(default=0, ge=0, le=500), admin: AuthUser = Depends(require_admin)) -> dict:
    """The audit trail, newest first: every decision and every report, with
    the post as it is now (none once its writer deleted it)."""
    query = get_supabase().table("refuge_moderation_log").select(f"{LOG_FIELDS}, post:refuge_posts(id, kind, body, status)")
    if action != "all":
        query = query.eq("action", action)
    rows = _desk(lambda: query.order("created_at", desc=True).range(page * PAGE, page * PAGE + PAGE).execute().data)
    return {"entries": rows[:PAGE], "has_more": len(rows) > PAGE, "page": page}


# ---------------------------------------------------------------------------
# Deciding
# ---------------------------------------------------------------------------
class DecisionIn(BaseModel):
    action: Literal["approve", "remove", "hold"]
    note: str | None = Field(default=None, max_length=300)


@router.post("/admin/refuge/{post_id}")
def decide(post_id: uuid.UUID, body: DecisionIn, admin: AuthUser = Depends(require_admin)) -> dict:
    """Approves (or puts back), removes or holds a post, and records it."""
    db = get_supabase()
    rows = _desk(lambda: db.table("refuge_posts").select("kind, status, approved_at").eq("id", str(post_id)).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    post, status = rows[0], NEW_STATUS[body.action]
    if body.action == "hold" and post["status"] != "approved":
        raise HTTPException(status_code=409, detail="Only a post on the wall can be held.")
    if post["status"] == status:
        return {"status": status}  # someone else on the desk got there first
    params = {
        "target": str(post_id), "new_status": status, "actor": admin.id, "actor_email": admin.email,
        "note": " ".join((body.note or "").split()) or None, "went_up": None, "ends": None,
    }
    # A post going up for the first time starts its time on the wall now; one
    # coming back keeps the time it already had.
    if status == "approved" and not post.get("approved_at"):
        went_up = datetime.now(timezone.utc)
        params["went_up"], params["ends"] = _iso(went_up), _iso(expires_for(post["kind"], went_up))
    if _desk(lambda: db.rpc("desk_decide", params).execute().data) is None:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    return {"status": status}


# ---------------------------------------------------------------------------
# Hooks from the wall. Both run after the person has their answer and never
# raise: a report or a post must never fail because the desk couldn't hear.
# ---------------------------------------------------------------------------
def alert_admins() -> int:
    """Sends the admins one notification that something urgent is waiting.
    Returns how many devices it reached."""
    from app import push  # here, so importing this module stays light

    emails = sorted(admin_emails())
    if not push.configured() or not emails:
        return 0
    try:
        ids = get_supabase().rpc("desk_admin_ids", {"emails": emails}).execute().data or []
        return sum(push.notify_user(admin_id, URGENT_ALERT) for admin_id in ids)
    except Exception:
        log.warning("couldn't alert the admin desk", exc_info=True)
        return 0


def report_received(post_id: str, was: str, category: str, reason: str | None) -> None:
    """Writes a report to the trail and, when someone may be in danger,
    alerts the admins. The reporter is never recorded."""
    try:
        get_supabase().table("refuge_moderation_log").insert({
            "post_id": post_id, "action": "report", "from_status": was,
            "to_status": "reported" if was == "approved" else was, "note": report_note(category, reason),
        }).execute()
    except Exception:
        log.warning("couldn't write a report to the desk's trail", exc_info=True)
    if category == "danger":
        alert_admins()
