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
2. A post the automatic check is clear about goes up straight away
   (`approved`, with `approved_at`). One it isn't sure of (a moderation flag,
   or the check not running at all) waits as `pending` on the admin desk
   (app/desk.py, the people in settings.admin_emails) until someone
   approves it. settings.amens_auto_approve turns going up straight away off,
   so that every post waits for the desk again.
3. A report takes an approved post off the wall (`reported`) at once and puts
   it back on the desk for another look, with why (`REPORT_CATEGORIES`). Each
   person can do that to `REPORT_TAKEDOWNS_PER_DAY` posts a day; past that,
   their report still reaches the desk but the post stays up until a person
   looks, so one account can't empty the wall. The desk can also hold a live
   post off the wall while it looks (`held`).

How long a post stays (supabase/migrations/20261117_amens_lifetimes.sql): a
prayer request two weeks from when it goes up, and its writer can keep it up
two weeks more at a time, up to two months (`keep_up`); good news a week; a
prayer request marked answered (`answered`) five more days, shown as good news
with a line on how. Then it leaves the wall for everyone else. The writer's
own copy, with every amen and kind word, never goes. `expires_at` holds when.

How the wall reaches people (supabase/migrations/20261116_amens_at_scale.sql):
there are no followers and no feeds. Each person's wall is `amens_wall`: posts
by others from the last month, the ones they haven't said amen to first, then
those with the fewest amens, in a shuffle of their own, a page at a time, so
prayer spreads across every request instead of piling onto the newest. Counts
live on the post (`amen_count`, kept by a trigger), amens per day in
`refuge_amen_days`, and the home notice counts what's gone up since someone
last opened the wall (`refuge_wall_visits`). Once a day, in their evening, a
writer with new amens is sent one quiet notification (`run_digest`).

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
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from openai import OpenAI
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_user
from app.care import sounds_unsafe
from app.cave import _db_call, _now
from app.config import settings
from app.db import gather, get_supabase
from app.retrieval import lookup_by_reference, parse_reference

log = logging.getLogger(__name__)

router = APIRouter()

PostKind = Literal["burden", "rejoice"]

SETUP_HINT = (
    "Refuge isn't set up on the database yet. Run supabase/migrations/20261110_refuge.sql "
    "in the Supabase SQL editor."
)

MAX_POST_LENGTH = 280
POSTS_PER_DAY = 5
WALL_DAYS = 30  # Refuge's "came back to you" looks this far back

# How long a post stays on the wall, from when it goes up.
LIFETIME_DAYS = {"burden": 14, "rejoice": 7}
KEEP_UP_DAYS = 14       # each "keep it up" adds this much
KEEP_UP_WINDOW_DAYS = 4  # offered once a request is this close to leaving (or has left)
MAX_DAYS_UP = 60        # a request never stays longer than this in all
ANSWERED_DAYS = 5       # an answered prayer stays this much longer, as good news
WALL_PAGE = 24  # posts per page of someone's wall
NEW_DAYS = 7    # the home notice counts what's new since the last look, or this week

# The daily digest: at most one every DIGEST_GAP, counting what came back
# since the last (DIGEST_LOOK_BACK at most), sent in the writer's evening.
DIGEST_GAP = timedelta(hours=20)
DIGEST_LOOK_BACK = timedelta(days=2)
DIGEST_HOURS = range(18, 22)  # 6pm to 9:59pm where they are

# The wall's later parts read tables and functions from a later migration.
AMENS_HINT = (
    "Amens needs a database update. Run supabase/migrations/20261116_amens_at_scale.sql "
    "in the Supabase SQL editor."
)

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
@lru_cache(maxsize=256)
def _verse_text(ref: str, translation: str) -> str | None:
    """A kind word's verse. Kept in memory, since the words never change and
    the wall shows the same few on every visit."""
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


def goes_up_now(check: dict) -> bool:
    """Whether a post the screen sent on can go on the wall straight away:
    the check ran, it flagged nothing at all, and going up straight away is
    on. Anything else waits for a person on the desk."""
    return settings.amens_auto_approve and not check.get("error") and not check.get("flagged")


