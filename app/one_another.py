"""Amens: Refuge's wall, where people share a burden or good news without
their name, and others carry it with them (Galatians 6:2, Romans 12:15). It
was called "One another" at first; the module and tables keep that name.

Saying amen is the wall's one reaction. On a burden it means "I prayed for
this", on good news "I'm rejoicing with you", and the count under a post is
its amens.

How a post reaches the wall:
1. The automatic check (`screen`) runs as it's submitted. Links, emails,
   phone numbers and @names are refused outright, so nobody can be found from
   a post. Words that suggest the writer isn't safe aren't posted at all: the
   writer is shown helplines instead (`outcome: "care"`). OpenAI's moderation
   check refuses hateful, sexual, harassing or violent posts.
2. Whatever passes waits as `pending` on the admin desk (/admin/refuge, the
   people in settings.admin_emails), and only appears once someone approves it.
3. A report takes an approved post off the wall (`reported`) and puts it back
   on the desk for another look.

What others can do is deliberately small: say they prayed (or are rejoicing),
send one of a fixed set of kind words (`KIND_WORDS`), or report. Nobody can
write freely to a stranger, and nobody, the desk included, is ever told who
wrote a post. Every /me query here filters by user in code, same rule as
app/cave.py.
"""

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_admin, require_user
from app.care import sounds_unsafe
from app.cave import _db_call, _now
from app.config import settings
from app.db import get_supabase
from app.retrieval import lookup_by_reference, parse_reference

log = logging.getLogger(__name__)

router = APIRouter()

PostKind = Literal["burden", "rejoice"]

SETUP_HINT = (
    "Refuge isn't set up on the database yet. Run supabase/migrations/20261110_refuge.sql "
    "in the Supabase SQL editor."
)

MAX_POST_LENGTH = 280
POSTS_PER_DAY = 3
WALL_DAYS = 30  # how long an approved post stays on the wall
WALL_SIZE = 40

_moderation = OpenAI(api_key=settings.openai_api_key)


def _db(fn):
    return _db_call(fn, SETUP_HINT)


# ---------------------------------------------------------------------------
# Kind words: the only thing anyone can send a stranger. Verses are stored by
# reference and read from the verses table in the reader's translation, like
# every verse on screen.
# ---------------------------------------------------------------------------
KIND_WORDS: dict[str, dict] = {
    "not-alone": {"for": "burden", "text": "You're not alone in this."},
    "praying": {"for": "burden", "text": "I prayed for you today, and I'll pray again tomorrow."},
    "god-sees": {"for": "burden", "text": "God sees you, even here."},
    "carried": {"for": "burden", "text": "Hold on. You're being carried more than you know."},
    "rest": {"for": "burden", "ref": "Matthew 11:28"},
    "with-you": {"for": "burden", "ref": "Isaiah 41:10"},
    "near": {"for": "burden", "ref": "Psalm 34:18"},
    "rejoicing": {"for": "rejoice", "text": "Rejoicing with you!"},
    "thank-god": {"for": "rejoice", "text": "Thank God for this. It made my day."},
    "keep-going": {"for": "rejoice", "text": "So glad for you. Keep going."},
    "this-day": {"for": "rejoice", "ref": "Psalm 118:24"},
    "great-things": {"for": "rejoice", "ref": "Psalm 126:3"},
    "every-good-gift": {"for": "rejoice", "ref": "James 1:17"},
}


@lru_cache(maxsize=256)
def _verse_text(ref: str, translation: str) -> str | None:
    parsed = parse_reference(ref)
    verses = lookup_by_reference(parsed, translation) if parsed else []
    return " ".join(v.text for v in verses) or None


def kind_word(choice: str, translation: str | None) -> dict | None:
    """One kind word ready to show: its text, and for a verse its reference
    and the translation it was read from. None if it isn't a known choice."""
    word = KIND_WORDS.get(choice)
    if not word:
        return None
    if "text" in word:
        return {"id": choice, "text": word["text"]}
    translation = (translation or settings.default_translation).upper()
    try:
        text = _verse_text(word["ref"], translation)
    except Exception:
        log.warning("couldn't read %s for a kind word", word["ref"], exc_info=True)
        text = None
    if not text:
        return None
    return {"id": choice, "text": text, "ref": word["ref"], "translation": translation}


