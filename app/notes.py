"""Notes a person writes on verses while reading the Bible.

A note is pinned to a book, chapter, and verse range rather than to a
translation, so a note written on John 3:16 in the KJV still shows beside
John 3:16 in the BSB. The translation it was written against, and the verse
text the person was looking at, are kept alongside it for reference.

Same rule as app/cave.py: the server's Supabase client bypasses RLS, so every
query here filters by the signed-in user's id itself. Never drop the
`.eq("user_id", user.id)`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator

from app.auth import AuthUser, require_user
from app.bible import resolve_chapter
from app.cave import _db_call, _now
from app.db import get_supabase

router = APIRouter()

_SETUP_HINT = (
    "Notes aren't set up on the database yet. Run supabase/migrations/20261107_verse_notes.sql "
    "in the Supabase SQL editor."
)

_FIELDS = "id, book, chapter, verse_start, verse_end, translation, verse_text, body, created_at, updated_at"


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


class NoteIn(BaseModel):
    book: str = Field(max_length=40)
    chapter: int = Field(ge=1, le=150)
    verse_start: int = Field(ge=1, le=176)
    verse_end: int | None = Field(default=None, ge=1, le=176)
    translation: str = Field(default="", max_length=12)
    verse_text: str | None = Field(default=None, max_length=6000)
    body: str = Field(min_length=1, max_length=8000)

    @model_validator(mode="after")
    def _range(self):
        if self.verse_end is None:
            self.verse_end = self.verse_start
        if self.verse_end < self.verse_start:
            raise ValueError("verse_end comes before verse_start")
        if not self.body.strip():
            raise ValueError("A note needs some words in it.")
        return self


class NotePatch(BaseModel):
    body: str = Field(min_length=1, max_length=8000)


def note_ref(note: dict) -> str:
    """"John 3:16" or "John 3:16-18", the form parse_reference reads back."""
    start, end = note["verse_start"], note["verse_end"]
    verses = f"{start}" if start == end else f"{start}-{end}"
    return f"{note['book']} {note['chapter']}:{verses}"


def _with_ref(note: dict) -> dict:
    return {**note, "ref": note_ref(note)}


@router.get("/me/notes")
def list_notes(book: str | None = None, chapter: int | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every note, newest first, or just one chapter's in verse order (what
    the reader asks for when it opens a chapter)."""

    def run():
        q = get_supabase().table("verse_notes").select(_FIELDS).eq("user_id", user.id)
        if book and chapter:
            q = q.eq("book", resolve_chapter(book, chapter)).eq("chapter", chapter)
            return q.order("verse_start").order("created_at").execute().data
        return q.order("updated_at", desc=True).limit(300).execute().data

    return [_with_ref(n) for n in _db(run)]


@router.post("/me/notes")
def create_note(body: NoteIn, user: AuthUser = Depends(require_user)) -> dict:
    row = body.model_dump()
    row["book"] = resolve_chapter(body.book, body.chapter)
    row["body"] = body.body.strip()
    row["translation"] = body.translation.upper()
    row["user_id"] = user.id
    return _with_ref(_db(lambda: get_supabase().table("verse_notes").insert(row).execute().data[0]))


@router.patch("/me/notes/{note_id}")
def update_note(note_id: uuid.UUID, body: NotePatch, user: AuthUser = Depends(require_user)) -> dict:
    text = body.body.strip()
    if not text:
        raise HTTPException(status_code=422, detail="A note needs some words in it.")
    rows = _db(
        lambda: get_supabase()
        .table("verse_notes")
        .update({"body": text, "updated_at": _now()})
        .eq("id", str(note_id))
        .eq("user_id", user.id)
        .execute()
        .data
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Note not found")
    return _with_ref(rows[0])


@router.delete("/me/notes/{note_id}")
def delete_note(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("verse_notes").delete().eq("id", str(note_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
