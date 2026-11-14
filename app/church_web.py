"""Reading the public web for the Church tab: church websites, YouTube
channels and podcast feeds (used by app/churches.py).

Everything here fetches a link a person pasted, so every fetch goes through
`safe_get`, which only follows http(s) links to public addresses. A pasted
link can never make the server reach something on its own network (a
database, a cloud metadata address, localhost). Redirects are followed one
hop at a time and each hop is checked the same way, and every response is
cut off at a size limit.

No YouTube API key is needed. A channel's live page says whether it's live
(its canonical link becomes the live video's watch page, alongside
"isLiveNow":true), and the channel page names the channel's id. Its latest
videos come from the public feed at /feeds/videos.xml?channel_id=... when
that answers (it has been answering 404 for every channel), and otherwise
from the channel's own Videos and Live pages, which carry the same list as
JSON (`parse_channel_page`). A video's transcript comes from
youtube-transcript-api when YouTube allows it (it often refuses servers in
the cloud), and otherwise from the video's own description.

The parsing helpers are pure functions over text, so tests/test_churches.py
covers them without the network.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse
from xml.etree import ElementTree

import httpx

log = logging.getLogger(__name__)

# A browser-like agent, since some church sites and YouTube serve a bare
# client something different (or nothing at all).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36 Adullam"
)
TIMEOUT_SECONDS = 8
MAX_REDIRECTS = 4
# Generous, since a site's markup can be heavy before its words begin (one
# church's homepage opens with a 1.5 MB inline drawing).
PAGE_BYTES = 3_000_000
# YouTube's pages carry a lot of script; the live page is about 1.6 MB.
YOUTUBE_PAGE_BYTES = 3_000_000
# The most of a podcast feed ever read; read_podcast_feed usually stops far sooner.
FEED_BYTES = 3_000_000


class FetchError(Exception):
    """A link that couldn't be read, with a message fit to show a person."""


def _status_message(status: int) -> str:
    """What to tell a person when a page answers with an error."""
    if status in (401, 403, 429, 503):
        # Usually a bot check in front of the site (Cloudflare and the like).
        return "That site doesn't let Adullam read it. You can enter the details yourself instead."
    if status in (404, 410):
        return "That page wasn't found. Check the link and try again."
    return "That page didn't open. Check the link and try again."


# ---------------------------------------------------------------------------
# Fetching, safely
# ---------------------------------------------------------------------------
def _is_public(host: str) -> bool:
    """True when every address `host` resolves to is on the public internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        if (address.is_private or address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_reserved or address.is_unspecified):
            return False
    return bool(infos)


def normalise_url(url: str) -> str:
    """A pasted link as a full https URL ("harvest.org" -> "https://harvest.org")."""
    url = (url or "").strip()
    if url and not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "https://" + url
    return url


def check_url(url: str) -> str:
    """The URL if it's an http(s) link to a public host, or a FetchError."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise FetchError("That doesn't look like a web link.")
    if parts.username or parts.password:
        raise FetchError("That link can't be read.")
    if not _is_public(parts.hostname):
        raise FetchError("That link can't be read.")
    return url


def safe_get(url: str, *, max_bytes: int = PAGE_BYTES, enough: Callable[[bytes], bool] | None = None) -> tuple[str, str]:
    """GET a public page and return (final URL, text), following redirects
    one checked hop at a time and stopping at `max_bytes`, or sooner once
    `enough` says what's been read will do."""
    url = check_url(normalise_url(url))
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False, headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = check_url(urljoin(url, response.headers.get("location", "")))
                        continue
                    if response.status_code >= 400:
                        raise FetchError(_status_message(response.status_code))
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= max_bytes or (enough and enough(body)):
                            break
                    return url, bytes(body[:max_bytes]).decode(response.encoding or "utf-8", errors="replace")
            except httpx.TimeoutException as err:
                raise FetchError("That site took too long to answer. Try again in a moment.") from err
            except httpx.HTTPError as err:
                raise FetchError("That page didn't open. Check the link and try again.") from err
    raise FetchError("That link kept redirecting.")


