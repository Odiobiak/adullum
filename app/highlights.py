"""Highlights a person paints on verses while reading the Bible.

One colour per verse, pinned to book, chapter and verse rather than to a
translation (the same rule as app/notes.py), so a verse highlighted in the KJV
is still highlighted when the BSB is open. Each row keeps the verse text of
the translation it was made in, read from the verses table here on the
server, so My notes in the Bible can list highlights without a lookup per verse.

Stored one row per verse so overlapping highlights never conflict: painting a
range simply sets the colour of each verse in it. The list view joins runs of
neighbouring verses that share a colour back into one passage.

Same rule as app/cave.py: every query filters by the signed-in user's id.
"""

from itertools import groupby
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field, model_validator

from app.auth import AuthUser, require_user
from app.bible import resolve_chapter
from app.cave import _db_call
from app.db import get_supabase
from app.plan import BOOK_CHAPTER_COUNTS

router = APIRouter()

Color = Literal["gold", "green", "blue", "rose"]

_SETUP_HINT = (
    "Highlights aren't set up on the database yet. Run "
    "supabase/migrations/20261109_prayers_highlights_memorize.sql in the Supabase SQL editor."
)

_BOOK_ORDER = {book: i for i, book in enumerate(BOOK_CHAPTER_COUNTS)}

# A highlight covers at most one chapter's worth of selection at a time.
MAX_VERSES = 40


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


class VerseRange(BaseModel):
    book: str = Field(max_length=40)
    chapter: int = Field(ge=1, le=150)
    verse_start: int = Field(ge=1, le=176)
    verse_end: int | None = Field(default=None, ge=1, le=176)

    @model_validator(mode="after")
    def _range(self):
        if self.verse_end is None:
            self.verse_end = self.verse_start
        if self.verse_end < self.verse_start:
            raise ValueError("verse_end comes before verse_start")
        if self.verse_end - self.verse_start + 1 > MAX_VERSES:
            raise ValueError(f"Highlight up to {MAX_VERSES} verses at a time.")
        return self


class HighlightIn(VerseRange):
    color: Color
    translation: str = Field(default="", max_length=12)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_highlights.py)
# ---------------------------------------------------------------------------
def group_highlights(rows: list[dict]) -> list[dict]:
    """Join neighbouring verses of one chapter that share a colour into one
    passage ("John 3:16" and "John 3:17", both gold, become "John 3:16-17"),
    most recently made first."""
    ordered = sorted(rows, key=lambda r: (_BOOK_ORDER.get(r["book"], 99), r["chapter"], r["verse"]))
    passages: list[dict] = []
    for _, chapter_rows in groupby(ordered, key=lambda r: (r["book"], r["chapter"])):
        run: list[dict] = []
        for row in chapter_rows:
            if run and (row["verse"] != run[-1]["verse"] + 1 or row["color"] != run[-1]["color"]):
                passages.append(_passage(run))
                run = []
            run.append(row)
        if run:
            passages.append(_passage(run))
    return sorted(passages, key=lambda p: p["created_at"] or "", reverse=True)


def _passage(run: list[dict]) -> dict:
    first, last = run[0], run[-1]
    verses = f"{first['verse']}" if first is last else f"{first['verse']}-{last['verse']}"
    return {
        "ref": f"{first['book']} {first['chapter']}:{verses}",
        "book": first["book"],
        "chapter": first["chapter"],
        "verse_start": first["verse"],
        "verse_end": last["verse"],
        "color": first["color"],
        "translation": first.get("translation") or "",
        "text": " ".join(r["verse_text"] for r in run if r.get("verse_text")),
        "created_at": max((r.get("created_at") or "") for r in run),
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/me/highlights")
def list_highlights(
    book: str | None = None,
    chapter: int | None = Query(default=None, ge=1, le=150),
    user: AuthUser = Depends(require_user),
) -> list[dict]:
    """With a book and chapter, that chapter's highlighted verses
    ([{verse, color}], what the reader paints). Without, every highlight
    grouped into passages, for My notes in the Bible."""
    db = get_supabase()
    if book and chapter:
        canonical = resolve_chapter(book, chapter)
        return _db(
            lambda: db.table("verse_highlights").select("verse, color").eq("user_id", user.id)
            .eq("book", canonical).eq("chapter", chapter).order("verse").execute().data
        )
    rows = _db(
        lambda: db.table("verse_highlights")
        .select("book, chapter, verse, color, translation, verse_text, created_at")
        .eq("user_id", user.id).limit(2000).execute().data
    )
    return group_highlights(rows)


@router.put("/me/highlights")
def paint(body: HighlightIn, user: AuthUser = Depends(require_user)) -> dict:
    """Colour every verse in the range, replacing any colour it had."""
    canonical = resolve_chapter(body.book, body.chapter)
    translation = body.translation.upper()
    db = get_supabase()
    texts = {}
    if translation:
        found = (
            db.table("verses").select("verse, text").eq("translation", translation).eq("book", canonical)
            .eq("chapter", body.chapter).gte("verse", body.verse_start).lte("verse", body.verse_end)
            .execute().data
        )
        texts = {r["verse"]: r["text"] for r in found}
    rows = [
        {
            "user_id": user.id,
            "book": canonical,
            "chapter": body.chapter,
            "verse": n,
            "color": body.color,
            "translation": translation,
            "verse_text": texts.get(n),
        }
        for n in range(body.verse_start, body.verse_end + 1)
    ]
    _db(lambda: db.table("verse_highlights").upsert(rows, on_conflict="user_id,book,chapter,verse").execute())
    return {"status": "highlighted", "verses": [r["verse"] for r in rows], "color": body.color}


@router.delete("/me/highlights")
def clear(
    book: str,
    chapter: int = Query(ge=1, le=150),
    verse_start: int = Query(ge=1, le=176),
    verse_end: int | None = Query(default=None, ge=1, le=176),
    user: AuthUser = Depends(require_user),
) -> dict:
    """Remove the highlight from every verse in the range."""
    canonical = resolve_chapter(book, chapter)
    end = verse_end or verse_start
    _db(
        lambda: get_supabase().table("verse_highlights").delete().eq("user_id", user.id)
        .eq("book", canonical).eq("chapter", chapter).gte("verse", verse_start).lte("verse", end).execute()
    )
    return {"status": "cleared"}
