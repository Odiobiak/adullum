"""My Cave: the signed-in side of Adullum.

Routes for signing in (/auth/*) and for everything a person keeps here
(/me/*): their conversations, journal, and Aquila's notes about them. Reading
plans have their own module, app/reading_plans.py. Every /me query filters by
the signed-in user's id itself, because the server's Supabase client uses the
service-role key and bypasses RLS (see app/db.py). Never drop the `.eq("user_id", user.id)` from a query
in this file.

`record_turn` also lives here: it is what main.py calls after an answer has
been sent, to save the exchange and let Aquila take notes.
"""

import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field
from supabase_auth.errors import AuthError

from app import auth, memory
from app.auth import AuthUser, require_user
from app.config import settings
from app.db import get_supabase

log = logging.getLogger(__name__)

router = APIRouter()

Mood = Literal["grief", "joy", "waiting", "decision", "gratitude", "doubt", "peace", "longing"]

_SETUP_HINT = (
    "My Cave isn't set up on the database yet. Run supabase/migrations/20261104_my_cave.sql "
    "in the Supabase SQL editor."
)


def _db_call(fn, setup_hint: str = _SETUP_HINT):
    """Runs a query, turning a missing table (migration not applied yet) into
    a clear 503 instead of an opaque 500."""
    try:
        return fn()
    except APIError as err:
        if err.code in ("42P01", "PGRST205", "42703"):
            raise HTTPException(status_code=503, detail=setup_hint) from err
        raise


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redirect_to(request: Request) -> str:
    """Where a magic link should land: back on this same site. Supabase only
    honors it if the URL is in the project's Auth > URL Configuration list."""
    return str(request.base_url).rstrip("/") + "/"


# ---------------------------------------------------------------------------
# /auth
# ---------------------------------------------------------------------------
# A light shape check only. Supabase Auth is the real judge of an address,
# and pydantic's EmailStr would pull in email-validator for little gain.
Email = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=254)


class PasswordAuth(BaseModel):
    email: str = Email
    password: str = Field(min_length=6)


class SignupBody(PasswordAuth):
    display_name: str | None = Field(default=None, max_length=60)


class EmailOnly(BaseModel):
    email: str = Email
    display_name: str | None = Field(default=None, max_length=60)


class EmailCode(BaseModel):
    email: str = Email
    code: str = Field(min_length=6, max_length=10)


class RefreshBody(BaseModel):
    refresh_token: str


def _auth_call(fn):
    try:
        return fn()
    except AuthError as err:
        raise HTTPException(status_code=400, detail=auth.auth_error_message(err)) from err


@router.get("/auth/providers")
def providers() -> dict:
    """Which optional sign-in buttons the client should show."""
    return {"google": settings.auth_google_enabled}


@router.get("/auth/google")
def google(request: Request) -> RedirectResponse:
    if not settings.auth_google_enabled:
        raise HTTPException(status_code=404, detail="Google sign-in isn't turned on.")
    return RedirectResponse(auth.google_authorize_url(_redirect_to(request)))


def _clean_name(name: str | None) -> str | None:
    name = (name or "").strip()
    return name or None


@router.post("/auth/signup")
def signup(body: SignupBody, request: Request) -> dict:
    name = _clean_name(body.display_name)
    session = _auth_call(lambda: auth.sign_up(body.email, body.password, _redirect_to(request), name))
    if session is None:
        return {"status": "confirm_email"}
    return {"status": "signed_in", "session": session}


@router.post("/auth/signin")
def signin(body: PasswordAuth) -> dict:
    return {"status": "signed_in", "session": _auth_call(lambda: auth.sign_in_password(body.email, body.password))}


@router.post("/auth/magic-link")
def magic_link(body: EmailOnly, request: Request) -> dict:
    _auth_call(lambda: auth.send_magic_link(body.email, _redirect_to(request), _clean_name(body.display_name)))
    return {"status": "sent"}


@router.post("/auth/verify")
def verify(body: EmailCode) -> dict:
    return {"status": "signed_in", "session": _auth_call(lambda: auth.verify_email_code(body.email, body.code.strip()))}


@router.post("/auth/refresh")
def refresh(body: RefreshBody) -> dict:
    try:
        return {"session": auth.refresh(body.refresh_token)}
    except AuthError as err:
        raise HTTPException(status_code=401, detail="Your session ended. Please sign in again.") from err


# ---------------------------------------------------------------------------
# /me: profile
# ---------------------------------------------------------------------------
class ProfilePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=60)
    preferred_translation: str | None = None
    memory_enabled: bool | None = None


def _ensure_profile(user: AuthUser) -> dict:
    db = get_supabase()
    rows = _db_call(lambda: db.table("profiles").select("*").eq("id", user.id).limit(1).execute().data)
    if rows:
        return rows[0]
    default_name = user.display_name or (user.email or "friend").split("@")[0].replace(".", " ").title()
    row = {"id": user.id, "display_name": default_name}
    return _db_call(lambda: db.table("profiles").upsert(row).execute().data[0])


