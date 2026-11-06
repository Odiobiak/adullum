"""The Bible reader: translations, books, and whole chapters to read.

Everything here is public and read-only, so a guest can read without an
account. Notes on verses are personal and live in app/notes.py.

Which translations a person can pick comes from the database, not just the
registry below: a translation is offered only once at least one of its verses
has been ingested (scripts/fetch_translation.py, then scripts/ingest.py), so
the picker never offers a Bible that would come back empty. That check is
cached for a few minutes because the answer only changes when someone runs
an ingest.
"""

import logging
import time
from threading import Lock

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.connections import book_meta
from app.db import get_supabase
from app.plan import BOOK_CHAPTER_COUNTS, BOOK_ORDER
from app.retrieval import canonical_book

log = logging.getLogger(__name__)

router = APIRouter()

# Public-domain translations only (see CLAUDE.md, "Product constraints").
# Order here is the order the picker shows them in.
TRANSLATIONS: dict[str, dict] = {
    "BSB": {"name": "Berean Standard Bible", "about": "A modern, readable translation, in the public domain since 2023."},
    "KJV": {"name": "King James Version", "about": "The 1769 Oxford text of the 1611 translation."},
    "WEB": {"name": "World English Bible", "about": "A modern update of the ASV, written to be read aloud."},
    "ASV": {"name": "American Standard Version", "about": "The 1901 revision, known for close, literal wording."},
}

_AVAILABLE_TTL_SECONDS = 300
_available: tuple[float, list[str]] | None = None
_available_lock = Lock()


def _loaded(code: str) -> bool:
    rows = get_supabase().table("verses").select("id").eq("translation", code).limit(1).execute().data
    return bool(rows)


def available_translations() -> list[str]:
    """Codes of the registered translations that have verses in the database,
    in registry order. The default translation is always included, so a
    database hiccup degrades to "just the default" rather than an empty picker.
    """
    global _available
    with _available_lock:
        if _available and time.monotonic() - _available[0] < _AVAILABLE_TTL_SECONDS:
            return _available[1]
    codes: list[str] = []
    try:
        codes = [code for code in TRANSLATIONS if _loaded(code)]
    except Exception:
        log.warning("checking which translations are loaded failed", exc_info=True)
    if settings.default_translation not in codes:
        codes.insert(0, settings.default_translation)
    with _available_lock:
        _available = (time.monotonic(), codes)
    return codes


def neighbours(book: str, chapter: int) -> tuple[dict | None, dict | None]:
    """The chapters either side of this one in canonical order, crossing book
    boundaries (Malachi 4 is followed by Matthew 1). None at either end."""
    i = BOOK_ORDER.index(book)
    prev = next_ = None
    if chapter > 1:
        prev = {"book": book, "chapter": chapter - 1}
    elif i > 0:
        before = BOOK_ORDER[i - 1]
        prev = {"book": before, "chapter": BOOK_CHAPTER_COUNTS[before]}
    if chapter < BOOK_CHAPTER_COUNTS[book]:
        next_ = {"book": book, "chapter": chapter + 1}
    elif i < len(BOOK_ORDER) - 1:
        next_ = {"book": BOOK_ORDER[i + 1], "chapter": 1}
    return prev, next_


def resolve_chapter(book: str, chapter: int) -> str:
    """Canonical book name for a requested chapter, or a 404 that says which
    part was wrong."""
    # Reader links write "Song-of-Solomon", hyphens for spaces.
    canonical = canonical_book(book.replace("-", " "))
    if not canonical:
        raise HTTPException(status_code=404, detail=f"There's no book called {book!r} in the Bible.")
    if not 1 <= chapter <= BOOK_CHAPTER_COUNTS[canonical]:
        raise HTTPException(
            status_code=404,
            detail=f"{canonical} has {BOOK_CHAPTER_COUNTS[canonical]} chapters.",
        )
    return canonical


@router.get("/bible/translations")
def translations() -> dict:
    return {
        "default": settings.default_translation,
        "translations": [
            {"code": code, **TRANSLATIONS.get(code, {"name": code, "about": ""})}
            for code in available_translations()
        ],
    }


@router.get("/bible/books")
def books() -> list[dict]:
    """The 66 books in canonical order with their chapter counts. Static (the
    versification is the same in every translation offered here), so the
    client can draw the book picker without waiting on the database."""
    return [{"name": b, "chapters": n, **book_meta(b)} for b, n in BOOK_CHAPTER_COUNTS.items()]


@router.get("/bible/chapter")
def chapter(book: str, chapter: int, translation: str | None = None) -> dict:
    canonical = resolve_chapter(book, chapter)
    translation = (translation or settings.default_translation).upper()
    if translation not in TRANSLATIONS:
        raise HTTPException(status_code=404, detail=f"{translation} isn't one of the translations offered here.")
    rows = (
        get_supabase()
        .table("verses")
        .select("verse, text")
        .eq("translation", translation)
        .eq("book", canonical)
        .eq("chapter", chapter)
        .order("verse")
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"{translation} hasn't been loaded yet.")
    prev, next_ = neighbours(canonical, chapter)
    return {
        "book": canonical,
        "chapter": chapter,
        "translation": translation,
        "verses": rows,
        "prev": prev,
        "next": next_,
        **book_meta(canonical),
    }
