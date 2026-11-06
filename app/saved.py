"""Saved: one place for everything a person saves with one tap.

Two kinds of thing land here, newest first:
- a verse (from the reader, the verse of the day, a sermon's week after). Its
  words are read from the verses table here, never sent by the browser, so
  what's saved is always the real text of the translation it was saved from.
  Saving the same passage again returns the one already saved.
- an answer from Aquila: the question, the answer and its citations, as they
  were given.

It is the Bible tab's "Saved" page (web/saved.js), which replaced Memorize.
Same rule as app/cave.py: every query filters by the signed-in user's id.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app.auth import AuthUser, require_user
from app.cave import _db_call
from app.config import settings
from app.db import get_supabase
from app.notes import note_ref
from app.retrieval import lookup_by_reference, parse_reference

router = APIRouter()

_SETUP_HINT = "Saved isn't set up on the database yet. Run supabase/migrations/20261118_saved.sql in the Supabase SQL editor."

_FIELDS = "id, kind, book, chapter, verse_start, verse_end, translation, verse_text, question, answer, citations, created_at"

# A selection longer than this is a chapter, better read than saved.
MAX_VERSES = 40
MAX_ITEMS = 500


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


class SavedVerseIn(BaseModel):
    ref: str = Field(min_length=3, max_length=60)
    translation: str | None = Field(default=None, max_length=12)


class Citation(BaseModel):
    book: str = Field(max_length=40)
    chapter: int = Field(ge=1, le=150)
    verse: int = Field(ge=1, le=176)


class SavedAnswerIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    answer: str = Field(min_length=1, max_length=20000)
    citations: list[Citation] = Field(default_factory=list, max_length=50)


def present(row: dict) -> dict:
    """A saved row as the page shows it: a verse gains its reference."""
    if row["kind"] == "verse":
        return {**row, "ref": note_ref(row)}
    return row


@router.get("/me/saved")
def list_saved(kind: Literal["verse", "answer"] | None = None, user: AuthUser = Depends(require_user)) -> list[dict]:
    def run():
        q = get_supabase().table("saved_items").select(_FIELDS).eq("user_id", user.id)
        if kind:
            q = q.eq("kind", kind)
        return q.order("created_at", desc=True).limit(MAX_ITEMS).execute().data

    return [present(r) for r in _db(run)]


@router.post("/me/saved/verse")
def save_verse(body: SavedVerseIn, user: AuthUser = Depends(require_user)) -> dict:
    """Save a passage. One already saved comes back as it is (`already`)."""
    parsed = parse_reference(body.ref)
    if not parsed:
        raise HTTPException(status_code=422, detail=f"{body.ref!r} doesn't look like a Bible reference.")
    if parsed.verse_start is None:
        raise HTTPException(status_code=422, detail="Pick the verses to save, like John 3:16, rather than a whole chapter.")
    if parsed.verse_end - parsed.verse_start + 1 > MAX_VERSES:
        raise HTTPException(status_code=422, detail=f"Save up to {MAX_VERSES} verses at a time.")
    translation = (body.translation or settings.default_translation).upper()
    verses = lookup_by_reference(parsed, translation)
    if not verses:
        raise HTTPException(status_code=404, detail=f"{body.ref} isn't in the {translation} here.")

    place = {"book": parsed.book, "chapter": parsed.chapter, "verse_start": parsed.verse_start, "verse_end": parsed.verse_end}
    row = {"user_id": user.id, "kind": "verse", **place, "translation": translation, "verse_text": " ".join(v.text for v in verses)}
    db = get_supabase()
    try:
        return {**present(_db(lambda: db.table("saved_items").insert(row).execute().data[0])), "already": False}
    except APIError as err:
        if err.code != "23505":  # unique violation: already saved
            raise
    q = db.table("saved_items").select(_FIELDS).eq("user_id", user.id).eq("kind", "verse")
    for column, value in place.items():
        q = q.eq(column, value)
    return {**present(q.limit(1).execute().data[0]), "already": True}


@router.post("/me/saved/answer")
def save_answer(body: SavedAnswerIn, user: AuthUser = Depends(require_user)) -> dict:
    row = {
        "user_id": user.id,
        "kind": "answer",
        "question": body.question.strip(),
        "answer": body.answer.strip(),
        "citations": [c.model_dump() for c in body.citations],
    }
    return present(_db(lambda: get_supabase().table("saved_items").insert(row).execute().data[0]))


@router.delete("/me/saved/{item_id}")
def unsave(item_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("saved_items").delete().eq("id", str(item_id)).eq("user_id", user.id).execute())
    return {"status": "deleted"}