# ---------------------------------------------------------------------------
# The automatic check
# ---------------------------------------------------------------------------
_LINK_RE = re.compile(r"(https?://|www\.|\b[\w-]+\.(com|org|net|io|co|uk|ng|me|app|ly|info)\b)", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_HANDLE_RE = re.compile(r"(^|\s)@\w{2,}")

# OpenAI moderation categories that keep a post off the wall entirely.
# Violence is left to the desk on purpose: it also catches someone describing
# harm done to them, and that person should reach a reader, not a refusal.
# Self-harm is handled separately: the writer is cared for, not refused.
_REFUSED_CATEGORIES = ("harassment", "hate", "sexual", "illicit")


def contact_details(text: str) -> bool:
    """True when a post would let someone find or contact its writer."""
    return any(r.search(text) for r in (_LINK_RE, _EMAIL_RE, _PHONE_RE, _HANDLE_RE))


def moderate(text: str) -> dict:
    """OpenAI's moderation check, reduced to what the wall needs. Never
    raises: if the check is unavailable the post still goes to the desk, where
    a person reads it anyway, with a note saying the check didn't run."""
    try:
        result = _moderation.moderations.create(model="omni-moderation-latest", input=text).results[0]
    except Exception as err:
        log.warning("moderation check failed", exc_info=True)
        return {"flagged": [], "self_harm_intent": False, "error": type(err).__name__}
    categories = result.categories.model_dump(by_alias=True)
    flagged = sorted(name for name, hit in categories.items() if hit)
    return {
        "flagged": flagged,
        "self_harm_intent": bool(categories.get("self-harm/intent") or categories.get("self-harm/instructions")),
        "error": None,
    }


def screen(text: str, check: dict) -> str:
    """What happens to a post: "care" (the writer may not be safe; don't
    post, show helplines), "refuse" (it can't go on the wall), or "desk" (it
    waits for a person to approve it). Contact details are refused before
    this is reached."""
    if sounds_unsafe(text) or check.get("self_harm_intent"):
        return "care"
    if any(name.split("/")[0] in _REFUSED_CATEGORIES for name in check.get("flagged", [])):
        return "refuse"
    return "desk"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PostIn(BaseModel):
    kind: PostKind = "burden"
    body: str = Field(min_length=1, max_length=MAX_POST_LENGTH)


class KindWordIn(BaseModel):
    choice: str = Field(max_length=40)


class ReportIn(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class ReviewIn(BaseModel):
    action: Literal["approve", "remove"]
    note: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------------------
# Helpers that read the wall
# ---------------------------------------------------------------------------
def _counts(table: str, post_ids: list[str]) -> dict[str, int]:
    if not post_ids:
        return {}
    rows = get_supabase().table(table).select("post_id").in_("post_id", post_ids).execute().data
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["post_id"]] = counts.get(r["post_id"], 0) + 1
    return counts


def _mine(table: str, user: AuthUser, post_ids: list[str]) -> set[str]:
    if not post_ids:
        return set()
    rows = get_supabase().table(table).select("post_id").eq("user_id", user.id).in_("post_id", post_ids).execute().data
    return {r["post_id"] for r in rows}


def _post(post_id: str) -> dict:
    rows = _db(lambda: get_supabase().table("refuge_posts").select("id, user_id, kind, status").eq("id", post_id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    return rows[0]


def _others_post(post_id: uuid.UUID, user: AuthUser) -> dict:
    """An approved post by someone else: the only kind anyone can respond to."""
    post = _post(str(post_id))
    if post["status"] != "approved":
        raise HTTPException(status_code=404, detail="That post isn't on the wall anymore.")
    if post["user_id"] == user.id:
        raise HTTPException(status_code=400, detail="That one's yours.")
    return post


def carried_summary(user: AuthUser) -> dict | None:
    """For Refuge's opening screen: how many people prayed or rejoiced, and
    how many kind words arrived, across what this person shared lately."""
    since = (datetime.now(timezone.utc) - timedelta(days=WALL_DAYS)).isoformat()
    posts = (
        get_supabase().table("refuge_posts").select("id, kind, created_at")
        .eq("user_id", user.id).eq("status", "approved").gte("created_at", since)
        .order("created_at", desc=True).execute().data
    )
    if not posts:
        return None
    ids = [p["id"] for p in posts]
    reactions = sum(_counts("refuge_reactions", ids).values())
    words = sum(_counts("refuge_kind_words", ids).values())
    if not reactions and not words:
        return None
    return {"reactions": reactions, "kind_words": words, "kind": posts[0]["kind"], "latest": posts[0]["created_at"]}


AMENS_WEEK_DAYS = 7


def featured_post(posts: list[dict], amened: set[str]) -> dict | None:
    """The newest post this person hasn't said amen to yet, or None once
    they've said amen to everything. `posts` is newest first."""
    return next((p for p in posts if p["id"] not in amened), None)


def amens_glance(user: AuthUser) -> dict:
    """For the home screen's Amens card: the wall's public side only.

    Refuge promises that what someone keeps or shares there never follows
    them onto another screen, so nothing here is about this person's own
    posts. It's how many amens the whole wall said this week, how many posts
    by other people are still waiting for this person's amen, and the newest
    of those, which is already visible to everyone signed in on the wall.
    """
    db = get_supabase()
    now = datetime.now(timezone.utc)
    week_ago = (now - timedelta(days=AMENS_WEEK_DAYS)).isoformat()
    said_this_week = (
        db.table("refuge_reactions").select("post_id", count="exact")
        .gte("created_at", week_ago).limit(1).execute().count or 0
    )
    since = (now - timedelta(days=WALL_DAYS)).isoformat()
    posts = (
        db.table("refuge_posts").select("id, kind, body")
        .eq("status", "approved").neq("user_id", user.id).gte("created_at", since)
        .order("created_at", desc=True).limit(WALL_SIZE).execute().data
    )
    amened = _mine("refuge_reactions", user, [p["id"] for p in posts])
    post = featured_post(posts, amened)
    if post:
        post = {**post, "amens": _counts("refuge_reactions", [post["id"]]).get(post["id"], 0)}
    return {
        "this_week": said_this_week,
        "waiting": sum(1 for p in posts if p["id"] not in amened),
        "post": post,
    }


# ---------------------------------------------------------------------------
# /me/refuge: the wall
# ---------------------------------------------------------------------------
@router.get("/me/refuge/wall")
def wall(translation: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """Approved posts by other people from the last month, newest first, and
    everything this person has shared, with what came back to them."""
    db = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=WALL_DAYS)).isoformat()
    others = _db(lambda: (
        db.table("refuge_posts").select("id, kind, body, created_at")
        .eq("status", "approved").neq("user_id", user.id).gte("created_at", since)
        .order("created_at", desc=True).limit(WALL_SIZE).execute().data
    ))
    ids = [p["id"] for p in others]
    reacted, worded, counts = _mine("refuge_reactions", user, ids), _mine("refuge_kind_words", user, ids), _counts("refuge_reactions", ids)
    for p in others:
        p["reactions"] = counts.get(p["id"], 0)
        p["reacted"] = p["id"] in reacted
        p["sent_kind_word"] = p["id"] in worded

    mine = _db(lambda: (
        db.table("refuge_posts").select("id, kind, body, status, created_at")
        .eq("user_id", user.id).order("created_at", desc=True).limit(20).execute().data
    ))
    mine_ids = [p["id"] for p in mine]
    mine_counts = _counts("refuge_reactions", mine_ids)
    words = db.table("refuge_kind_words").select("post_id, choice").in_("post_id", mine_ids).execute().data if mine_ids else []
    for p in mine:
        p["reactions"] = mine_counts.get(p["id"], 0)
        p["kind_words"] = [w for w in (kind_word(r["choice"], translation) for r in words if r["post_id"] == p["id"]) if w]
        # The desk's own words never reach the writer, only where it stands.
        p["status"] = {"pending": "waiting", "reported": "waiting", "approved": "shared", "removed": "not_shared"}[p["status"]]
    return {"posts": others, "mine": mine}


@router.get("/me/refuge/kind-words")
def kind_words(kind: PostKind, translation: str | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """The choices offered when sending kind words to a post of this kind."""
    return [w for w in (kind_word(c, translation) for c, word in KIND_WORDS.items() if word["for"] == kind) if w]


@router.post("/me/refuge/posts")
def share(body: PostIn, user: AuthUser = Depends(require_user)) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Write a little first.")
    if contact_details(text):
        raise HTTPException(
            status_code=422,
            detail="Take out any links, emails, phone numbers or @names, so nobody can find you from it.",
        )
    db = get_supabase()
    since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    recent = _db(lambda: db.table("refuge_posts").select("id", count="exact").eq("user_id", user.id).gte("created_at", since).limit(1).execute().count or 0)
    if recent >= POSTS_PER_DAY:
        raise HTTPException(status_code=429, detail="You've shared three things today. Come back tomorrow to share more.")

    check = moderate(text)
    outcome = screen(text, check)
    if outcome == "care":
        # Not posted. The client answers with helplines and a gentle word.
        return {"outcome": "care"}
    if outcome == "refuse":
        raise HTTPException(
            status_code=422,
            detail="This can't go on the wall as it's written. If something is weighing on you, Talk with Aquila or Someone to talk to are both here.",
        )
    row = {"user_id": user.id, "kind": body.kind, "body": text, "status": "pending", "auto_check": check}
    post = _db(lambda: db.table("refuge_posts").insert(row).execute().data[0])
    return {"outcome": "waiting", "post": {"id": post["id"], "kind": post["kind"], "body": post["body"], "created_at": post["created_at"]}}


@router.delete("/me/refuge/posts/{post_id}")
def take_down(post_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("refuge_posts").delete().eq("id", str(post_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


@router.post("/me/refuge/posts/{post_id}/react")
def react(post_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """Say amen: "I prayed for this" on a burden, "Rejoicing with you" on
    good news. Returns the post's amens so far."""
    _others_post(post_id, user)
    db = get_supabase()
    _db(lambda: db.table("refuge_reactions").upsert({"post_id": str(post_id), "user_id": user.id}, on_conflict="post_id,user_id", ignore_duplicates=True).execute())
    return {"reactions": _counts("refuge_reactions", [str(post_id)]).get(str(post_id), 0)}


@router.post("/me/refuge/posts/{post_id}/kind-words")
def send_kind_word(post_id: uuid.UUID, body: KindWordIn, user: AuthUser = Depends(require_user)) -> dict:
    post = _others_post(post_id, user)
    word = KIND_WORDS.get(body.choice)
    if not word or word["for"] != post["kind"]:
        raise HTTPException(status_code=422, detail="Choose one of the kind words offered.")
    row = {"post_id": str(post_id), "user_id": user.id, "choice": body.choice}
    _db(lambda: get_supabase().table("refuge_kind_words").upsert(row, on_conflict="post_id,user_id", ignore_duplicates=True).execute())
    return {"status": "sent"}


@router.post("/me/refuge/posts/{post_id}/report")
def report(post_id: uuid.UUID, body: ReportIn, user: AuthUser = Depends(require_user)) -> dict:
    """Takes the post off the wall straight away and sends it back to the desk."""
    post = _post(str(post_id))
    if post["user_id"] == user.id:
        raise HTTPException(status_code=400, detail="That one's yours. You can take it down instead.")
    db = get_supabase()
    reason = (body.reason or "").strip() or None
    _db(lambda: db.table("refuge_reports").upsert({"post_id": str(post_id), "user_id": user.id, "reason": reason}, on_conflict="post_id,user_id", ignore_duplicates=True).execute())
    if post["status"] == "approved":
        db.table("refuge_posts").update({"status": "reported"}).eq("id", str(post_id)).eq("status", "approved").execute()
    return {"status": "reported"}


# ---------------------------------------------------------------------------
# /admin/refuge: the desk. Never shows who wrote anything.
# ---------------------------------------------------------------------------
def waiting_count() -> int:
    """How many posts are waiting on the desk, for the badge in the menu."""
    return (
        get_supabase().table("refuge_posts").select("id", count="exact")
        .in_("status", ["pending", "reported"]).limit(1).execute().count or 0
    )


@router.get("/admin/refuge")
def desk(admin: AuthUser = Depends(require_admin)) -> dict:
    db = get_supabase()
    rows = _db(lambda: (
        db.table("refuge_posts").select("id, kind, body, status, auto_check, created_at")
        .in_("status", ["pending", "reported"]).order("created_at").limit(100).execute().data
    ))
    ids = [r["id"] for r in rows]
    reports = db.table("refuge_reports").select("post_id, reason, created_at").in_("post_id", ids).execute().data if ids else []
    for r in rows:
        r["reports"] = [{"reason": x["reason"], "created_at": x["created_at"]} for x in reports if x["post_id"] == r["id"]]
    return {
        "pending": [r for r in rows if r["status"] == "pending"],
        "reported": [r for r in rows if r["status"] == "reported"],
    }


@router.post("/admin/refuge/{post_id}")
def review(post_id: uuid.UUID, body: ReviewIn, admin: AuthUser = Depends(require_admin)) -> dict:
    status = "approved" if body.action == "approve" else "removed"
    patch = {"status": status, "review_note": (body.note or "").strip() or None, "reviewed_at": _now()}
    rows = _db(lambda: get_supabase().table("refuge_posts").update(patch).eq("id", str(post_id)).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    return {"status": status}