@router.get("/me")
def me(user: AuthUser = Depends(require_user)) -> dict:
    profile = _ensure_profile(user)
    db = get_supabase()

    def count(table: str) -> int:
        return db.table(table).select("id", count="exact").eq("user_id", user.id).limit(1).execute().count or 0

    counts = _db_call(
        lambda: {
            "journal": count("journal_entries"),
            "sessions": count("chat_sessions"),
            "memories": count("user_memories"),
            "plans": count("reading_plans"),
        }
    )
    return {"user": {"id": user.id, "email": user.email}, "profile": profile, "counts": counts}


@router.patch("/me")
def update_me(body: ProfilePatch, user: AuthUser = Depends(require_user)) -> dict:
    _ensure_profile(user)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return _ensure_profile(user)
    patch["updated_at"] = _now()
    return _db_call(lambda: get_supabase().table("profiles").update(patch).eq("id", user.id).execute().data[0])


# ---------------------------------------------------------------------------
# /me/sessions: past conversations
# ---------------------------------------------------------------------------
@router.get("/me/sessions")
def list_sessions(user: AuthUser = Depends(require_user)) -> list[dict]:
    return _db_call(
        lambda: get_supabase()
        .table("chat_sessions")
        .select("id, title, created_at, updated_at")
        .eq("user_id", user.id)
        .order("updated_at", desc=True)
        .limit(50)
        .execute()
        .data
    )


