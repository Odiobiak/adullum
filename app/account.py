"""A person's whole account: take everything with them, or close it for good.

- `GET /me/export` is one zip: a JSON file per kind of thing they keep, their
  sermon photos, and a README saying what each file is.
- `DELETE /me` closes the account. They confirm by typing their email.

Deleting the auth user is what removes almost everything: every personal
table references `auth.users` with `on delete cascade`. Two things don't
cascade and are cleared here: reading plans (`reading_plans.user_id` is
`on delete set null`, so they'd be left behind without an owner) and sermon
photos in storage. Both are gathered before the account goes, because once
it's gone the plans no longer say whose they were, and removed after, so a
failure to delete the account never costs the person their plans or photos.

Like every /me route, each query filters by `user.id` in code, since the
service-role client bypasses RLS.
"""

import io
import json
import logging
import zipfile
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app import auth
from app.auth import AuthUser, require_user
from app.db import get_supabase
from app.sermons import BUCKET

log = logging.getLogger(__name__)

router = APIRouter()

# Every table that holds what a person keeps, filtered by `user_id`, with a
# line for the export's README. Chat messages and the profile are read
# separately: messages hang off sessions, and the profile's key is `id`.
EXPORT_TABLES: dict[str, str] = {
    "chat_sessions": "Your conversations with Aquila (the messages are in chat_messages.json)",
    "journal_entries": "Your journal",
    "reflections": "Your reflections",
    "user_memories": "What Aquila remembered about you",
    "prayers": "Your prayer list",
    "prayer_days": "The days you marked as prayed",
    "fasts": "Your fasts",
    "declarations": "Declarations you kept",
    "verse_notes": "Your notes on verses",
    "verse_highlights": "Your highlights",
    "saved_items": "Things you saved",
    "memory_verses": "Verses you were memorizing (from before Saved)",
    "reading_plans": "Your reading plans",
    "sermon_notes": "Your sermon notes (photos are in sermon-photos/)",
    "churches": "Churches you added",
    "reminders": "Reminders you set",
    "refuge_writings": "What you kept from Write it out",
    "refuge_talks": "Talks with Aquila you kept in Refuge",
    "refuge_seeds": "Your goals and habits (Pebbles)",
    "refuge_checkins": "Your check-ins on goals and habits",
    "refuge_posts": "What you shared on the Amens wall",
    "refuge_reactions": "Amens you said",
    "refuge_kind_words": "Kind words you sent",
    "refuge_reports": "Posts you reported",
    "user_activity": "The days you used Adullam (for your streak)",
}

# Internal columns with no meaning outside Adullam (search vectors).
_DROPPED_COLUMNS = {"embedding"}
_PAGE = 1000
_MISSING = ("42P01", "PGRST205")  # a table whose migration hasn't run


class DeleteAccount(BaseModel):
    confirm: str = Field(max_length=254, description="The account's email, typed to confirm.")


def _rows(table: str, column: str, value: str) -> list[dict]:
    """Every row where `column` is `value`, a page at a time (PostgREST stops
    at 1,000). A table that doesn't exist yet reads as empty."""
    db = get_supabase()
    rows: list[dict] = []
    try:
        while True:
            page = db.table(table).select("*").eq(column, value).range(len(rows), len(rows) + _PAGE - 1).execute().data
            rows += page
            if len(page) < _PAGE:
                break
    except APIError as err:
        if err.code in _MISSING:
            return []
        raise
    return [{k: v for k, v in row.items() if k not in _DROPPED_COLUMNS} for row in rows]


def _chat_messages(session_ids: list[str]) -> list[dict]:
    db = get_supabase()
    messages: list[dict] = []
    for start in range(0, len(session_ids), 100):
        chunk = session_ids[start:start + 100]
        messages += db.table("chat_messages").select("*").in_("session_id", chunk).order("id").limit(10_000).execute().data
    return messages


def _photo_paths(user_id: str) -> list[str]:
    """Every file under the person's folder in the sermon photos bucket
    (`<user id>/<note id>/<file>`), including any a note no longer points at."""
    bucket = get_supabase().storage.from_(BUCKET)
    paths: list[str] = []
    try:
        for folder in bucket.list(user_id, {"limit": 1000}):
            prefix = f"{user_id}/{folder['name']}"
            if folder.get("id"):  # a file sitting directly in the folder
                paths.append(prefix)
                continue
            paths += [f"{prefix}/{f['name']}" for f in bucket.list(prefix, {"limit": 1000}) if f.get("id")]
    except Exception:
        log.warning("couldn't list sermon photos for an account", exc_info=True)
    return paths


def _readme(user: AuthUser, counts: dict[str, int]) -> str:
    lines = [
        "Everything you keep in Adullam",
        f"Exported {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC for {user.email}",
        "",
        "Each .json file is a list of records. Dates are in UTC.",
        "",
        "profile.json: Your profile and settings",
        f"chat_messages.json ({counts.get('chat_messages', 0)}): The messages in your conversations",
    ]
    lines += [f"{table}.json ({counts.get(table, 0)}): {about}" for table, about in EXPORT_TABLES.items()]
    return "\n".join(lines) + "\n"


@router.get("/me/export")
def export_account(user: AuthUser = Depends(require_user)) -> Response:
    """Everything the person keeps here, as one zip they can download."""
    data: dict[str, object] = {"profile": _rows("profiles", "id", user.id)[:1]}
    for table in EXPORT_TABLES:
        data[table] = _rows(table, "user_id", user.id)
    data["chat_messages"] = _chat_messages([s["id"] for s in data["chat_sessions"]])
    counts = {name: len(rows) for name, rows in data.items()}

    buffer = io.BytesIO()
    bucket = get_supabase().storage.from_(BUCKET)
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", _readme(user, counts))
        for name, rows in data.items():
            archive.writestr(f"{name}.json", json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        for path in _photo_paths(user.id):
            try:
                archive.writestr(f"sermon-photos/{path.split('/', 1)[1]}", bucket.download(path))
            except Exception:
                log.warning("couldn't add a sermon photo to an export", exc_info=True)

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''Adullam%20export%20{stamp}.zip"},
    )


@router.delete("/me")
def delete_account(body: DeleteAccount, user: AuthUser = Depends(require_user)) -> dict:
    """Closes the account and removes everything in it. Not reversible."""
    if not user.email or body.confirm.strip().lower() != user.email.lower():
        raise HTTPException(status_code=422, detail="Type your email address exactly to confirm.")

    db = get_supabase()
    plan_ids = [p["id"] for p in _rows("reading_plans", "user_id", user.id)]
    photos = _photo_paths(user.id)

    try:
        db.auth.admin.delete_user(user.id)
    except Exception as err:
        log.exception("couldn't delete an account")
        raise HTTPException(status_code=502, detail="Your account couldn't be closed just now. Nothing was removed. Please try again.") from err
    auth.forget_user(user.id)

    # The account is gone; what's left can't be reached by anyone, so a
    # failure below is logged for the operator rather than shown to the person.
    try:
        for start in range(0, len(plan_ids), 100):
            db.table("reading_plans").delete().in_("id", plan_ids[start:start + 100]).execute()
    except Exception:
        log.exception("account deleted, but %d reading plans were left behind", len(plan_ids))
    try:
        for start in range(0, len(photos), 100):
            db.storage.from_(BUCKET).remove(photos[start:start + 100])
    except Exception:
        log.exception("account deleted, but %d sermon photos were left behind", len(photos))
    return {"ok": True}
