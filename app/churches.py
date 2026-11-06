"""The Church tab (web/church.js): the churches a person has put in their own
list, their sermons, and sermon notes drafted from a link.

Personal, never social. A church belongs to the one person who added it (see
supabase/migrations/20261114_churches.sql): nobody follows anything, nobody
sees who else goes where, and Adullum never suggests a church. The tab exists
for people who want their churches close by.

A church can be added two ways:
  - From a link. POST /me/churches/read fetches the page (through
    app/church_web.py's safe fetching), reads its structured data and a few
    likely pages (visit, events, news), and has the model pick out the
    details. Nothing is saved: the page shows the draft, the person corrects
    it, and POST /me/churches saves what they confirm. A church added from a
    site is read again in the background when it's opened a week or more
    after the last check, which keeps its events and notices current.
  - By hand, with the same POST /me/churches.

What's live comes from each church's YouTube channel, checked at most every
two minutes per channel. Sermons come from the channel's public feed and from
a podcast feed. Listen tags those sermons by season (weary, anxious, ...)
with the model once per sermon, kept in `sermon_moods`.

A sermon note can be drafted from a link (POST /me/sermons/from-link): the
video's transcript when YouTube allows it, otherwise its description, turned
into passages, main points, a line worth keeping, steps for the week and one
question. Passages are only ever references, checked by the same parser Aquila
uses; verse text is read from the database when the note is shown. The note
is then an ordinary sermon note (app/sermons.py), with the week after it
tracked in its `week` column.

Same rule as app/cave.py: the service-role client bypasses RLS, so every
query filters by the signed-in user's id. Never drop the `.eq("user_id", ...)`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

from app import church_web as web
from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.config import settings
from app.days import parse_today
from app.db import get_supabase
from app.sermons import canonical_or_raw, clean_blocks, note_passages, present, references_in

log = logging.getLogger(__name__)

router = APIRouter()

_SETUP_HINT = (
    "The Church tab isn't set up on the database yet. Run "
    "supabase/migrations/20261114_churches.sql in the Supabase SQL editor."
)

_llm = ChatOpenAI(model=settings.chat_model, api_key=settings.openai_api_key, temperature=0)

MAX_CHURCHES = 20
RECHECK_AFTER = timedelta(days=7)
LIVE_CACHE_SECONDS = 120
FEED_CACHE_SECONDS = 30 * 60
SITE_TEXT_CHARS = 14_000
MOODS = ("weary", "anxious", "grateful", "grieving", "deciding", "joyful")
DAYS = ("sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday")
_EM_DASH = "\u2014"


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
Time = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


class Gathering(BaseModel):
    label: str = Field(default="", max_length=60)
    day: int = Field(ge=0, le=6)  # 0 = Sunday
    time: str = Time


class Notice(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    date: str | None = Field(default=None, max_length=20)
    added: str | None = Field(default=None, max_length=40)  # when Adullum first saw it


class Event(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


def _web_link(url: str | None) -> str | None:
    """A link kept on a church: http(s) only, since it's shown as a link."""
    url = web.normalise_url(url or "")
    if not url:
        return None
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("A link needs to start with http:// or https://")
    return url[:500]


def _zone(name: str | None) -> str | None:
    if not name:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("That time zone isn't one we know.")
    return name


class ChurchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    time_zone: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=300)
    pastors: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    youtube_url: str | None = Field(default=None, max_length=500)
    podcast_url: str | None = Field(default=None, max_length=500)
    facebook_url: str | None = Field(default=None, max_length=500)
    gatherings: list[Gathering] = Field(default_factory=list, max_length=20)
    notices: list[Notice] = Field(default_factory=list, max_length=10)
    events: list[Event] = Field(default_factory=list, max_length=20)
    source_url: str | None = Field(default=None, max_length=500)
    live_alerts: bool = True

    @field_validator("website", "youtube_url", "podcast_url", "facebook_url", "source_url")
    @classmethod
    def web_links_only(cls, value: str | None) -> str | None:
        return _web_link(value)

    @field_validator("time_zone")
    @classmethod
    def known_zone(cls, value: str | None) -> str | None:
        return _zone(value)


class ChurchPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    time_zone: str | None = Field(default=None, max_length=60)
    address: str | None = Field(default=None, max_length=300)
    pastors: str | None = Field(default=None, max_length=300)
    website: str | None = Field(default=None, max_length=500)
    youtube_url: str | None = Field(default=None, max_length=500)
    podcast_url: str | None = Field(default=None, max_length=500)
    facebook_url: str | None = Field(default=None, max_length=500)
    gatherings: list[Gathering] | None = Field(default=None, max_length=20)
    live_alerts: bool | None = None

    @field_validator("website", "youtube_url", "podcast_url", "facebook_url")
    @classmethod
    def web_links_only(cls, value: str | None) -> str | None:
        return _web_link(value)

    @field_validator("time_zone")
    @classmethod
    def known_zone(cls, value: str | None) -> str | None:
        return _zone(value)


class ReadIn(BaseModel):
    url: str = Field(min_length=3, max_length=500)


class FromLinkIn(BaseModel):
    url: str = Field(min_length=3, max_length=500)
    church_id: uuid.UUID | None = None


class WeekIn(BaseModel):
    step: Literal["reread", "learn", "question", "act", "pray"] | None = None
    done: bool | None = None
    answer: str | None = Field(default=None, max_length=2000)


# What the model returns when reading a church's site. Everything optional:
# a field the pages don't state stays empty rather than guessed.
class _DraftGathering(BaseModel):
    label: str = Field(description="What it is, short: 'Sunday service', 'Bible study', 'Prayer meeting'.")
    day: str = Field(description="Day of the week in English, e.g. 'Sunday'.")
    time: str = Field(description="Start time, 24-hour HH:MM.")


class _DraftEvent(BaseModel):
    title: str
    date: str = Field(description="YYYY-MM-DD. Leave the event out if its date isn't stated.")
    time: str | None = Field(default=None, description="24-hour HH:MM, if stated.")


class ChurchDraft(BaseModel):
    name: str = Field(default="", description="The church's name as it calls itself.")
    city: str = Field(default="", description="City, as on the site.")
    time_zone: str = Field(default="", description="IANA time zone for that city, e.g. 'Africa/Lagos', 'America/New_York'. Empty if the city is unknown.")
    address: str = ""
    pastors: str = Field(default="", description="Pastors or leaders named on the site, comma separated.")
    gatherings: list[_DraftGathering] = Field(default_factory=list, description="Regular weekly gatherings only.")
    events: list[_DraftEvent] = Field(default_factory=list, description="Upcoming one-off events with a stated date.")
    notices: list[str] = Field(default_factory=list, description="Short announcements a member should know (changed times, closures). Each one plain sentence, at most 140 characters.")


_READ_PROMPT = (
    "You read a church's own web pages and pick out practical details for one of its members. "
    "Use only what the pages state. Never guess a time, a date or a name: leave it out instead. "
    "Weekly gatherings go in `gatherings`; one-off dated events in `events`; announcements in `notices`. "
    "Write plainly, never use an em dash, and don't add marketing language."
)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_churches.py)
# ---------------------------------------------------------------------------
def day_index(name: str) -> int | None:
    key = (name or "").strip().lower()[:3]
    for i, day in enumerate(DAYS):
        if day.startswith(key) and key:
            return i
    return None


def clean_time(value: str | None) -> str | None:
    """'9:00', '09:00', '9am', '5:30 pm' -> 'HH:MM', or None."""
    text = (value or "").strip().lower().replace(".", "")
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if not match:
        return None
    hour, minute, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
    if half == "pm" and hour < 12:
        hour += 12
    if half == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}" if hour < 24 and minute < 60 else None


def _plain(text: str | None, limit: int) -> str:
    return " ".join((text or "").replace(_EM_DASH, ",").split())[:limit]


