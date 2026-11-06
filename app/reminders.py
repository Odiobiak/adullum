"""Reminders and "your church is live", sent as push notifications
(app/push.py does the sending; web/notify.js and web/sw.js are the browser
side).

A reminder is something the person asked for with a bell: an event a day or
an hour before, or a weekly gathering a little before it starts. Each is one
row in `reminders`, keyed by what it's about, so ringing the same bell again
changes it rather than adding another.

Sending. Render's free plan sleeps a quiet server, so two things send due
reminders, and either is enough:
  - while the server is awake, `loop` checks every minute, and checks the
    person's churches for a live stream every few minutes;
  - a scheduled GitHub workflow (.github/workflows/reminders.yml) calls
    POST /internal/send-reminders every five minutes with CRON_SECRET, which
    wakes the server if it was asleep and sends whatever is due.
A reminder is claimed (its `sent_at` set only if it was still empty) before
it's sent, so the two can never send the same one twice. One that's more
than six hours late is dropped rather than sent, since it would only confuse.

Same rule as app/cave.py for every /me route: filter by the signed-in
user's id in code.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app import push
from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.config import settings
from app.db import get_supabase

log = logging.getLogger(__name__)

router = APIRouter()

_SETUP_HINT = (
    "Reminders aren't set up on the database yet. Run "
    "supabase/migrations/20261115_reminders.sql in the Supabase SQL editor."
)

MAX_REMINDERS = 200
STALE_AFTER = timedelta(hours=6)
LOOP_SECONDS = 60
LIVE_EVERY_LOOPS = 3


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
class DeviceKeys(BaseModel):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=8, max_length=100)


class DeviceIn(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)
    keys: DeviceKeys

    @field_validator("endpoint")
    @classmethod
    def https_only(cls, endpoint: str) -> str:
        if not endpoint.startswith("https://"):
            raise ValueError("That isn't a push address.")
        return endpoint


class DeviceOut(BaseModel):
    endpoint: str = Field(min_length=10, max_length=1000)


class Repeat(BaseModel):
    """A weekly gathering: remind `before` minutes ahead of each one."""
    day: int = Field(ge=0, le=6)  # 0 = Sunday
    time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    zone: str = Field(max_length=60)
    before: int = Field(ge=0, le=24 * 60)

    @field_validator("zone")
    @classmethod
    def known_zone(cls, zone: str) -> str:
        try:
            ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("That time zone isn't one we know.")
        return zone


class ReminderIn(BaseModel):
    key: str = Field(min_length=3, max_length=200, pattern=r"^[\w:.\-]+$")
    title: str = Field(min_length=1, max_length=120)
    body: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=300)
    remind_at: datetime | None = None
    repeat: Repeat | None = None

    @field_validator("url")
    @classmethod
    def inside_adullum(cls, url: str | None) -> str | None:
        return inside_link(url)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_reminders.py)
# ---------------------------------------------------------------------------
def inside_link(url: str | None) -> str | None:
    """A notification only ever opens a place inside Adullum ("#church/c/..."),
    never another site."""
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"^#[\w/\-.:]*$", url):
        raise ValueError("A reminder can only open a page in Adullum.")
    return url


def next_occurrence(rule: dict, after: datetime) -> datetime:
    """When to remind next for a weekly gathering: `before` minutes ahead of
    its next start (in its own time zone) that is still to come after `after`.
    Worked out in the zone each time, so a clock change never shifts it."""
    zone = ZoneInfo(rule["zone"])
    hour, minute = (int(x) for x in rule["time"].split(":"))
    before = timedelta(minutes=int(rule.get("before") or 0))
    local = after.astimezone(zone)
    # Python's weekday() is Monday = 0; ours is Sunday = 0.
    ahead = (int(rule["day"]) - (local.weekday() + 1) % 7) % 7
    for extra in (0, 7, 14):
        day = (local + timedelta(days=ahead + extra)).date()
        start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
        if start - before > after:
            return (start - before).astimezone(timezone.utc)
    raise ValueError("no next occurrence")  # unreachable for a valid rule


def is_stale(remind_at: datetime, now: datetime) -> bool:
    return now - remind_at > STALE_AFTER


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------
def run_due(now: datetime | None = None) -> int:
    """Send every reminder that's due. Returns how many went out."""
    if not push.configured():
        return 0
    now = now or datetime.now(timezone.utc)
    db = get_supabase()
    due = (
        db.table("reminders").select("id, user_id, key, title, body, url, remind_at, repeat")
        .is_("sent_at", "null").lte("remind_at", now.isoformat()).order("remind_at").limit(200).execute().data
    )
    sent = 0
    for reminder in due:
        claimed = db.table("reminders").update({"sent_at": now.isoformat()}).eq("id", reminder["id"]).is_("sent_at", "null").execute().data
        if not claimed:
            continue  # the other sender got it first
        if not is_stale(_parse(reminder["remind_at"]), now):
            payload = {"title": reminder["title"], "body": reminder.get("body") or "", "url": reminder.get("url") or "#home", "tag": reminder["key"]}
            if push.notify_user(reminder["user_id"], payload):
                sent += 1
        if reminder.get("repeat"):
            try:
                again = next_occurrence(reminder["repeat"], now)
                db.table("reminders").update({"remind_at": again.isoformat(), "sent_at": None}).eq("id", reminder["id"]).execute()
            except Exception:
                log.warning("couldn't move weekly reminder %s on", reminder["id"], exc_info=True)
    return sent