# ---------------------------------------------------------------------------
# Reading a web page
# ---------------------------------------------------------------------------
@dataclass
class Page:
    url: str
    title: str = ""
    site_name: str = ""
    description: str = ""
    text: str = ""
    links: list[tuple[str, str]] = field(default_factory=list)  # (absolute href, anchor text)
    json_ld: list[dict] = field(default_factory=list)
    feeds: list[str] = field(default_factory=list)
    # YouTube and podcast links named anywhere in the markup, scripts
    # included, for sites whose footer links are drawn by JavaScript.
    mentions: list[str] = field(default_factory=list)


class _PageParser(HTMLParser):
    """Collects what a church page says, without running anything on it."""

    _SKIP = {"script", "style", "noscript", "svg", "template"}
    # Tags that start a new line of text. Every other tag is a word break, so
    # a menu of links reads "Sermons Locations About", not "SermonsLocationsAbout".
    _BLOCK = {
        "p", "div", "li", "br", "hr", "tr", "section", "article", "header", "footer", "nav", "main", "aside",
        "ul", "ol", "table", "dl", "dt", "dd", "address", "blockquote", "figure", "figcaption", "form",
        "h1", "h2", "h3", "h4", "h5", "h6",
    }

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.page = Page(url=base)
        self._skip = 0
        self._in_title = False
        self._in_ld = False
        self._ld = []
        self._href: str | None = None
        self._anchor: list[str] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_ld = True
            self._ld = []
            return
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key == "og:site_name":
                self.page.site_name = a.get("content", "").strip()
            elif key in ("description", "og:description") and not self.page.description:
                self.page.description = a.get("content", "").strip()
        elif tag == "link" and "alternate" in a.get("rel", "").lower() and "xml" in a.get("type", "").lower():
            self.page.feeds.append(urljoin(self.page.url, a.get("href", "")))
        elif tag == "a" and a.get("href"):
            self._href = urljoin(self.page.url, a["href"])
            self._anchor = []
        self._text.append("\n" if tag in self._BLOCK else " ")

    def handle_endtag(self, tag):
        self._text.append("\n" if tag in self._BLOCK else " ")
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try:
                data = json.loads("".join(self._ld))
            except ValueError:
                return
            items = data if isinstance(data, list) else [data]
            for item in items:
                if isinstance(item, dict):
                    self.page.json_ld.extend(item.get("@graph") or [item])
            return
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._href:
            self.page.links.append((self._href, " ".join(" ".join(self._anchor).split())))
            self._href = None

    def handle_data(self, data):
        if self._in_ld:
            self._ld.append(data)
            return
        if self._skip:
            return
        if self._in_title:
            self.page.title += data
        if self._href is not None:
            self._anchor.append(data)
        self._text.append(data)

    def close(self):
        super().close()
        lines = (" ".join(line.split()) for line in "".join(self._text).split("\n"))
        self.page.text = "\n".join(line for line in lines if line)
        self.page.title = " ".join(self.page.title.split())


# YouTube and podcast addresses as they appear in markup or in a script's
# JSON (where "/" is often written "\/").
_MEDIA_LINK = re.compile(
    r"https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be|podcasts\.apple\.com|open\.spotify\.com|anchor\.fm)/[^\s\"'<>\\)]+"
)


def parse_page(url: str, html: str) -> Page:
    parser = _PageParser(url)
    parser.feed(html)
    parser.close()
    page = parser.page
    page.mentions = list(dict.fromkeys(_MEDIA_LINK.findall(html.replace("\\/", "/"))))[:50]
    return page


def _site(host: str | None) -> str:
    return (host or "").lower().removeprefix("www.")


# What a link's words or path say about the page behind it, best first: when
# the church meets, then what's coming up, then who they are.
_PAGE_HINTS = (
    (3, re.compile(r"(plan[ _-]?(a|your)?[ _-]?)?visit|new[ _-]?here|i'?m[ _-]?new|first[ _-]?time|services?|times|sundays?|worship|gatherings?|locations?|campus|find[ _-]us|join[ _-]us", re.IGNORECASE)),
    (2, re.compile(r"events?|calendar|whats[ _-]?on|what's on|happening|news|announce|notices?|bulletin", re.IGNORECASE)),
    (1, re.compile(r"about|contact|who[ _-]we[ _-]are|our[ _-]story|our[ _-](pastors|team|leaders)|leadership|staff", re.IGNORECASE)),
)
_NOT_A_PAGE = re.compile(r"\.(pdf|jpe?g|png|gif|webp|mp3|m4a|mp4|zip|docx?)$", re.IGNORECASE)