def merge_draft(url: str, draft: ChurchDraft, structured: dict, links: dict, today: date) -> dict:
    """What the page shows for review: the model's reading, with the site's
    own structured data and links taking precedence where they exist, and only
    gatherings and events that make sense kept."""
    gatherings = []
    for g in draft.gatherings:
        day, at = day_index(g.day), clean_time(g.time)
        if day is not None and at and len(gatherings) < 20:
            gatherings.append({"label": _plain(g.label, 60) or "Gathering", "day": day, "time": at})
    events, seen = [], set()
    for e in [*structured.get("events", []), *(ev.model_dump() for ev in draft.events)]:
        try:
            when = date.fromisoformat(str(e.get("date"))[:10])
        except ValueError:
            continue
        title = _plain(e.get("title"), 120)
        key = (title.lower(), when)
        if not title or when < today or key in seen:
            continue
        seen.add(key)
        events.append({"title": title, "date": when.isoformat(), "time": clean_time(e.get("time"))})
    events.sort(key=lambda e: e["date"])
    try:
        zone = _zone(draft.time_zone.strip() or None)
    except ValueError:
        zone = None
    added = _now()
    return {
        "name": _plain(structured.get("name") or draft.name, 120),
        "city": _plain(structured.get("city") or draft.city, 120) or None,
        "time_zone": zone,
        "address": _plain(structured.get("address") or draft.address, 300) or None,
        "pastors": _plain(draft.pastors, 300) or None,
        "website": url if not web.is_youtube(url) else None,
        "youtube_url": links.get("youtube_url"),
        "podcast_url": links.get("podcast_url"),
        "facebook_url": links.get("facebook_url"),
        "gatherings": gatherings,
        "events": events[:20],
        "notices": [{"text": _plain(n, 300), "date": None, "added": added} for n in draft.notices if _plain(n, 300)][:10],
        "source_url": url,
    }


def unseen_notices(church: dict) -> int:
    """How many notices arrived since the person last opened them."""
    seen = church.get("notices_seen_at")
    return sum(1 for n in church.get("notices") or [] if not seen or (n.get("added") or "") > seen)


def carry_notice_dates(old: list[dict], new: list[dict]) -> list[dict]:
    """A refreshed notice that was already there keeps its first-seen time,
    so only genuinely new ones raise the count on the info icon."""
    known = {n.get("text"): n.get("added") for n in old or []}
    return [{**n, "added": known.get(n.get("text")) or n.get("added")} for n in new]


def week_steps(note: dict) -> list[dict]:
    """The five small steps for the week after a sermon, from its note."""
    passages = note.get("passages") or []
    main = note.get("passage_ref") or (passages[0] if passages else None)
    verse = next((p for p in passages if ":" in p), None)
    if not verse and main and ":" not in main:
        verse = f"{main}:1"
    todo = next((i.get("text") for b in note.get("blocks") or [] if b.get("type") == "todo" for i in b.get("items") or [] if (i.get("text") or "").strip()), None)
    week = note.get("week") or {}
    done = week.get("done") or {}
    steps = [
        {"key": "reread", "offset": 1, "title": "Read the passage again", "ref": main},
        {"key": "learn", "offset": 2, "title": "Carry a verse with you", "ref": verse},
        {"key": "question", "offset": 3, "title": "One question to sit with", "text": week.get("question") or "What is God asking of you from this sermon?", "answer": week.get("answer") or ""},
        {"key": "act", "offset": 4, "title": "Do the thing", "text": todo or "Do one thing the sermon asked of you."},
        {"key": "pray", "offset": 6, "title": "Pray it before Sunday", "ref": main},
    ]
    return [{**s, "done": bool(done.get(s["key"]))} for s in steps if s["key"] not in ("reread", "learn") or s.get("ref")]


# ---------------------------------------------------------------------------
# Reading a church from its link
# ---------------------------------------------------------------------------
def read_church(url: str, today: date) -> dict:
    url = web.normalise_url(url)
    if web.is_youtube(url):
        return _read_youtube_channel(url)
    final_url, html = web.safe_get(url)
    page = web.parse_page(final_url, html)
    pages = [page]
    for extra in web.useful_pages(page):
        try:
            pages.append(web.parse_page(*web.safe_get(extra)))
        except web.FetchError:
            continue
    structured = web.from_json_ld([item for p in pages for item in p.json_ld])
    links = web.social_links([*structured.get("same_as", []), *(href for p in pages for href, _ in p.links)])
    text = "\n\n".join(f"Page: {p.url}\nTitle: {p.title}\n{p.text}" for p in pages)[:SITE_TEXT_CHARS]
    try:
        draft = _llm.with_structured_output(ChurchDraft).invoke([
            SystemMessage(_READ_PROMPT),
            HumanMessage(f"Today is {today.isoformat()}.\n\n{text}"),
        ])
    except Exception:
        log.warning("couldn't read %s with the model", final_url, exc_info=True)
        draft = ChurchDraft(name=page.site_name or page.title)
    if not (draft.name or structured.get("name")):
        draft.name = page.site_name or page.title.split("|")[0].split(" - ")[0]
    return merge_draft(final_url, draft, structured, links, today)


