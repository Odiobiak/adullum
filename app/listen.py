"""Listen (#church/listen in web/church.js): sermons picked by how someone feels.

Sermons come from two places:
- The person's own churches: their YouTube and podcast feeds
  (app/churches.py::church_sermons).
- Adullum's catalog: a short, hand-chosen list of public sermon podcasts from
  across the Christian traditions (CATALOG below), so Listen has something to
  offer before someone adds a church, and more than one church's voice after.
  Each source is an official feed, checked to open and parse. To add one, find
  its feed (Apple's podcast search gives `feedUrl`), check it parses with
  church_web.parse_podcast_feed within FEED_BYTES, and keep the list balanced
  across traditions, the same way Aquila gives the range of views on a
  disputed question.

Every sermon is tagged once with the seasons it speaks to (weary, anxious,
grateful, grieving, deciding, joyful) by the model, and kept in `sermon_moods`
by the sermon's own id, which holds nothing personal. A request tags one batch
before it answers and leaves the rest to run after the response, saying
`pending` so the page can look again in a moment.

The person filters by season and by source, both as compact dropdowns on the
page. Nothing here is social: no counts, no one else's listening.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app import church_web as web
from app.auth import AuthUser, require_user
from app.churches import _all, _cached_feed, _ensure_channel_id, church_sermons, tag_moods
from app.sermons import references_in

log = logging.getLogger(__name__)

router = APIRouter()

Mood = Literal["weary", "anxious", "grateful", "grieving", "deciding", "joyful"]

# The most of a feed read, and how many of its latest episodes are offered.
FEED_BYTES = 3_000_000
CATALOG_PER_SOURCE = 12
# How many sermons from the person's churches, and from the catalog, a list holds.
MINE_LIMIT = 20
CATALOG_LIMIT = 36
# tag_moods tags this many at a time; one batch runs before answering.
TAG_BATCH = 30


@dataclass(frozen=True)
class CatalogSource:
    key: str          # stable, used in the source filter ("catalog:keller")
    name: str         # who's preaching, as the list shows it
    show: str         # the podcast's own name
    tradition: str
    feed: str


CATALOG: tuple[CatalogSource, ...] = (
    CatalogSource("keller", "Tim Keller", "Gospel in Life", "Presbyterian", "https://podcast.gospelinlife.com/feed.xml"),
    CatalogSource("begg", "Alistair Begg", "Truth For Life", "Reformed Baptist", "https://feeds.feedburner.com/TruthForLifeSermons"),
    CatalogSource("barron", "Bishop Robert Barron", "Sunday Sermons", "Catholic", "https://feed.podbean.com/wordonfire/feed.xml"),
    CatalogSource("reardon", "Fr. Patrick Henry Reardon", "All Saints Homilies", "Orthodox", "https://feeds.ancientfaith.com/AllSaintsHomilies/"),
    CatalogSource("stpeters", "St Peter's Brighton", "Sunday Talks", "Anglican", "https://anchor.fm/s/80ffedc8/podcast/rss"),
    CatalogSource("cymbala", "Brooklyn Tabernacle", "Audio Sermons", "Pentecostal", "https://www.brooklyntabernacle.org/feed/bt-audio"),
    CatalogSource("evans", "Tony Evans", "Sermons", "Baptist", "https://www.oneplace.com/ministries/the-alternative/subscribe/podcast.xml"),
    CatalogSource("stanley", "Charles Stanley", "In Touch", "Southern Baptist", "https://www.omnycontent.com/d/playlist/7237c071-cd56-4495-998a-b23d00f69e8d/f731729c-5ad6-4a16-a48a-b26701569a3b/18a6fa44-525e-45ba-82a5-b26701569a5d/podcast.rss"),
    CatalogSource("caine", "Christine Caine", "Equip & Empower", "Pentecostal", "https://feeds.megaphone.fm/OURNE9825724726"),
    CatalogSource("lloydjones", "Martyn Lloyd-Jones", "MLJ Trust", "Reformed", "https://www.mljtrust.org/sermons/podcast/"),
    CatalogSource("piper", "John Piper", "Desiring God", "Reformed Baptist", "https://feed.desiringgod.org/light-and-truth.rss"),
    # Nigeria. The ministries' own feeds where they publish one (Koinonia
    # Global, Church of God Mission, The Covenant Nation); Apostle Orokpo's and
    # Dr Enenche's are published under their own names.
    CatalogSource("selman", "Apostle Joshua Selman", "Koinonia Global", "Pentecostal, Nigeria", "https://anchor.fm/s/1065bfa84/podcast/rss"),
    CatalogSource("idahosa", "Archbishop Benson Idahosa", "Church of God Mission", "Pentecostal, Nigeria", "https://anchor.fm/s/35ae56ac/podcast/rss"),
    CatalogSource("orokpo", "Apostle Michael Orokpo", "Messages", "Pentecostal, Nigeria", "https://www.spreaker.com/show/6370612/episodes/feed"),
    CatalogSource("oyemade", "Pastor Poju Oyemade", "The Covenant Nation", "Pentecostal, Nigeria", "https://anchor.fm/s/d8d51d98/podcast/rss"),
    CatalogSource("enenche", "Dr Paul Enenche", "Dunamis", "Pentecostal, Nigeria", "https://anchor.fm/s/e7eb6d28/podcast/rss"),
)
_BY_KEY = {s.key: s for s in CATALOG}


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_listen.py)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceFilter:
    """Which sermons a list draws from: the person's churches (all, or one),
    the catalog (all, or one source), or both."""

    mine: bool
    catalog: bool
    church_id: str | None = None
    catalog_key: str | None = None


def parse_source(value: str | None) -> SourceFilter:
    """The page's source filter: "all", "mine", "church:<id>", "catalog" or
    "catalog:<key>". Anything else is a 422, so a stale link says so."""
    value = (value or "all").strip()
    if value == "all":
        return SourceFilter(mine=True, catalog=True)
    if value == "mine":
        return SourceFilter(mine=True, catalog=False)
    if value == "catalog":
        return SourceFilter(mine=False, catalog=True)
    kind, _, rest = value.partition(":")
    if kind == "church" and rest:
        return SourceFilter(mine=True, catalog=False, church_id=rest)
    if kind == "catalog" and rest in _BY_KEY:
        return SourceFilter(mine=False, catalog=True, catalog_key=rest)
    raise HTTPException(status_code=422, detail="That isn't one of the sources here.")


def interleave(groups: list[list[dict]], limit: int) -> list[dict]:
    """One from each source in turn, so no single preacher fills the list."""
    out = [item for row in zip_longest(*groups) for item in row if item is not None]
    return out[:limit]


def matches(item: dict, tags: dict[str, list[str]], mood: str | None) -> bool:
    """Whether a sermon belongs in the list: tagged with the season asked
    for, or, with no season chosen, tagged at all (so it's been looked at)."""
    moods = tags.get(item["id"])
    if moods is None:
        return False
    return mood in moods if mood else True


def untagged(items: list[dict], tags: dict[str, list[str]]) -> list[dict]:
    return [i for i in items if i["id"] not in tags]


def present(item: dict) -> dict:
    """What the page needs of a sermon: everything but its long description."""
    return {k: v for k, v in item.items() if k != "description"}


# ---------------------------------------------------------------------------
# Reading the sources
# ---------------------------------------------------------------------------
def catalog_sermons(source: CatalogSource) -> list[dict]:
    """A catalog source's latest episodes, read through the same cache and
    safe fetching as a church's feed."""
    items = _cached_feed(
        f"catalog:{source.key}",
        lambda: web.parse_podcast_feed(web.safe_get(source.feed, max_bytes=FEED_BYTES)[1])[:CATALOG_PER_SOURCE],
    )
    return [
        {
            **i,
            "church": source.name,
            "show": source.show,
            "tradition": source.tradition,
            "source": f"catalog:{source.key}",
            "catalog": True,
            "refs": references_in(f"{i['title']} {i.get('description', '')}")[:3],
        }
        for i in items
    ]


def _tag_the_rest(items: list[dict]) -> None:
    """Tags what one request didn't get to, a batch at a time, after the
    response has gone. Stops early if a batch makes no progress (the model
    being unavailable), so it never loops."""
    for _ in range(len(items) // TAG_BATCH + 1):
        try:
            tags = tag_moods(items)
        except Exception:
            log.warning("couldn't tag the rest of Listen's sermons", exc_info=True)
            return
        left = untagged(items, tags)
        if not left or len(left) == len(items):
            return
        items = left


@router.get("/me/listen/sources")
def sources(user: AuthUser = Depends(require_user)) -> dict:
    """What the source filter offers: the person's churches and the catalog."""
    try:
        churches = [{"id": c["id"], "name": c["name"]} for c in _all(user)]
    except HTTPException:
        churches = []  # the Church tab isn't set up yet; the catalog still is
    return {
        "churches": churches,
        "catalog": [{"key": s.key, "name": s.name, "show": s.show, "tradition": s.tradition} for s in CATALOG],
    }


@router.get("/me/listen")
def listen(
    background: BackgroundTasks,
    mood: Mood | None = Query(default=None),
    source: str = Query(default="all"),
    user: AuthUser = Depends(require_user),
) -> dict:
    """Sermons that speak to `mood` (any season when it's left out), from the
    person's churches (newest first) and the catalog (one source at a time,
    in turn). `pending` says some are still being sorted into seasons."""
    pick = parse_source(source)

    mine: list[dict] = []
    if pick.mine:
        try:
            churches = _all(user)
        except HTTPException:
            churches = []
        if pick.church_id:
            churches = [c for c in churches if c["id"] == pick.church_id]
        churches = [_ensure_channel_id(c, user) for c in churches]
        with ThreadPoolExecutor(max_workers=4) as pool:
            mine = [s for batch in pool.map(church_sermons, churches) for s in batch[:15]]
        mine.sort(key=lambda s: s.get("published") or "", reverse=True)

    catalog_groups: list[list[dict]] = []
    if pick.catalog:
        chosen = [_BY_KEY[pick.catalog_key]] if pick.catalog_key else list(CATALOG)
        with ThreadPoolExecutor(max_workers=6) as pool:
            catalog_groups = list(pool.map(catalog_sermons, chosen))

    everything = mine + [i for group in catalog_groups for i in group]
    # tag_moods reads every tag already kept and sorts the first batch of the
    # rest (the person's own churches come first in `everything`); whatever
    # is left is sorted after the response.
    tags = tag_moods(everything) if everything else {}
    left = untagged(everything, tags)
    if left:
        background.add_task(_tag_the_rest, left)

    mine_out = [present(i) for i in mine if matches(i, tags, mood)][:MINE_LIMIT]
    catalog_out = interleave([[present(i) for i in group if matches(i, tags, mood)] for group in catalog_groups], CATALOG_LIMIT)
    return {"mine": mine_out, "catalog": catalog_out, "pending": bool(left)}