def _page_score(path: str, text: str) -> int:
    """How promising a link is. In its path a hint counts only at the start
    of a part ("/about-us", "/Services.aspx"), so a news story's long slug
    that merely mentions a pastor doesn't count. A long anchor is usually a
    card's whole blurb, so only short ones count by their words."""
    parts = [p for p in path.split("/") if p]
    words = text if len(text) <= 40 else ""
    return max((score for score, hint in _PAGE_HINTS if any(hint.match(p) for p in parts) or hint.search(words)), default=0)


def useful_pages(page: Page, limit: int = 3) -> list[str]:
    """Same-site links worth reading too: the best of each kind first (times,
    then events, then about), then the next best. Within a kind a shallower
    page wins ("/news" over one story under it), then the page's own order."""
    home = _site(urlparse(page.url).hostname)
    seen, scored = {page.url.split("#")[0].rstrip("/")}, []
    for href, text in page.links:
        parts = urlparse(href)
        clean = href.split("#")[0].rstrip("/")
        if (_site(parts.hostname) != home or clean in seen or parts.scheme not in ("http", "https")
                or _NOT_A_PAGE.search(parts.path)):
            continue
        score = _page_score(parts.path, text)
        if score:
            seen.add(clean)
            depth = len([p for p in parts.path.split("/") if p])
            scored.append((-score, depth, len(scored), clean))
    scored.sort()
    picked: list[str] = []
    for tier in (3, 2, 1):
        best = next((url for score, _, _, url in scored if -score == tier), None)
        if best:
            picked.append(best)
    rest = [url for *_, url in scored if url not in picked]
    return (picked + rest)[:limit]


