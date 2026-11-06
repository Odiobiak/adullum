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
"isLiveNow":true), the channel page names the channel's id, and the public
feed at /feeds/videos.xml?channel_id=... lists its latest videos. A video's
transcript comes from youtube-transcript-api when YouTube allows it (it often
refuses servers in the cloud), and otherwise from the video's own
description.

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
from dataclasses import dataclass, field
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
    "(KHTML, like Gecko) Chrome/126 Safari/537.36 Adullum"
)
TIMEOUT_SECONDS = 8
MAX_REDIRECTS = 4
PAGE_BYTES = 1_500_000
# YouTube's pages carry a lot of script; the live page is about 1.6 MB.
YOUTUBE_PAGE_BYTES = 3_000_000


class FetchError(Exception):
    """A link that couldn't be read, with a message fit to show a person."""


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


def safe_get(url: str, *, max_bytes: int = PAGE_BYTES) -> tuple[str, str]:
    """GET a public page and return (final URL, text), following redirects
    one checked hop at a time and stopping at `max_bytes`."""
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
                        raise FetchError("That page didn't open. Check the link and try again.")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) >= max_bytes:
                            break
                    return url, bytes(body[:max_bytes]).decode(response.encoding or "utf-8", errors="replace")
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


class _PageParser(HTMLParser):
    """Collects what a church page says, without running anything on it."""

    _SKIP = {"script", "style", "noscript", "svg", "template"}

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
        if tag in ("p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section"):
            self._text.append("\n")

    def handle_endtag(self, tag):
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
            self.page.links.append((self._href, " ".join("".join(self._anchor).split())))
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


def parse_page(url: str, html: str) -> Page:
    parser = _PageParser(url)
    parser.feed(html)
    parser.close()
    return parser.page


# Words in a link that point at the pages most likely to hold service times,
# events and announcements.
_USEFUL_PAGE = re.compile(r"visit|new here|im-new|i'm new|about|times|service|worship|events?|calendar|whats-on|what's on|news|announce|contact|location|sunday", re.IGNORECASE)


def useful_pages(page: Page, limit: int = 3) -> list[str]:
    """Same-site links worth reading too, most promising first."""
    host = urlparse(page.url).hostname
    seen, found = {page.url.rstrip("/")}, []
    for href, text in page.links:
        parts = urlparse(href)
        clean = href.split("#")[0].rstrip("/")
        if parts.hostname != host or clean in seen or not parts.scheme.startswith("http"):
            continue
        if _USEFUL_PAGE.search(text) or _USEFUL_PAGE.search(parts.path):
            seen.add(clean)
            found.append(clean)
    return found[:limit]


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


def social_links(links: list[str]) -> dict:
    """The first YouTube, Facebook and podcast links among `links`."""
    out: dict = {}
    for href in links:
        host = (urlparse(href).hostname or "").lower()
        path = urlparse(href).path
        if "youtube.com" in host and re.match(r"^/(@[\w.-]+|channel/UC[\w-]{22}|c/[\w.-]+|user/[\w.-]+)", path):
            out.setdefault("youtube_url", href.split("?")[0].rstrip("/"))
        elif host.endswith("facebook.com") and path.strip("/") and not path.startswith("/sharer"):
            out.setdefault("facebook_url", href.split("?")[0])
        elif host in ("podcasts.apple.com", "open.spotify.com", "anchor.fm") or re.search(r"\.(rss|xml)$|/feed/?$", path):
            out.setdefault("podcast_url", href)
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


def parse_podcast_feed(xml: str) -> list[dict]:
    """Episodes from a podcast's RSS feed, as the feed orders them."""
    root = ElementTree.fromstring(xml)
    episodes = []
    for item in root.iter("item"):
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
            "published": (item.findtext("pubDate") or "").strip()[:16],
            "url": link,
            "description": re.sub(r"<[^>]+>", " ", unescape(item.findtext("description") or ""))[:1500],
        })
    return episodes


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