def _own_session(session_id: str, user: AuthUser) -> dict:
    rows = _db_call(
        lambda: get_supabase()
        .table("chat_sessions")
        .select("id, title, created_at")
        .eq("id", session_id)
        .eq("user_id", user.id)
        .limit(1)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return rows[0]


@router.get("/me/sessions/{session_id}")
def get_session(session_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    session = _own_session(str(session_id), user)
    messages = _db_call(
        lambda: get_supabase()
        .table("chat_messages")
        .select("role, content, citations, followups, created_at")
        .eq("session_id", str(session_id))
        .order("id")
        .execute()
        .data
    )
    return {**session, "messages": messages}


@router.delete("/me/sessions/{session_id}")
def delete_session(session_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _own_session(str(session_id), user)
    _db_call(lambda: get_supabase().table("chat_sessions").delete().eq("id", str(session_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# /me/journal
# ---------------------------------------------------------------------------
class CitationIn(BaseModel):
    book: str
    chapter: int
    verse: int
    translation: str


class JournalIn(BaseModel):
    question: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=12000)
    passage_ref: str | None = Field(default=None, max_length=120)
    verse_text: str | None = Field(default=None, max_length=2000)
    citations: list[CitationIn] = []
    reflection: str = Field(default="", max_length=8000)
    mood: Mood | None = None
    tags: list[str] = Field(default=[], max_length=12)
    session_id: uuid.UUID | None = None


class JournalPatch(BaseModel):
    reflection: str | None = Field(default=None, max_length=8000)
    mood: Mood | None = None
    tags: list[str] | None = Field(default=None, max_length=12)


_JOURNAL_FIELDS = "id, question, answer, passage_ref, verse_text, citations, reflection, mood, tags, session_id, created_at, updated_at"


def _clean_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tags:
        t = t.strip().lstrip("#").lower()[:30]
        if t and t not in seen:
            seen.append(t)
    return seen


def _journal_memory_text(entry: dict) -> str:
    """What Aquila keeps from a journal entry: where they were and what they
    wrote, short enough to sit alongside a question in a prompt."""
    where = entry.get("passage_ref") or (entry.get("question") or "")[:80]
    mood = f", in a season of {entry['mood']}" if entry.get("mood") else ""
    reflection = (entry.get("reflection") or "").strip().replace("\n", " ")
    if len(reflection) > 280:
        reflection = reflection[:277] + "..."
    return f'They journaled on {where}{mood}, writing: "{reflection}"'


def _remember_journal(user: AuthUser, entry: dict, *, replace: bool = False) -> None:
    """Keep Aquila's note about a journal entry in step with what it says.

    With `replace`, the old note is deleted first, so Aquila remembers what
    the entry says now rather than every draft of it. A new note is written
    only when the entry has a reflection and the person has memory switched
    on; with it off, editing an entry still clears the note it used to have.
    """
    if replace:
        get_supabase().table("user_memories").delete().eq("journal_id", entry["id"]).eq("user_id", user.id).execute()
    if (entry.get("reflection") or "").strip() and memory.memory_enabled(user.id):
        memory.store_note(user.id, _journal_memory_text(entry), kind="journal", journal_id=entry["id"])


@router.get("/me/journal")
def list_journal(mood: Mood | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    def run():
        q = get_supabase().table("journal_entries").select(_JOURNAL_FIELDS).eq("user_id", user.id)
        if mood:
            q = q.eq("mood", mood)
        return q.order("created_at", desc=True).limit(100).execute().data

    return _db_call(run)


@router.post("/me/journal")
def create_journal(body: JournalIn, user: AuthUser = Depends(require_user)) -> dict:
    row = body.model_dump(mode="json")
    row["tags"] = _clean_tags(body.tags)
    row["user_id"] = user.id
    if row.get("session_id"):
        # Only link a conversation the person actually owns, otherwise just drop the link.
        owned = get_supabase().table("chat_sessions").select("id").eq("id", row["session_id"]).eq("user_id", user.id).execute().data
        if not owned:
            row["session_id"] = None
    entry = _db_call(lambda: get_supabase().table("journal_entries").insert(row).execute().data[0])
    _remember_journal(user, entry)
    return entry


@router.patch("/me/journal/{entry_id}")
def update_journal(entry_id: uuid.UUID, body: JournalPatch, user: AuthUser = Depends(require_user)) -> dict:
    patch = body.model_dump(exclude_unset=True)
    if "tags" in patch and patch["tags"] is not None:
        patch["tags"] = _clean_tags(patch["tags"])
    patch["updated_at"] = _now()
    rows = _db_call(
        lambda: get_supabase().table("journal_entries").update(patch).eq("id", str(entry_id)).eq("user_id", user.id).execute().data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Entry not found")
    entry = rows[0]
    if "reflection" in patch:
        _remember_journal(user, entry, replace=True)
    return entry


@router.delete("/me/journal/{entry_id}")
def delete_journal(entry_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    # user_memories.journal_id cascades, so the note goes with the entry.
    _db_call(lambda: get_supabase().table("journal_entries").delete().eq("id", str(entry_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


@router.get("/me/journal/revisit")
def revisit(user: AuthUser = Depends(require_user)) -> dict:
    """One older entry to gently bring back up on the landing page ("three
    weeks ago you sat with Psalm 42"). Picks among entries at least a week
    old so it never just echoes what was written yesterday."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows = _db_call(
        lambda: get_supabase()
        .table("journal_entries")
        .select(_JOURNAL_FIELDS)
        .eq("user_id", user.id)
        .lte("created_at", cutoff)
        .neq("reflection", "")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
        .data
    )
    return {"entry": random.choice(rows) if rows else None}


# ---------------------------------------------------------------------------
# /me/memories: what Aquila remembers, fully visible and deletable
# ---------------------------------------------------------------------------
@router.get("/me/memories")
def list_memories(user: AuthUser = Depends(require_user)) -> list[dict]:
    return _db_call(
        lambda: get_supabase()
        .table("user_memories")
        .select("id, content, kind, created_at")
        .eq("user_id", user.id)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
        .data
    )


@router.delete("/me/memories/{memory_id}")
def forget(memory_id: int, user: AuthUser = Depends(require_user)) -> dict:
    _db_call(lambda: get_supabase().table("user_memories").delete().eq("id", memory_id).eq("user_id", user.id).execute())
    return {"status": "forgotten"}


@router.delete("/me/memories")
def forget_all(user: AuthUser = Depends(require_user)) -> dict:
    _db_call(lambda: get_supabase().table("user_memories").delete().eq("user_id", user.id).execute())
    return {"status": "forgotten"}


# ---------------------------------------------------------------------------
# After a turn
# ---------------------------------------------------------------------------
def _valid_uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(value)) if value else None
    except ValueError:
        return None


def record_turn(
    user: AuthUser,
    session_id: str | None,
    query: str,
    answer: str,
    citations: list[dict],
    followups: list[str],
) -> None:
    """Saves the exchange to the person's history, then lets Aquila take
    notes. Called once the answer has already been delivered, off the request
    path, and never raises: a history write failing must not surface as an
    error on an answer the person is already reading."""
    sid = _valid_uuid(session_id)
    try:
        db = get_supabase()
        if sid:
            existing = db.table("chat_sessions").select("user_id").eq("id", sid).limit(1).execute().data
            if existing and existing[0]["user_id"] != user.id:
                sid = None  # someone else's id: never write into their conversation
            elif existing:
                db.table("chat_sessions").update({"updated_at": _now()}).eq("id", sid).execute()
            else:
                title = query.strip().replace("\n", " ")
                title = title if len(title) <= 80 else title[:77] + "..."
                db.table("chat_sessions").insert({"id": sid, "user_id": user.id, "title": title}).execute()
        if sid:
            db.table("chat_messages").insert(
                [
                    {"session_id": sid, "role": "user", "content": query},
                    {
                        "session_id": sid,
                        "role": "assistant",
                        "content": answer,
                        "citations": citations,
                        "followups": followups,
                    },
                ]
            ).execute()
    except Exception:
        log.warning("saving conversation failed", exc_info=True)
    memory.remember_turn(user.id, sid, query, answer)