def site_text(pages: list[Page], limit: int) -> str:
    """The pages' words for the model, at most `limit` characters. A long line
    already seen on an earlier page (the menu, the footer) is left out, and
    each page gets a fair share, a short page's unused share passing on, so
    the visit and events pages are read and not just the homepage."""
    seen: set[str] = set()
    bodies = []
    for page in pages:
        lines = []
        for line in page.text.split("\n"):
            key = line.lower()
            if len(line) >= 20 and key in seen:
                continue
            lines.append(line)
        seen.update(line.lower() for line in lines if len(line) >= 20)
        bodies.append(f"Page: {page.url}\nTitle: {page.title}\n" + "\n".join(lines))
    out, left = [], limit
    for i, body in enumerate(bodies):
        piece = body[: left // (len(bodies) - i)]
        out.append(piece)
        left -= len(piece)
    return "\n\n".join(out)


# ---------------------------------------------------------------------------
# Structured data, links and feeds
# ---------------------------------------------------------------------------
_PLACE_TYPES = {"church", "placeofworship", "organization", "localbusiness", "religiousorganization"}


def _types(item: dict) -> set[str]:
    kind = item.get("@type") or []
    return {str(k).lower() for k in (kind if isinstance(kind, list) else [kind])}


def _address(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = [value.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "addressCountry")]
        return ", ".join(str(p).strip() for p in parts if p and isinstance(p, str))
    return ""


def from_json_ld(items: list[dict]) -> dict:
    """The church's name, address, city, links and events from schema.org data."""
    out: dict = {"events": [], "same_as": []}
    for item in items:
        kinds = _types(item)
        if kinds & _PLACE_TYPES and not out.get("name"):
            out["name"] = str(item.get("name") or "").strip()
            address = item.get("address")
            out["address"] = _address(address)
            if isinstance(address, dict) and isinstance(address.get("addressLocality"), str):
                out["city"] = address["addressLocality"].strip()
            same = item.get("sameAs") or []
            out["same_as"] = [s for s in (same if isinstance(same, list) else [same]) if isinstance(s, str)]
        if "event" in kinds and item.get("name") and item.get("startDate"):
            start = str(item["startDate"])
            out["events"].append({"title": str(item["name"]).strip()[:120], "date": start[:10], "time": start[11:16] or None})
    return out


# A channel's own address: /@handle, /channel/UC..., /c/name, /user/name, or
# the old bare /name. A link to one of its tabs (/@handle/videos) is cut back
# to the channel, since "/live" is added to it to check for a stream.
_CHANNEL_PATH = re.compile(r"^/(@[\w.-]+|channel/UC[\w-]{22}|c/[\w.-]+|user/[\w.-]+|[A-Za-z0-9][\w.-]{2,})(?:/|$)")
# First path parts that are YouTube's own pages, never a channel's old name.
_YOUTUBE_PAGES = {
    "watch", "embed", "shorts", "results", "playlist", "feed", "redirect", "live", "hashtag", "premium", "music",
    "kids", "gaming", "account", "signin", "logout", "about", "howyoutubeworks", "ads", "creators", "t",
    "attribution_link", "subscription_manager", "supported_browsers", "new", "trending", "post", "source",
    "iframe_api", "player_api", "s", "img", "yts", "sw.js", "favicon.ico", "robots.txt",
}
# Podcast hosts whose links are, or lead to, a readable feed. Spotify's lead
# nowhere readable, so a Spotify link is kept only when there's nothing better.
_FEED_HOSTS = ("anchor.fm", "podbean.com", "buzzsprout.com", "libsyn.com", "simplecast.com", "megaphone.fm",
               "captivate.fm", "transistor.fm", "spreaker.com", "omnycontent.com", "feedburner.com", "subsplash.com")


def youtube_channel_url(href: str) -> str | None:
    """The channel a YouTube link is the home of, or None for any other link."""
    parts = urlparse(href)
    if not (parts.hostname or "").lower().endswith("youtube.com"):
        return None
    match = _CHANNEL_PATH.match(parts.path)
    if not match or match.group(1).lower() in _YOUTUBE_PAGES:
        return None
    return f"https://www.youtube.com/{match.group(1)}"


def _podcast_rank(host: str, path: str) -> int:
    """How readable a podcast link is likely to be, or 0 for no podcast."""
    if host == "podcasts.apple.com":
        return 4
    if re.search(r"\.(rss|xml)$|/(podcast/)?rss/?$|/feed/podcast", path):
        return 3
    if any(host == h or host.endswith("." + h) for h in _FEED_HOSTS):
        return 2
    return 1 if host == "open.spotify.com" and path.startswith("/show/") else 0


def social_links(links: list[str]) -> dict:
    """The first YouTube channel, Facebook page and best podcast among
    `links`, plus a YouTube video (`youtube_video`) to find the channel from
    when no channel is linked."""
    out: dict = {}
    podcast_rank = 0
    for href in links:
        parts = urlparse(href)
        host, path = (parts.hostname or "").lower(), parts.path
        channel = youtube_channel_url(href)
        if channel:
            out.setdefault("youtube_url", channel)
        elif youtube_video_id(href):
            out.setdefault("youtube_video", href)
        elif host.endswith("facebook.com") and path.strip("/") and not re.match(r"^/(sharer|share|plugins|dialog|tr)\b", path):
            out.setdefault("facebook_url", href.split("?")[0])
        elif (rank := _podcast_rank(host, path)) > podcast_rank:
            podcast_rank = rank
            out["podcast_url"] = href.split("?")[0] if host == "open.spotify.com" else href
    return out


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------
_VIDEO_ID = re.compile(r"^[\w-]{11}$")


def youtube_video_id(url: str) -> str | None:
    """The video id in a YouTube watch, share, live or shorts link."""
    parts = urlparse(normalise_url(url))
    host = (parts.hostname or "").lower()
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        candidate = parse_qs(parts.query).get("v", [""])[0]
        match = re.match(r"^/(?:live|shorts|embed)/([\w-]{11})", parts.path)
        if match:
            candidate = match.group(1)
    else:
        return None
    return candidate if _VIDEO_ID.match(candidate or "") else None


def is_youtube(url: str | None) -> bool:
    host = (urlparse(normalise_url(url or "")).hostname or "").lower()
    return host == "youtu.be" or host.endswith("youtube.com")


def youtube_channel_id(html: str) -> str | None:
    match = (re.search(r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"', html)
             or re.search(r"feeds/videos\.xml\?channel_id=(UC[\w-]{22})", html)
             or re.search(r'"(?:channelId|externalId)":"(UC[\w-]{22})"', html))
    return match.group(1) if match else None


def youtube_live_video(html: str) -> str | None:
    """The video id when a channel's /live page shows a stream that's live now."""
    if '"isLiveNow":true' not in html:
        return None
    match = re.search(r'<link rel="canonical" href="https://www\.youtube\.com/watch\?v=([\w-]{11})"', html)
    return match.group(1) if match else None


def channel_live_url(channel_url: str) -> str:
    return channel_url.rstrip("/") + "/live"


_ATOM = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}


def parse_youtube_feed(xml: str) -> list[dict]:
    """Videos from a channel's public feed, newest first, without Shorts."""
    root = ElementTree.fromstring(xml)
    videos = []
    for entry in root.findall("a:entry", _ATOM):
        video_id = entry.findtext("yt:videoId", default="", namespaces=_ATOM)
        link = entry.find("a:link", _ATOM)
        href = link.get("href", "") if link is not None else ""
        if not video_id or "/shorts/" in href:
            continue
        videos.append({
            "id": f"yt:{video_id}",
            "video_id": video_id,
            "title": entry.findtext("a:title", default="", namespaces=_ATOM).strip(),
            "published": entry.findtext("a:published", default="", namespaces=_ATOM)[:10],
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "description": (entry.findtext("media:group/media:description", default="", namespaces=_ATOM) or "")[:1500],
        })
    return videos


# "2 days ago", "Streamed 3 weeks ago", and the short forms "2d ago", "1mo ago".
_AGO = re.compile(r"(\d+)\s*(years?|yrs?|y|months?|mos?|weeks?|wks?|w|days?|d|hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\s+ago", re.IGNORECASE)
_AGO_DAYS = {"y": 365, "mo": 30, "w": 7, "d": 1}


def days_ago(label: str) -> int | None:
    """How many days back YouTube's "N units ago" is, or None without one."""
    match = _AGO.search(label or "")
    if not match:
        return None
    unit = match.group(2).lower()
    per = next((days for prefix, days in _AGO_DAYS.items() if unit.startswith(prefix)), 0)
    return int(match.group(1)) * per


def _initial_data(html: str) -> dict | None:
    """The JSON a YouTube page draws itself from."""
    start = html.find("ytInitialData = ")
    if start < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(html, start + len("ytInitialData = "))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _each(node, key: str):
    """Every value stored under `key` anywhere in a JSON tree."""
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if key in item:
                yield item[key]
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def _texts(node) -> list[str]:
    """Every piece of text in a JSON tree, its spoken label first."""
    found = []
    for item in _each(node, "accessibilityLabel"):
        if isinstance(item, str):
            found.append(item)
    for item in _each(node, "content"):
        if isinstance(item, str):
            found.append(item)
    return found


def parse_channel_page(html: str, today: date) -> list[dict]:
    """Videos on a channel's Videos or Live page, newest first, in the same
    shape as parse_youtube_feed. The page gives only an age ("2 days ago"),
    so `published` is worked back from `today`. A stream that's live or
    still to come has no age yet and is left out (live is checked apart)."""
    data = _initial_data(html)
    if not data:
        return []
    videos, seen = [], set()
    for lockup in _each(data, "lockupViewModel"):
        if not isinstance(lockup, dict) or lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            continue
        video_id = lockup.get("contentId") or ""
        if not _VIDEO_ID.match(video_id) or video_id in seen:
            continue
        meta = (lockup.get("metadata") or {}).get("lockupMetadataViewModel") or {}
        title = ((meta.get("title") or {}).get("content") or "").strip()
        ago = next((d for d in map(days_ago, _texts(meta.get("metadata"))) if d is not None), None)
        if not title or ago is None:
            continue
        badges = [b.get("text", "") for b in _each(lockup.get("contentImage") or {}, "thumbnailBadgeViewModel") if isinstance(b, dict)]
        seen.add(video_id)
        videos.append({
            "id": f"yt:{video_id}",
            "video_id": video_id,
            "title": title,
            "published": (today - timedelta(days=ago)).isoformat(),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "length": next((b for b in badges if re.match(r"^\d+(:\d\d)+$", b)), ""),
            "description": "",
        })
    return videos


def channel_videos(channel_id: str, today: date, limit: int = 20) -> list[dict]:
    """A channel's latest videos and past streams, from its own pages, newest
    first. Many churches post whole services as streams, so Live counts too."""
    found: dict[str, dict] = {}
    for tab in ("videos", "streams"):
        try:
            _, html = safe_get(f"https://www.youtube.com/channel/{channel_id}/{tab}", max_bytes=YOUTUBE_PAGE_BYTES)
        except FetchError:
            continue
        for video in parse_channel_page(html, today):
            found.setdefault(video["video_id"], video)
    return sorted(found.values(), key=lambda v: v["published"], reverse=True)[:limit]


def read_podcast_feed(url: str, limit: int, *, max_bytes: int = FEED_BYTES) -> list[dict]:
    """A podcast's latest `limit` episodes. Reading stops once they've arrived,
    since a feed can hold years of episodes (several MB) and only its top is
    wanted."""
    closing = b"</item>"
    _, xml = safe_get(url, max_bytes=max_bytes, enough=lambda body: body.count(closing) >= limit)
    return parse_podcast_feed(xml, limit)


def _feed_date(value: str | None) -> str:
    """An RSS date ("Sun, 09 Nov 2026 10:00:00 GMT") as YYYY-MM-DD, or ""."""
    value = (value or "").strip()
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        match = re.match(r"\d{4}-\d{2}-\d{2}", value)
        return match.group(0) if match else ""


def _feed_length(value: str | None) -> str:
    """An episode's itunes:duration ("2712", "45:12", "01:05:00") as "h:mm:ss"
    or "m:ss", the way YouTube writes a length, or ""."""
    value = (value or "").strip()
    if value.isdigit():
        return clock(int(value)) if int(value) else ""
    parts = value.split(":")
    if 2 <= len(parts) <= 3 and all(p.isdigit() for p in parts):
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return clock(seconds) if seconds else ""
    return ""


_ITUNES = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"


def parse_podcast_feed(xml: str, limit: int | None = None) -> list[dict]:
    """Episodes from a podcast's RSS feed, as the feed orders them. A feed
    cut off part way (read_podcast_feed stops early) gives the episodes that
    arrived whole."""
    parser = ElementTree.XMLPullParser(events=("end",))
    parser.feed(xml)
    episodes = []
    for _, item in parser.read_events():
        if item.tag != "item":
            continue
        if limit is not None and len(episodes) >= limit:
            break
        enclosure = item.find("enclosure")
        audio = enclosure.get("url", "") if enclosure is not None else ""
        link = (item.findtext("link") or audio or "").strip()
        if not link:
            continue
        guid = (item.findtext("guid") or link).strip()
        episodes.append({
            # A stable id (Python's own hash() changes between runs).
            "id": "pod:" + hashlib.sha1(guid.encode()).hexdigest()[:16],
            "audio_url": audio,
            "title": (item.findtext("title") or "").strip(),
            "published": _feed_date(item.findtext("pubDate")),
            "length": _feed_length(item.findtext(f"{_ITUNES}duration")),
            "url": link,
            "description": re.sub(r"<[^>]+>", " ", unescape(item.findtext("description") or ""))[:1500],
        })
    return episodes


def video_channel_id(html: str) -> str | None:
    """The channel a watch page's own video belongs to (not a suggested one's)."""
    match = re.search(r'"videoDetails":\{"videoId":"[\w-]{11}".*?"channelId":"(UC[\w-]{22})"', html)
    return match.group(1) if match else None


def watch_page_details(html: str) -> dict:
    """A video's title, channel, upload date and description from its watch page."""
    def field_(pattern: str) -> str:
        match = re.search(pattern, html)
        if not match:
            return ""
        try:
            return json.loads(f'"{match.group(1)}"')
        except ValueError:
            return match.group(1)
    return {
        "title": field_(r'"title":"((?:[^"\\]|\\.)*)","lengthSeconds"'),
        "channel": field_(r'"ownerChannelName":"((?:[^"\\]|\\.)*)"'),
        "date": field_(r'"(?:uploadDate|publishDate)":"(\d{4}-\d{2}-\d{2})'),
        "description": field_(r'"shortDescription":"((?:[^"\\]|\\.)*)"'),
    }


def video_transcript(video_id: str, max_chars: int = 60_000) -> list[tuple[float, str]] | None:
    """The video's captions as (seconds, text), or None when YouTube won't give
    them to this server."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return None
    try:
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=["en", "en-US", "en-GB"])
    except Exception:
        log.info("no transcript for %s", video_id, exc_info=True)
        return None
    lines, total = [], 0
    for snippet in fetched:
        text = " ".join(snippet.text.split())
        if not text or text.startswith("["):
            continue
        lines.append((float(snippet.start), text))
        total += len(text)
        if total >= max_chars:
            break
    return lines or None


def clock(seconds: float) -> str:
    """Seconds into a video as "m:ss" or "h:mm:ss"."""
    s = int(seconds)
    hours, rest = divmod(s, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"