def _read_youtube_channel(url: str) -> dict:
    final_url, html = web.safe_get(url, max_bytes=web.YOUTUBE_PAGE_BYTES)
    page = web.parse_page(final_url, html)
    name = (page.site_name or page.title).removesuffix(" - YouTube").strip()
    return {
        "name": _plain(name, 120), "city": None, "time_zone": None, "address": None, "pastors": None,
        "website": None, "youtube_url": final_url.split("?")[0].rstrip("/"), "podcast_url": None, "facebook_url": None,
        "gatherings": [], "events": [], "notices": [], "source_url": final_url,
    }


def _refresh(church: dict) -> None:
    """Read a church's site again and keep its events and notices current.
    Gatherings are left alone, since the person may have corrected them."""
    try:
        fresh = read_church(church["source_url"], date.today())
    except Exception:
        log.info("couldn't recheck church %s", church.get("id"), exc_info=True)
        fresh = None
    update = {"checked_at": _now()}
    if fresh:
        update["events"] = fresh["events"]
        update["notices"] = carry_notice_dates(church.get("notices") or [], fresh["notices"])
    try:
        get_supabase().table("churches").update(update).eq("id", church["id"]).eq("user_id", church["user_id"]).execute()
    except Exception:
        log.warning("couldn't save the recheck of church %s", church.get("id"), exc_info=True)


# ---------------------------------------------------------------------------
# Live and sermons (cached in this process)
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_live_cache: dict[str, tuple[float, str | None]] = {}
_feed_cache: dict[str, tuple[float, list[dict]]] = {}


def live_video(channel_url: str) -> str | None:
    """The live video id for a channel, checked at most every two minutes."""
    now = time.monotonic()
    with _cache_lock:
        hit = _live_cache.get(channel_url)
    if hit and now - hit[0] < LIVE_CACHE_SECONDS:
        return hit[1]
    try:
        _, html = web.safe_get(web.channel_live_url(channel_url), max_bytes=web.YOUTUBE_PAGE_BYTES)
        video = web.youtube_live_video(html)
    except web.FetchError:
        video = None
    with _cache_lock:
        _live_cache[channel_url] = (now, video)
    return video


def _cached_feed(key: str, load) -> list[dict]:
    now = time.monotonic()
    with _cache_lock:
        hit = _feed_cache.get(key)
    if hit and now - hit[0] < FEED_CACHE_SECONDS:
        return hit[1]
    try:
        items = load()
    except Exception:
        log.info("couldn't read feed %s", key, exc_info=True)
        items = hit[1] if hit else []
    with _cache_lock:
        _feed_cache[key] = (now, items)
    return items


def _podcast_feed_url(url: str) -> str | None:
    """An RSS feed for a podcast link: the link itself, or Apple's lookup."""
    host = (urlparse(url).hostname or "").lower()
    if host == "podcasts.apple.com":
        match = re.search(r"/id(\d+)", url)
        if not match:
            return None
        _, body = web.safe_get(f"https://itunes.apple.com/lookup?id={match.group(1)}&entity=podcast")
        results = json.loads(body).get("results") or []
        return results[0].get("feedUrl") if results else None
    if host in ("open.spotify.com", "anchor.fm"):
        return None  # no public feed behind these links
    return url