def run_live() -> int:
    """Tell people when one of their churches goes live (once per stream).
    Only churches with "Tell me when it's live" on, of people with a device
    that takes notifications, are checked."""
    if not push.configured():
        return 0
    from app.churches import live_video  # here, so importing this module stays light

    db = get_supabase()
    users = list({r["user_id"] for r in db.table("push_subscriptions").select("user_id").limit(5000).execute().data})
    if not users:
        return 0
    churches = (
        db.table("churches").select("id, user_id, name, youtube_url, last_live_video")
        .eq("live_alerts", True).not_.is_("youtube_url", "null").in_("user_id", users).limit(500).execute().data
    )
    channels = sorted({c["youtube_url"] for c in churches})
    with ThreadPoolExecutor(max_workers=4) as pool:
        live = dict(zip(channels, pool.map(live_video, channels)))
    told = 0
    for church in churches:
        video = live.get(church["youtube_url"])
        if not video or video == church.get("last_live_video"):
            continue
        db.table("churches").update({"last_live_video": video}).eq("id", church["id"]).eq("user_id", church["user_id"]).execute()
        payload = {"title": f"{church['name']} is live", "body": "Tap to watch, with your notes beside it.", "url": f"#church/live/{church['id']}", "tag": f"live:{church['id']}"}
        if push.notify_user(church["user_id"], payload):
            told += 1
    return told


_loop_task: asyncio.Task | None = None


async def loop() -> None:
    """Sends due reminders every minute, and checks for live churches every
    few minutes, for as long as the server is awake."""
    turn = 0
    while True:
        try:
            await asyncio.to_thread(run_due)
            if turn % LIVE_EVERY_LOOPS == 0:
                await asyncio.to_thread(run_live)
        except Exception:
            # A missing table (migration not run yet) or a network blip: try again next time.
            log.info("reminder loop skipped a turn", exc_info=True)
        turn += 1
        await asyncio.sleep(LOOP_SECONDS)


def start() -> None:
    """Start the loop once, when push is set up (called by app/main.py)."""
    global _loop_task
    if push.configured() and _loop_task is None:
        _loop_task = asyncio.create_task(loop())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/push/key")
def push_key() -> dict:
    """The public key a browser subscribes with, or null when push isn't set up."""
    return {"key": settings.vapid_public_key or None}


@router.post("/me/push")
def add_device(body: DeviceIn, user: AuthUser = Depends(require_user)) -> dict:
    row = {"endpoint": body.endpoint, "user_id": user.id, "p256dh": body.keys.p256dh, "auth": body.keys.auth}
    _db(lambda: get_supabase().table("push_subscriptions").upsert(row, on_conflict="endpoint").execute())
    return {"status": "ok"}


@router.post("/me/push/remove")
def remove_device(body: DeviceOut, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("push_subscriptions").delete().eq("endpoint", body.endpoint).eq("user_id", user.id).execute())
    return {"status": "deleted"}


@router.post("/me/push/test")
def test_device(user: AuthUser = Depends(require_user)) -> dict:
    if not push.configured():
        raise HTTPException(status_code=503, detail="Notifications aren't set up on this server yet.")
    reached = _db(lambda: push.notify_user(user.id, {"title": "Notifications are on", "body": "This is how Adullum will remind you.", "url": "#church", "tag": "test"}))
    return {"reached": reached}


@router.get("/me/reminders")
def list_reminders(user: AuthUser = Depends(require_user)) -> list[dict]:
    return _db(lambda: (
        get_supabase().table("reminders").select("key, title, remind_at, repeat")
        .eq("user_id", user.id).is_("sent_at", "null").order("remind_at").limit(MAX_REMINDERS).execute().data
    ))


@router.put("/me/reminders")
def set_reminder(body: ReminderIn, user: AuthUser = Depends(require_user)) -> dict:
    now = datetime.now(timezone.utc)
    if body.repeat:
        remind_at = next_occurrence(body.repeat.model_dump(), now)
    elif body.remind_at:
        remind_at = body.remind_at if body.remind_at.tzinfo else body.remind_at.replace(tzinfo=timezone.utc)
        if remind_at < now - timedelta(minutes=5):
            raise HTTPException(status_code=422, detail="That time has already passed.")
    else:
        raise HTTPException(status_code=422, detail="Say when to remind you.")
    count = _db(lambda: get_supabase().table("reminders").select("id", count="exact").eq("user_id", user.id).is_("sent_at", "null").execute().count) or 0
    if count >= MAX_REMINDERS:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_REMINDERS} reminders.")
    row = {
        "user_id": user.id, "key": body.key, "title": body.title.strip(), "body": (body.body or "").strip() or None,
        "url": body.url, "remind_at": remind_at.isoformat(), "repeat": body.repeat.model_dump() if body.repeat else None,
        "sent_at": None, "created_at": _now(),
    }
    saved = _db(lambda: get_supabase().table("reminders").upsert(row, on_conflict="user_id,key").execute().data[0])
    return {k: saved[k] for k in ("key", "title", "remind_at", "repeat")}


@router.delete("/me/reminders")
def remove_reminder(key: str = Query(min_length=3, max_length=200), user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("reminders").delete().eq("user_id", user.id).eq("key", key).execute())
    return {"status": "deleted"}


@router.post("/internal/send-reminders")
def send_reminders(x_cron_secret: str | None = Header(default=None)) -> dict:
    """For the scheduled workflow: wakes the server and sends what's due."""
    if not settings.cron_secret or not x_cron_secret or not hmac.compare_digest(x_cron_secret, settings.cron_secret):
        raise HTTPException(status_code=403, detail="Not allowed.")
    return {"sent": run_due(), "live": run_live()}
