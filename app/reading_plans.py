"""Reading plans in My Cave: listing them, shaping one with Aquila, marking
days as read, and letting one go.

The scheduling itself is in app/plan.py. Like everything under /me, every
query here filters by the signed-in user's id in code, because the server's
Supabase client uses the service-role key and bypasses RLS.

Plans shaped with Aquila carry their own title, stored in a column added by
supabase/migrations/20261106_plan_titles.sql. Until that migration runs, a
new plan is saved without its title and shows a generic one instead, rather
than failing to save at all.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app import quota
from app.auth import AuthUser, require_user
from app.cave import _db_call
from app.config import settings
from app.db import get_supabase
from app.hearth import _parse_today, _record_visit
from app.plan import draft_custom_plan, plan_today, serialize_schedule

log = logging.getLogger(__name__)

router = APIRouter()

# Postgres "undefined column" and PostgREST "column not in schema cache".
_MISSING_COLUMN_CODES = ("42703", "PGRST204")


def _plan_summary(row: dict, today) -> dict:
    """A plan as the Bible's Reading plans page shows it: where it stands today plus the
    details the list needs."""
    return {
        **plan_today(row, today),
        "start_date": row["start_date"],
        "translation": row["translation"],
        "overview": row.get("overview") or "",
        "created_at": row.get("created_at"),
    }


def _own_plan(plan_id: str, user: AuthUser) -> dict:
    rows = _db_call(
        lambda: get_supabase()
        .table("reading_plans")
        .select("*")
        .eq("id", plan_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Plan not found")
    return rows[0]


@router.get("/me/plans")
def list_plans(today: str | None = Query(default=None), user: AuthUser = Depends(require_user)) -> list[dict]:
    day = _parse_today(today)
    rows = _db_call(
        lambda: get_supabase()
        .table("reading_plans")
        .select("*")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    return [_plan_summary(row, day) for row in rows]


class BuildPlanBody(BaseModel):
    request: str = Field(min_length=3, max_length=500)
    today: str | None = None
    translation: str | None = None


@router.post("/me/plans/build")
def build_plan(body: BuildPlanBody, user: AuthUser = Depends(require_user)) -> dict:
    """Shape a plan with Aquila from a request in the person's own words, and
    keep it. It starts on their local today."""
    day = _parse_today(body.today)
    quota.spend("question", user.id)
    try:
        plan = draft_custom_plan(body.request, day)
    except ValueError as err:
        raise HTTPException(
            status_code=422,
            detail="Aquila couldn't turn that into a reading plan. Try naming a book, a topic, or how long you'd like it to take.",
        ) from err
    except Exception as err:
        log.warning("building a reading plan failed", exc_info=True)
        raise HTTPException(status_code=502, detail="Aquila couldn't shape a plan just now. Please try again.") from err

    row = {
        "user_id": user.id,
        "start_date": day.isoformat(),
        "days": len(plan.schedule),
        "translation": body.translation or settings.default_translation,
        "overview": plan.overview,
        "schedule": serialize_schedule(plan.schedule),
        "title": plan.title,
    }
    db = get_supabase()
    try:
        inserted = db.table("reading_plans").insert(row).execute().data[0]
    except APIError as err:
        if err.code not in _MISSING_COLUMN_CODES:
            raise
        log.info("reading_plans.title missing (run supabase/migrations/20261106_plan_titles.sql)")
        row.pop("title")
        inserted = _db_call(lambda: db.table("reading_plans").insert(row).execute().data[0])
    return _plan_summary(inserted, day)


@router.delete("/me/plans/{plan_id}")
def delete_plan(plan_id: str, user: AuthUser = Depends(require_user)) -> dict:
    _own_plan(plan_id, user)
    _db_call(lambda: get_supabase().table("reading_plans").delete().eq("id", plan_id).eq("user_id", user.id).execute())
    return {"status": "deleted"}


class ProgressBody(BaseModel):
    day: int
    done: bool
    today: str | None = None


@router.post("/me/plans/{plan_id}/progress")
def plan_progress(plan_id: str, body: ProgressBody, user: AuthUser = Depends(require_user)) -> dict:
    row = _own_plan(plan_id, user)
    if not 1 <= body.day <= int(row["days"]):
        raise HTTPException(status_code=422, detail="That day isn't part of this plan.")
    completed = set(row.get("completed_days") or [])
    if body.done:
        completed.add(body.day)
    else:
        completed.discard(body.day)
    try:
        row = (
            get_supabase()
            .table("reading_plans")
            .update({"completed_days": sorted(completed)})
            .eq("id", plan_id)
            .eq("user_id", user.id)
            .execute()
            .data[0]
        )
    except Exception as err:
        raise HTTPException(
            status_code=503,
            detail="Plan progress isn't set up yet. Run supabase/migrations/20261105_hearth.sql in Supabase.",
        ) from err
    day = _parse_today(body.today)
    if body.done:
        _record_visit(user, day)
    return _plan_summary(row, day)