def church_sermons(church: dict) -> list[dict]:
    """The church's latest sermons, from its YouTube feed and its podcast."""
    items: list[dict] = []
    channel = church.get("youtube_channel_id")
    if channel:
        items += _cached_feed(f"yt:{channel}", lambda: web.parse_youtube_feed(web.safe_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel}")[1]))
    if church.get("podcast_url"):
        podcast = church["podcast_url"]

        def load_podcast():
            feed = _podcast_feed_url(podcast)
            return web.parse_podcast_feed(web.safe_get(feed, max_bytes=3_000_000)[1])[:20] if feed else []
        items += _cached_feed(f"pod:{podcast}", load_podcast)
    return [{**i, "church_id": church["id"], "church": church["name"], "refs": references_in(f"{i['title']} {i.get('description', '')}")[:3]} for i in items]


def _ensure_channel_id(church: dict, user: AuthUser) -> dict:
    """Find and keep a church's YouTube channel id, which its feed needs."""
    if church.get("youtube_channel_id") or not church.get("youtube_url"):
        return church
    try:
        _, html = web.safe_get(church["youtube_url"], max_bytes=web.YOUTUBE_PAGE_BYTES)
    except web.FetchError:
        return church
    channel = web.youtube_channel_id(html)
    if channel:
        church = {**church, "youtube_channel_id": channel}
        _db(lambda: get_supabase().table("churches").update({"youtube_channel_id": channel}).eq("id", church["id"]).eq("user_id", user.id).execute())
    return church


class _MoodTag(BaseModel):
    id: str
    moods: list[Literal["weary", "anxious", "grateful", "grieving", "deciding", "joyful"]] = Field(default_factory=list)


class _MoodTags(BaseModel):
    tags: list[_MoodTag]


def tag_moods(items: list[dict]) -> dict[str, list[str]]:
    """Which seasons each sermon speaks to, worked out once and kept."""
    if not items:
        return {}
    ids = [i["id"] for i in items]
    known = {r["item_id"]: r["moods"] for r in _db(lambda: get_supabase().table("sermon_moods").select("item_id, moods").in_("item_id", ids).execute().data)}
    missing = [i for i in items if i["id"] not in known][:30]
    if missing:
        listing = "\n".join(f"- id {i['id']}: {i['title']} | {i.get('description', '')[:300]}" for i in missing)
        try:
            result = _llm.with_structured_output(_MoodTags).invoke([
                SystemMessage(
                    "For each sermon, say which seasons of life it would help someone in: weary, anxious, grateful, "
                    "grieving, deciding (facing a decision) or joyful. Judge from its title, description and the passages "
                    "named. Choose none when it isn't clear. Most sermons fit one or two."
                ),
                HumanMessage(listing),
            ])
            fresh = {t.id: list(dict.fromkeys(t.moods)) for t in result.tags if t.id in {i["id"] for i in missing}}
        except Exception:
            log.warning("couldn't tag sermon moods", exc_info=True)
            fresh = {}
        if fresh:
            rows = [{"item_id": k, "moods": v} for k, v in fresh.items()]
            _db(lambda: get_supabase().table("sermon_moods").upsert(rows).execute())
            known.update(fresh)
    return known


# ---------------------------------------------------------------------------
# Drafting a sermon note from a link
# ---------------------------------------------------------------------------
class _Point(BaseModel):
    at_seconds: float | None = Field(default=None, description="Where in the video the point is made, if the transcript shows it.")
    text: str


class _Quote(BaseModel):
    text: str = ""
    who: str = ""


class SermonDraft(BaseModel):
    title: str = ""
    speaker: str = Field(default="", description="The preacher, if named.")
    main_passage: str = Field(default="", description="The main Bible passage preached, as a reference like 'Isaiah 40:28-31'.")
    passages: list[str] = Field(default_factory=list, description="Other passages read or referred to, as references only.")
    points: list[_Point] = Field(default_factory=list, description="Three to five main points, one plain sentence each.")
    quote: _Quote = Field(default_factory=_Quote, description="One memorable line the preacher said, word for word from the transcript. Never a Bible verse.")
    todos: list[str] = Field(default_factory=list, description="Up to three practical things to do this week that the sermon asked for.")
    question: str = Field(default="", description="One short, personal question to sit with this week.")


_DRAFT_PROMPT = (
    "You draft sermon notes for the person who listened, from the sermon's transcript or description. "
    "Write only what the sermon says. Name Bible passages as references only and never quote verse text. "
    "The quote must be the preacher's own words, not Scripture. Keep each point to one plain sentence. "
    "Never use an em dash. If the source is only a short description, keep the notes short rather than inventing."
)


def _source_for(url: str) -> dict:
    """What a sermon link says: details, and the words to draft from."""
    video = web.youtube_video_id(url)
    if video:
        details = {}
        try:
            _, html = web.safe_get(f"https://www.youtube.com/watch?v={video}", max_bytes=web.YOUTUBE_PAGE_BYTES)
            details = web.watch_page_details(html)
        except web.FetchError:
            pass
        transcript = web.video_transcript(video)
        if transcript:
            words = "\n".join(f"[{int(at)}s] {line}" for at, line in transcript)
        else:
            words = details.get("description", "")
        return {"video_id": video, "url": f"https://www.youtube.com/watch?v={video}", "details": details, "words": words, "transcript": bool(transcript)}
    final_url, html = web.safe_get(url)
    page = web.parse_page(final_url, html)
    return {"video_id": None, "url": final_url, "details": {"title": page.title, "description": page.description}, "words": page.text[:SITE_TEXT_CHARS], "transcript": False}


def note_from_draft(draft: SermonDraft, source: dict, church: dict | None, preached_on: date) -> dict:
    """The sermon note's details and blocks, from the model's draft, with every
    passage checked by the reference parser before it's kept."""
    def bid() -> str:
        return uuid.uuid4().hex[:16]

    main = references_in(draft.main_passage)
    passages = list(dict.fromkeys([*main, *(r for p in draft.passages for r in references_in(p))]))[:8]
    blocks: list[dict] = []
    points = [p for p in draft.points if _plain(p.text, 300)][:6]
    if points:
        lines = []
        for p in points:
            stamp = f"{web.clock(p.at_seconds)} " if source.get("video_id") and p.at_seconds is not None else ""
            lines.append(f"• {stamp}{_plain(p.text, 300)}")
        blocks.append({"id": bid(), "type": "heading", "text": "Main points"})
        blocks.append({"id": bid(), "type": "text", "text": "\n".join(lines)})
    for ref in passages:
        blocks.append({"id": bid(), "type": "verse", "ref": ref})
    quote = _plain(draft.quote.text, 600)
    if quote and not references_in(quote):
        blocks.append({"id": bid(), "type": "quote", "text": quote, "who": _plain(draft.quote.who or draft.speaker, 200)})
    todos = [_plain(t, 300) for t in draft.todos if _plain(t, 300)][:3]
    if todos:
        blocks.append({"id": bid(), "type": "todo", "items": [{"text": t, "done": False, "prayer_id": None} for t in todos]})
    blocks.append({"id": bid(), "type": "text", "text": ""})
    blocks.append({"id": bid(), "type": "link", "url": source["url"], "label": "Watch again" if source.get("video_id") else "Listen again"})
    return {
        "title": _plain(draft.title or source["details"].get("title"), 200) or "Sermon",
        "speaker": _plain(draft.speaker, 200) or None,
        "church": church["name"] if church else (_plain(source["details"].get("channel"), 200) or None),
        "preached_on": preached_on.isoformat(),
        "passage_ref": canonical_or_raw(main[0]) if main else (passages[0] if passages else None),
        "blocks": blocks,
        "week": {"question": _plain(draft.question, 300) or None, "done": {}},
    }


# ---------------------------------------------------------------------------
# Routes: churches
# ---------------------------------------------------------------------------
_FIELDS = (
    "id, user_id, name, city, time_zone, address, pastors, website, youtube_url, youtube_channel_id, podcast_url, "
    "facebook_url, gatherings, notices, events, source_url, checked_at, notices_seen_at, live_alerts, created_at"
)


def _present(church: dict) -> dict:
    out = {k: v for k, v in church.items() if k != "user_id"}
    out["unseen"] = unseen_notices(church)
    return out


def _own(church_id: uuid.UUID, user: AuthUser) -> dict:
    rows = _db(lambda: get_supabase().table("churches").select(_FIELDS).eq("id", str(church_id)).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That church isn't in your list anymore.")
    return rows[0]


def _all(user: AuthUser) -> list[dict]:
    return _db(lambda: get_supabase().table("churches").select(_FIELDS).eq("user_id", user.id).order("created_at").limit(MAX_CHURCHES).execute().data)


@router.get("/me/churches")
def list_churches(user: AuthUser = Depends(require_user)) -> list[dict]:
    return [_present(c) for c in _all(user)]


@router.post("/me/churches/read")
def read_link(body: ReadIn, today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """A draft of the church at a link, for the person to check. Saves nothing."""
    try:
        return read_church(body.url, parse_today(today))
    except web.FetchError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.post("/me/churches")
def add_church(body: ChurchIn, user: AuthUser = Depends(require_user)) -> dict:
    if len(_all(user)) >= MAX_CHURCHES:
        raise HTTPException(status_code=422, detail=f"You can keep up to {MAX_CHURCHES} churches.")
    row = {**body.model_dump(mode="json"), "id": str(uuid.uuid4()), "user_id": user.id}
    if body.source_url:
        row["checked_at"] = _now()
    # Notices that came with a draft count as already seen: the person just read them.
    row["notices_seen_at"] = _now()
    church = _db(lambda: get_supabase().table("churches").insert(row).execute().data[0])
    church = _ensure_channel_id(church, user)
    return _present(church)


@router.get("/me/churches/live")
def live_now(user: AuthUser = Depends(require_user)) -> list[dict]:
    """The person's churches that are streaming right now."""
    churches = [c for c in _all(user) if c.get("youtube_url")]
    if not churches:
        return []
    with ThreadPoolExecutor(max_workers=4) as pool:
        videos = list(pool.map(lambda c: live_video(c["youtube_url"]), churches))
    return [
        {"church_id": c["id"], "name": c["name"], "video_id": v, "alerts": c.get("live_alerts", True)}
        for c, v in zip(churches, videos) if v
    ]


@router.get("/me/churches/{church_id}")
def get_church(church_id: uuid.UUID, background: BackgroundTasks, user: AuthUser = Depends(require_user)) -> dict:
    church = _own(church_id, user)
    checked = church.get("checked_at")
    if church.get("source_url") and (not checked or datetime.fromisoformat(checked) < datetime.now(timezone.utc) - RECHECK_AFTER):
        background.add_task(_refresh, church)
    return _present(church)


@router.patch("/me/churches/{church_id}")
def update_church(church_id: uuid.UUID, body: ChurchPatch, user: AuthUser = Depends(require_user)) -> dict:
    church = _own(church_id, user)
    changes = body.model_dump(mode="json", exclude_unset=True)
    if "name" in changes and not changes["name"]:
        changes.pop("name")
    if "youtube_url" in changes and changes["youtube_url"] != church.get("youtube_url"):
        changes["youtube_channel_id"] = None
    changes["updated_at"] = _now()
    church = _db(lambda: get_supabase().table("churches").update(changes).eq("id", str(church_id)).eq("user_id", user.id).execute().data[0])
    return _present(_ensure_channel_id(church, user))


@router.delete("/me/churches/{church_id}")
def remove_church(church_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("churches").delete().eq("id", str(church_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}


@router.post("/me/churches/{church_id}/seen")
def notices_seen(church_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("churches").update({"notices_seen_at": _now()}).eq("id", str(church_id)).eq("user_id", user.id).execute())
    return {"status": "ok"}


@router.get("/me/churches/{church_id}/sermons")
def sermons_of(church_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> list[dict]:
    church = _ensure_channel_id(_own(church_id, user), user)
    return [{k: v for k, v in s.items() if k != "description"} for s in church_sermons(church)][:20]


@router.get("/me/listen")
def listen(mood: Literal["weary", "anxious", "grateful", "grieving", "deciding", "joyful"] = Query(...), user: AuthUser = Depends(require_user)) -> list[dict]:
    """Sermons from the person's own churches that speak to `mood`."""
    churches = [_ensure_channel_id(c, user) for c in _all(user)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        items = [s for batch in pool.map(church_sermons, churches) for s in batch[:15]]
    tags = tag_moods(items)
    picked = [s for s in items if mood in (tags.get(s["id"]) or [])]
    picked.sort(key=lambda s: s.get("published") or "", reverse=True)
    return [{k: v for k, v in s.items() if k != "description"} for s in picked][:30]


# ---------------------------------------------------------------------------
# Routes: sermon notes from a link, and the week after
# ---------------------------------------------------------------------------
@router.post("/me/sermons/from-link")
def note_from_link(body: FromLinkIn, today: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    church = _own(body.church_id, user) if body.church_id else None
    try:
        source = _source_for(body.url)
    except web.FetchError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if not source["words"].strip():
        raise HTTPException(status_code=422, detail="There wasn't enough to draft notes from. Try a sermon with captions, or start a blank note.")
    details = source["details"]
    try:
        draft = _llm.with_structured_output(SermonDraft).invoke([
            SystemMessage(_DRAFT_PROMPT),
            HumanMessage(f"Title: {details.get('title', '')}\nChannel: {details.get('channel', '')}\n\n{source['words'][:60_000]}"),
        ])
    except Exception as err:
        log.warning("couldn't draft a sermon note from %s", source["url"], exc_info=True)
        raise HTTPException(status_code=502, detail="Couldn't draft the notes just now. Try again in a moment.") from err
    try:
        preached = date.fromisoformat(details.get("date") or "")
    except ValueError:
        preached = parse_today(today)
    fields = note_from_draft(draft, source, church, preached)
    note_id = str(uuid.uuid4())
    row = {
        **fields,
        "id": note_id,
        "user_id": user.id,
        "blocks": clean_blocks(fields["blocks"], user.id, note_id),
        "church_id": church["id"] if church else None,
        "source_url": source["url"],
    }
    row["passages"] = note_passages(row)
    note = _db(lambda: get_supabase().table("sermon_notes").insert(row).execute().data[0])
    return {**present(note), "from_transcript": source["transcript"]}


@router.get("/me/church/week")
def this_week(today: str | None = None, user: AuthUser = Depends(require_user)) -> dict | None:
    """The most recent sermon of the last eight days, with its steps."""
    day = parse_today(today)
    since = (day - timedelta(days=8)).isoformat()
    rows = _db(lambda: (
        get_supabase().table("sermon_notes").select("id, title, speaker, church, preached_on, passage_ref, passages, blocks, week")
        .eq("user_id", user.id).gte("preached_on", since).lte("preached_on", day.isoformat())
        .order("preached_on", desc=True).limit(1).execute().data
    ))
    if not rows:
        return None
    note = rows[0]
    return {k: v for k, v in note.items() if k not in ("blocks", "week")} | {"steps": week_steps(note)}


@router.get("/me/sermons/{note_id}/week")
def week_of(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    note = _week_note(note_id, user)
    return {k: v for k, v in note.items() if k not in ("blocks", "week")} | {"steps": week_steps(note)}


@router.post("/me/sermons/{note_id}/week")
def update_week(note_id: uuid.UUID, body: WeekIn, user: AuthUser = Depends(require_user)) -> dict:
    note = _week_note(note_id, user)
    week = dict(note.get("week") or {})
    done = dict(week.get("done") or {})
    if body.step and body.done is not None:
        done[body.step] = body.done
    week["done"] = done
    if body.answer is not None:
        week["answer"] = body.answer.strip()
    _db(lambda: get_supabase().table("sermon_notes").update({"week": week}).eq("id", str(note_id)).eq("user_id", user.id).execute())
    note["week"] = week
    return {k: v for k, v in note.items() if k not in ("blocks", "week")} | {"steps": week_steps(note)}


def _week_note(note_id: uuid.UUID, user: AuthUser) -> dict:
    rows = _db(lambda: (
        get_supabase().table("sermon_notes").select("id, title, speaker, church, preached_on, passage_ref, passages, blocks, week")
        .eq("id", str(note_id)).eq("user_id", user.id).limit(1).execute().data
    ))
    if not rows:
        raise HTTPException(status_code=404, detail="That sermon note isn't here anymore.")
    return rows[0]