def _stamp(value) -> datetime | None:
    if not value:
        return None
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def expires_for(kind: str, went_up: datetime) -> datetime:
    """When a post that went up at `went_up` leaves the wall."""
    return went_up + timedelta(days=LIFETIME_DAYS[kind])


def kept_up_until(post: dict, now: datetime) -> datetime | None:
    """Where "keep it up" would move a prayer request's end: two weeks on from
    today or from its current end, whichever is later, never past two months
    from when it went up. None when it can't be kept up now: it isn't a live
    or recently ended request, it's been answered, it isn't near its end yet,
    or it's already at two months."""
    went_up, ends = _stamp(post.get("approved_at")), _stamp(post.get("expires_at"))
    if post.get("kind") != "burden" or post.get("status") != "approved" or post.get("answered_at") or not went_up or not ends:
        return None
    if ends - now > timedelta(days=KEEP_UP_WINDOW_DAYS):
        return None
    cap = went_up + timedelta(days=MAX_DAYS_UP)
    until = min(max(ends, now) + timedelta(days=KEEP_UP_DAYS), cap)
    return until if until > max(ends, now) else None


def on_wall(post: dict, now: datetime) -> bool:
    ends = _stamp(post.get("expires_at"))
    return post.get("status") == "approved" and bool(ends) and ends > now


def shown_kind(post: dict) -> str:
    """How a post reads on the wall: an answered prayer reads as good news."""
    return "rejoice" if post.get("answered_at") else post["kind"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class PostIn(BaseModel):
    kind: PostKind = "burden"
    body: str = Field(min_length=1, max_length=MAX_POST_LENGTH)


class KindWordIn(BaseModel):
    choice: str = Field(max_length=40)


# Why someone reported a post, shown on the report sheet and the admin desk
# (app/desk.py). "danger" goes to the top of the desk and alerts the admins.
REPORT_CATEGORIES = {
    "danger": "Someone may be in danger",
    "identifies": "It names or could identify someone",
    "unkind": "It's hurtful or hateful",
    "spam": "It's spam or selling something",
    "other": "Something else",
}


# How many reports a day one person can make that take a post off the wall at
# once. Past that a report still goes to the desk (app/desk.py shows it as
# "Reported, still up"), but the post stays up until someone there looks. The
# reporter is told the same either way, so the limit can't be felt for.
REPORT_TAKEDOWNS_PER_DAY = 3


class ReportIn(BaseModel):
    category: Literal["danger", "identifies", "unkind", "spam", "other"] = "other"
    reason: str | None = Field(default=None, max_length=300)


# ---------------------------------------------------------------------------
# Helpers that read the wall
# ---------------------------------------------------------------------------
def _rpc(name: str, params: dict):
    """Calls one of the wall's database functions (see the migration above)."""
    return _db_call(lambda: get_supabase().rpc(name, params).execute().data, AMENS_HINT)


def _ago(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _since_last_look(user: AuthUser) -> str:
    """When the person last opened the wall, or a week ago if longer."""
    rows = get_supabase().table("refuge_wall_visits").select("seen_at").eq("user_id", user.id).limit(1).execute().data
    week_ago = _ago(days=NEW_DAYS)
    return max(rows[0]["seen_at"], week_ago) if rows else week_ago


def _post(post_id: str) -> dict:
    rows = _db(lambda: (
        get_supabase().table("refuge_posts").select("id, user_id, kind, status, approved_at, expires_at, answered_at")
        .eq("id", post_id).limit(1).execute().data
    ))
    if not rows:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    return rows[0]


def _others_post(post_id: uuid.UUID, user: AuthUser) -> dict:
    """A post by someone else that's on the wall now: the only kind anyone
    can respond to."""
    post = _post(str(post_id))
    if not on_wall(post, datetime.now(timezone.utc)):
        raise HTTPException(status_code=404, detail="That post isn't on the wall anymore.")
    if post["user_id"] == user.id:
        raise HTTPException(status_code=400, detail="That one's yours.")
    return post


def carried_summary(user: AuthUser) -> dict | None:
    """For Refuge's opening screen: how many people prayed or rejoiced, and
    how many kind words arrived, across what this person shared lately."""
    posts = (
        get_supabase().table("refuge_posts").select("kind, created_at, amen_count, kind_word_count")
        .eq("user_id", user.id).eq("status", "approved").gte("created_at", _ago(days=WALL_DAYS))
        .order("created_at", desc=True).limit(50).execute().data
    )
    if not posts:
        return None
    reactions = sum(p.get("amen_count") or 0 for p in posts)
    words = sum(p.get("kind_word_count") or 0 for p in posts)
    if not reactions and not words:
        return None
    return {"reactions": reactions, "kind_words": words, "kind": posts[0]["kind"], "latest": posts[0]["created_at"]}


AMENS_WEEK_DAYS = 7


def featured_post(posts: list[dict], amened: set[str]) -> dict | None:
    """The newest post this person hasn't said amen to yet, or None once
    they've said amen to everything. `posts` is newest first."""
    return next((p for p in posts if p["id"] not in amened), None)


def amens_glance(user: AuthUser) -> dict:
    """For the home screen's Amens notice: the wall's public side only.

    Refuge promises that what someone keeps or shares there never follows
    them onto another screen, so nothing here is about this person's own
    posts. It's how many amens the whole wall said this week, how many posts
    by other people have gone up since they last looked that they haven't
    said amen to, and the first post their own wall would show them.
    """
    week_start = (datetime.now(timezone.utc).date() - timedelta(days=AMENS_WEEK_DAYS - 1)).isoformat()
    days, waiting, first = gather(
        lambda: get_supabase().table("refuge_amen_days").select("amens").gte("day", week_start).execute().data,
        lambda: _rpc("amens_waiting", {"viewer": user.id, "since": _since_last_look(user)}) or 0,
        lambda: _rpc("amens_wall", {"viewer": user.id, "since": _ago(days=MAX_DAYS_UP), "max_posts": 1, "skip": 0}),
    )
    post = featured_post(first, {p["id"] for p in first if p.get("reacted")})
    return {
        "this_week": sum(d["amens"] for d in days),
        "waiting": waiting,
        "post": {"id": post["id"], "kind": post["kind"], "body": post["body"], "amens": post.get("amen_count") or 0} if post else None,
    }


# ---------------------------------------------------------------------------
# /me/refuge: the wall
# ---------------------------------------------------------------------------
def lifetime(post: dict, now: datetime) -> dict:
    """Where one of the writer's own posts stands on the wall: whether it's
    up, how many days it has left, and whether it can be kept up now."""
    up = on_wall(post, now)
    ends = _stamp(post.get("expires_at"))
    return {
        "on_wall": up,
        "days_left": max(0, -((now - ends) // timedelta(days=1))) if up and ends else 0,
        "can_keep_up": kept_up_until(post, now) is not None,
        "answered": bool(post.get("answered_at")),
    }


# Where a post stands, as its writer sees it. Reported and held both read as
# waiting: the writer is never told someone reported it.
WRITER_STATUS = {"pending": "waiting", "reported": "waiting", "held": "waiting", "approved": "shared", "removed": "not_shared"}


def _wall_post(row: dict) -> dict:
    """A post as the wall sends it: never who wrote it."""
    return {
        "id": row["id"], "kind": row["kind"], "body": row["body"], "created_at": row["created_at"],
        "reactions": row.get("amen_count") or 0, "reacted": bool(row.get("reacted")), "sent_kind_word": bool(row.get("sent_kind_word")),
        # An answered prayer reads as good news, with the writer's line on how.
        "answered": bool(row.get("answered_at")), "answer_note": row.get("answer_note"),
    }


@router.get("/me/refuge/wall")
def wall(translation: str | None = None, page: int = Query(default=0, ge=0, le=200), user: AuthUser = Depends(require_user)) -> dict:
    """One page of this person's wall (see `amens_wall` for the order), and on
    the first page everything they've shared, with what came back to them,
    and whether their evening digest is on."""
    db = get_supabase()

    def page_of_wall():
        return _rpc("amens_wall", {"viewer": user.id, "since": _ago(days=MAX_DAYS_UP), "max_posts": WALL_PAGE + 1, "skip": page * WALL_PAGE})

    def shared():
        mine = _db(lambda: (
            db.table("refuge_posts").select("id, kind, body, status, created_at, amen_count, kind_word_count, approved_at, expires_at, answered_at, answer_note")
            .eq("user_id", user.id).order("created_at", desc=True).limit(20).execute().data
        ))
        return mine, (_rpc("kind_word_tally", {"post_ids": [p["id"] for p in mine]}) if mine else [])

    def digest_on():
        try:
            profile = db.table("profiles").select("amens_digest").eq("id", user.id).limit(1).execute().data
            return profile[0].get("amens_digest", True) if profile else True
        except Exception:
            return None  # the setting isn't there yet; the page leaves the switch out

    def opened_now():
        # The wall is open now: what's new on the home notice counts from here.
        db.table("refuge_wall_visits").upsert({"user_id": user.id, "seen_at": _now()}, on_conflict="user_id").execute()

    if page:
        rows = page_of_wall()
    else:
        # The first page brings everything at once: four round trips side by side.
        rows, (mine, tally), digest, _ = gather(page_of_wall, shared, digest_on, opened_now)
    out = {"posts": [_wall_post(r) for r in rows[:WALL_PAGE]], "has_more": len(rows) > WALL_PAGE, "page": page}
    if page:
        return out

    now = datetime.now(timezone.utc)
    for p in mine:
        p["reactions"] = p.pop("amen_count", 0) or 0
        p["kind_word_count"] = p.get("kind_word_count") or 0
        p["kind_words"] = [
            {**w, "count": t["n"]}
            for t in tally if t["post_id"] == p["id"]
            for w in [kind_word(t["choice"], translation)] if w
        ]
        p.update(lifetime(p, now))
        # The desk's own words never reach the writer, only where it stands.
        p["status"] = WRITER_STATUS[p["status"]]
        if p["status"] == "shared" and not p["on_wall"]:
            p["status"] = "ended"
    out["mine"] = mine
    out["digest"] = digest
    return out


@router.get("/me/refuge/kind-words")
def kind_words(kind: PostKind, translation: str | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """The choices offered when sending kind words to a post of this kind."""
    return [w for w in (kind_word(c, translation) for c, word in KIND_WORDS.items() if word["for"] == kind) if w]


@router.post("/me/refuge/posts")
def share(body: PostIn, background: BackgroundTasks, user: AuthUser = Depends(require_user)) -> dict:
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
        raise HTTPException(status_code=429, detail="You've shared five things today. Come back tomorrow to share more.")

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
    goes_up = goes_up_now(check)
    row = {"user_id": user.id, "kind": body.kind, "body": text, "status": "approved" if goes_up else "pending", "auto_check": check}
    if goes_up:
        went_up = datetime.now(timezone.utc)
        row["approved_at"] = went_up.isoformat()
        row["expires_at"] = expires_for(body.kind, went_up).isoformat()
    post = _db(lambda: db.table("refuge_posts").insert(row).execute().data[0])
    from app import desk  # here, since app/desk.py imports this module

    if not goes_up and desk.check_is_urgent(check):
        background.add_task(desk.alert_admins)
    return {
        "outcome": "shared" if goes_up else "waiting",
        "post": {"id": post["id"], "kind": post["kind"], "body": post["body"], "created_at": post["created_at"]},
    }


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
    # The trigger has counted it on the post already.
    rows = db.table("refuge_posts").select("amen_count").eq("id", str(post_id)).limit(1).execute().data
    return {"reactions": (rows[0].get("amen_count") or 0) if rows else 0}


@router.post("/me/refuge/posts/{post_id}/kind-words")
def send_kind_word(post_id: uuid.UUID, body: KindWordIn, user: AuthUser = Depends(require_user)) -> dict:
    post = _others_post(post_id, user)
    word = KIND_WORDS.get(body.choice)
    if not word or word["for"] != shown_kind(post):
        raise HTTPException(status_code=422, detail="Choose one of the kind words offered.")
    row = {"post_id": str(post_id), "user_id": user.id, "choice": body.choice}
    _db(lambda: get_supabase().table("refuge_kind_words").upsert(row, on_conflict="post_id,user_id", ignore_duplicates=True).execute())
    return {"status": "sent"}


class AnsweredIn(BaseModel):
    note: str | None = Field(default=None, max_length=280)


def _own_post(post_id: uuid.UUID, user: AuthUser) -> dict:
    rows = _db(lambda: (
        get_supabase().table("refuge_posts").select("id, user_id, kind, status, approved_at, expires_at, answered_at, kept_up")
        .eq("id", str(post_id)).eq("user_id", user.id).limit(1).execute().data
    ))
    if not rows:
        raise HTTPException(status_code=404, detail="That post isn't here anymore.")
    return rows[0]


@router.post("/me/refuge/posts/{post_id}/keep-up")
def keep_up(post_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """Keeps one of the person's prayer requests on the wall two weeks more,
    once it's near its end (or just past it), up to two months in all."""
    post = _own_post(post_id, user)
    until = kept_up_until(post, datetime.now(timezone.utc))
    if not until:
        raise HTTPException(status_code=422, detail="This can't be kept up right now. A prayer request stays up to two months.")
    patch = {"expires_at": until.isoformat(), "kept_up": (post.get("kept_up") or 0) + 1}
    _db(lambda: get_supabase().table("refuge_posts").update(patch).eq("id", str(post_id)).eq("user_id", user.id).execute())
    return {"expires_at": patch["expires_at"]}


@router.post("/me/refuge/posts/{post_id}/answered")
def mark_answered(post_id: uuid.UUID, body: AnsweredIn, user: AuthUser = Depends(require_user)) -> dict:
    """Marks one of the person's prayer requests answered, with an optional
    line on how. On the wall it reads as good news for five more days, so the
    people who prayed get to see it."""
    post = _own_post(post_id, user)
    if post["kind"] != "burden":
        raise HTTPException(status_code=422, detail="Only a prayer request can be marked answered.")
    note = " ".join((body.note or "").split()) or None
    if note and contact_details(note):
        raise HTTPException(status_code=422, detail="Take out any links, emails, phone numbers or @names, so nobody can find you from it.")
    now = datetime.now(timezone.utc)
    patch = {"answered_at": now.isoformat(), "answer_note": note}
    if post["status"] == "approved":
        patch["expires_at"] = (now + timedelta(days=ANSWERED_DAYS)).isoformat()
    _db(lambda: get_supabase().table("refuge_posts").update(patch).eq("id", str(post_id)).eq("user_id", user.id).execute())
    return {"answered_at": patch["answered_at"], "expires_at": patch.get("expires_at")}


def _save_report(row: dict) -> list:
    """Stores a report, returning it when it's new (one per person a post).
    Before the admin desk's migration there's no category column; the report
    still goes in, with the category folded into its reason, since a report
    must never fail."""
    def upsert(r: dict) -> list:
        return get_supabase().table("refuge_reports").upsert(r, on_conflict="post_id,user_id", ignore_duplicates=True).execute().data or []

    try:
        return upsert(row)
    except APIError as err:
        if err.code not in ("42703", "PGRST204"):
            raise
        label = REPORT_CATEGORIES[row.pop("category")]
        row["reason"] = f"{label}: {row['reason']}"[:300] if row["reason"] else label
        return upsert(row)


def _reports_today(user_id: str) -> int:
    """How many posts this person has reported in the last day."""
    since = _ago(days=1)
    return _db(lambda: (
        get_supabase().table("refuge_reports").select("post_id", count="exact")
        .eq("user_id", user_id).gte("created_at", since).limit(1).execute().count or 0
    ))


@router.post("/me/refuge/posts/{post_id}/report")
def report(post_id: uuid.UUID, body: ReportIn, background: BackgroundTasks, user: AuthUser = Depends(require_user)) -> dict:
    """Sends the post back to the desk, where it goes on the trail
    (app/desk.py), and takes it off the wall straight away unless this person
    has already reported `REPORT_TAKEDOWNS_PER_DAY` posts today. Reporting a
    post again adds nothing: one report per person."""
    post = _post(str(post_id))
    if post["user_id"] == user.id:
        raise HTTPException(status_code=400, detail="That one's yours. You can take it down instead.")
    live = on_wall(post, datetime.now(timezone.utc))
    if not live and post["status"] not in ("reported", "held"):
        raise HTTPException(status_code=404, detail="That post isn't on the wall anymore.")
    takes_down = live and _reports_today(user.id) < REPORT_TAKEDOWNS_PER_DAY
    reason = (body.reason or "").strip() or None
    row = {"post_id": str(post_id), "user_id": user.id, "category": body.category, "reason": reason}
    is_new = _db(lambda: _save_report(row))
    if is_new and takes_down:
        get_supabase().table("refuge_posts").update({"status": "reported"}).eq("id", str(post_id)).eq("status", "approved").execute()
    if is_new:
        from app import desk  # here, since app/desk.py imports this module

        background.add_task(desk.report_received, str(post_id), post["status"], body.category, reason, takes_down)
    return {"status": "reported"}


# ---------------------------------------------------------------------------
# The evening digest: one quiet notification a day for a writer whose post
# was prayed for or rejoiced with. Sent by app/reminders.py's loop and its
# scheduled workflow; `claim_amens_digest` keeps the two from both sending.
# ---------------------------------------------------------------------------
def digest_message(prayed: int, rejoiced: int, kind_words: int) -> dict | None:
    """The notification's words, or None when nothing came back."""
    parts = []
    if prayed:
        parts.append(f"{prayed} {'person' if prayed == 1 else 'people'} prayed for you")
    if rejoiced:
        parts.append(f"{rejoiced} {'person' if rejoiced == 1 else 'people'} rejoiced with you")
    if kind_words:
        parts.append(f"{kind_words} kind {'word was' if kind_words == 1 else 'words were'} sent to you")
    if not parts:
        return None
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    title = "Someone prayed for you today" if prayed == 1 and not rejoiced else "People prayed for you today" if prayed and not rejoiced else "From the Amens wall"
    return {"title": title, "body": body[0].upper() + body[1:] + ".", "url": "#amens", "tag": "amens-digest"}


def is_evening(time_zone: str | None, now: datetime) -> bool:
    """Whether it's the writer's evening, where they are (UTC if unknown)."""
    try:
        zone = ZoneInfo(time_zone) if time_zone else timezone.utc
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    return now.astimezone(zone).hour in DIGEST_HOURS


def run_digest(now: datetime | None = None) -> int:
    """Sends each due writer their digest. Returns how many were sent."""
    from app import push  # here, so importing this module stays light

    if not push.configured():
        return 0
    now = now or datetime.now(timezone.utc)
    gap = f"{int(DIGEST_GAP.total_seconds())} seconds"
    due = _rpc("amens_digest_due", {"min_gap": gap, "look_back": f"{int(DIGEST_LOOK_BACK.total_seconds())} seconds"}) or []
    sent = 0
    for writer in due:
        message = digest_message(writer["prayed"], writer["rejoiced"], writer["kind_words"])
        if not message or not is_evening(writer.get("time_zone"), now):
            continue
        if not _rpc("claim_amens_digest", {"writer": writer["user_id"], "min_gap": gap}):
            continue  # the other sender got there first
        if push.notify_user(writer["user_id"], message):
            sent += 1
    return sent
