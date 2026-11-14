"""Declare: Scripture spoken aloud over something a person is facing.

Someone says what's ahead (an interview, a hospital visit, a friend's visa)
and gets a few lines to say aloud in faith, each with the passage it rests
on. It opens from the home screen for oneself, and from the prayer list
("Declare over" on a prayer, or a quick one from the tab's New menu).

How the words stay grounded:
- Aquila suggests passages as references only (nodes.py::suggest_declare_refs),
  alongside an ordinary search for the situation. Every verse's words are then
  read from the verses table in the person's translation.
- She writes the lines from those passages (nodes.py::write_declaration), and
  usable_lines keeps a line only when its reference is one she was given and
  its words name no reference of their own. Too few survive and she writes
  again once; none survive and the person is asked to put it another way.
- A kept declaration stores each line's words and reference, never verse text,
  which is read again whenever it's opened.
- After the lines comes a prayer to God over the same thing, in her words
  (clean_prayer). It names no reference, so it can never pass off a verse she
  wasn't given; one that does is dropped and the declaration goes without.

A situation that sounds unsafe gets no declaration: the page shows helplines
instead (app/care.py, the same phrases Refuge uses). Nothing here reaches
Aquila's memory. Same rule as app/cave.py: every query filters by user id.
"""

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException
from postgrest.exceptions import APIError
from pydantic import BaseModel, Field

from app import prayers, quota
from app.agent.nodes import DeclareLine, suggest_declare_refs, write_declaration
from app.auth import AuthUser, require_user
from app.bible import TRANSLATIONS
from app.care import sounds_unsafe
from app.cave import _db_call
from app.config import settings
from app.db import get_supabase
from app.observability import get_langfuse_handler
from app.retrieval import ParsedReference, find_references, hybrid_retrieve, lookup_by_reference, parse_reference
from app.schemas import Verse

log = logging.getLogger(__name__)
router = APIRouter()

_SETUP_HINT = "Keeping declarations needs a database update. Run supabase/migrations/20261119_declarations.sql in the Supabase SQL editor."
_PRAYER_HINT = "Keeping the prayer needs a database update. Run supabase/migrations/20261123_declaration_prayers.sql in the Supabase SQL editor."
_FIELDS = "id, title, situation, name, prayer_id, opening, lines, created_at"
# Postgres "undefined column" and PostgREST "column not in schema cache":
# the prayer column before its migration has run.
_MISSING_COLUMN_CODES = ("42703", "PGRST204")
MAX_PRAYER = 1200

MAX_LINES = 5
MAX_PASSAGE_VERSES = 3  # a passage is a verse or a short run, never a chapter
SEARCH_K = 6  # verses from the ordinary search, beside Aquila's suggestions
FALLBACK_OPENING = "In the name of Jesus, I declare God's word over this."
NO_WORDS = "Aquila couldn't find the right words this time. Try saying what you're facing a little differently."


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_declare.py)
# ---------------------------------------------------------------------------
def ref_key(ref: ParsedReference) -> str:
    """A reference in the one form passages are keyed by: "Isaiah 41:10",
    or "Numbers 6:24-26" for a run."""
    end = ref.verse_end or ref.verse_start
    span = f"{ref.verse_start}" if end == ref.verse_start else f"{ref.verse_start}-{end}"
    return f"{ref.book} {ref.chapter}:{span}"


def passage_key(verses: list[Verse]) -> str:
    """The key for verses actually found, so a run cut short by the end of a
    chapter is named by what it holds."""
    first, last = verses[0], verses[-1]
    return ref_key(ParsedReference(first.book, first.chapter, first.verse, last.verse))


def clamp(ref: ParsedReference) -> ParsedReference:
    """A run held to MAX_PASSAGE_VERSES, counted from its first verse."""
    end = min(ref.verse_end or ref.verse_start, ref.verse_start + MAX_PASSAGE_VERSES - 1)
    return ParsedReference(ref.book, ref.chapter, ref.verse_start, end)


def canonical_ref(text: str) -> str | None:
    """`text` as a passage key, or None when it isn't a verse reference."""
    ref = parse_reference(text or "")
    if not ref or ref.verse_start is None:
        return None
    return ref_key(clamp(ref))


def tidy(text: str) -> str:
    return " ".join((text or "").split())


def usable_lines(lines: list[DeclareLine], passages: dict[str, list[Verse]]) -> list[dict]:
    """The lines worth keeping, in order: each drawn from a listed passage,
    each passage used once, none naming a reference in its words (the verse
    sits under the line, so a reference in it could only point elsewhere)."""
    kept, used = [], set()
    for line in lines:
        key = canonical_ref(line.ref)
        say = tidy(line.say)
        if not say or key not in passages or key in used or find_references(say):
            continue
        kept.append({"say": say, "ref": key})
        used.add(key)
        if len(kept) == MAX_LINES:
            break
    return kept


def clean_opening(text: str) -> str:
    """The opening line, or a plain one when it's empty or names a reference."""
    text = tidy(text)
    return text if text and not find_references(text) else FALLBACK_OPENING


def clean_prayer(text: str | None) -> str | None:
    """The prayer, or None when it's empty or names a reference: a prayer
    leans on the passages under the lines, never on one it names itself."""
    text = tidy(text)[:MAX_PRAYER]
    return text if text and not find_references(text) else None


def clean_name(text: str | None) -> str | None:
    return tidy(text)[:40] or None


def with_text(lines: list[dict], passages: dict[str, list[Verse]]) -> list[dict]:
    """Each line with its passage's words, as read from the database."""
    return [{**line, "text": " ".join(v.text for v in passages.get(line["ref"], []))} for line in lines]


# ---------------------------------------------------------------------------
# Finding the passages
# ---------------------------------------------------------------------------
def _lookup(key: str, translation: str) -> list[Verse]:
    return lookup_by_reference(parse_reference(key), translation)


def gather_passages(situation: str, translation: str, config: dict) -> dict[str, list[Verse]]:
    """Aquila's suggested passages (looked up, so a reference that doesn't
    exist simply drops out) and the ordinary search's verses, keyed by
    reference. Her call and the search run side by side to save a wait."""
    with ThreadPoolExecutor(max_workers=4) as pool:
        ideas = pool.submit(suggest_declare_refs, situation, config)
        found = pool.submit(hybrid_retrieve, situation, translation, SEARCH_K)
        keys = list(dict.fromkeys(k for k in map(canonical_ref, ideas.result()) if k))
        looked_up = pool.map(lambda k: _lookup(k, translation), keys)
        passages = {passage_key(vs): vs for vs in looked_up if vs}
        for v in found.result():
            passages.setdefault(f"{v.book} {v.chapter}:{v.verse}", [v])
    return passages


def _config() -> dict:
    handler = get_langfuse_handler()
    return {"callbacks": [handler] if handler else [], "run_name": "declare"}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class DeclareIn(BaseModel):
    situation: str = Field(min_length=1, max_length=600)
    name: str | None = Field(default=None, max_length=60)
    translation: str | None = Field(default=None, max_length=12)


@router.post("/declare")
def declare(body: DeclareIn, user: AuthUser = Depends(require_user)) -> dict:
    """A declaration over what someone is facing: a title, an opening line,
    and a few lines to say aloud, each with its passage's words."""
    situation = tidy(body.situation)
    if not situation:
        raise HTTPException(status_code=422, detail="Say a few words about what you're facing.")
    if sounds_unsafe(situation):
        return {"care": True}
    quota.spend("question", user.id)
    translation = (body.translation or settings.default_translation).upper()
    if translation not in TRANSLATIONS:
        translation = settings.default_translation
    name = clean_name(body.name)
    config = _config()

    passages = gather_passages(situation, translation, config)
    if not passages:
        raise HTTPException(status_code=502, detail=NO_WORDS)
    draft = write_declaration(situation, name, passages, config=config)
    lines = usable_lines(draft.lines, passages)
    if len(lines) < 2:
        draft = write_declaration(
            situation, name, passages, config=config,
            extra="Your last draft used a passage that isn't listed, or named a reference in its words. Use only the listed passages, with each reference exactly as written.",
        )
        lines = usable_lines(draft.lines, passages) or lines
    if not lines:
        raise HTTPException(status_code=502, detail=NO_WORDS)
    return {
        "care": False,
        "title": tidy(draft.title)[:80] or "Your declaration",
        "opening": clean_opening(draft.opening),
        "lines": with_text(lines, passages),
        "prayer": clean_prayer(draft.prayer),
        "translation": translation,
    }


class KeptLine(BaseModel):
    say: str = Field(min_length=1, max_length=400)
    ref: str = Field(min_length=3, max_length=40)


class KeepIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    situation: str = Field(min_length=1, max_length=600)
    name: str | None = Field(default=None, max_length=60)
    opening: str = Field(min_length=1, max_length=300)
    lines: list[KeptLine] = Field(min_length=1, max_length=MAX_LINES)
    prayer: str | None = Field(default=None, max_length=MAX_PRAYER)
    # A declaration over a prayer stays with it (one per prayer). A quick one
    # from the prayer list becomes a prayer when it's kept.
    prayer_id: uuid.UUID | None = None
    as_prayer: bool = False


def _read(query):
    """Runs `query(fields)` with the prayer, or without it until the prayer
    migration has run, so kept declarations still open before then."""
    try:
        return query(f"{_FIELDS}, prayer")
    except APIError:
        # Without the prayer: this works before its migration, and any other
        # problem (a missing table) comes back from _db as what to run.
        return _db(lambda: query(_FIELDS))


@router.get("/me/declarations")
def list_declarations(user: AuthUser = Depends(require_user)) -> list[dict]:
    """Kept declarations, newest first, without their verses."""
    return _read(lambda fields: get_supabase().table("declarations").select(fields).eq("user_id", user.id)
                 .order("created_at", desc=True).limit(100).execute().data)


@router.get("/me/declarations/{declaration_id}")
def get_declaration(declaration_id: uuid.UUID, translation: str | None = None, user: AuthUser = Depends(require_user)) -> dict:
    """One kept declaration, its verses read in the translation open now."""
    rows = _read(lambda fields: get_supabase().table("declarations").select(fields)
                 .eq("id", str(declaration_id)).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="Declaration not found")
    row = rows[0]
    translation = (translation or settings.default_translation).upper()
    if translation not in TRANSLATIONS:
        translation = settings.default_translation
    passages = {line["ref"]: _lookup(line["ref"], translation) for line in row["lines"]}
    return {**row, "lines": with_text(row["lines"], passages), "translation": translation}


def kept_lines(lines: list[KeptLine]) -> list[dict]:
    """Lines as they're stored: words and a canonical reference, never verse
    text. A line whose reference isn't a verse, or whose words name one of
    their own (the person may have reworded it), is refused."""
    out = []
    for line in lines:
        key = canonical_ref(line.ref)
        if not key:
            raise HTTPException(status_code=422, detail="One of these lines doesn't point at a verse.")
        if find_references(line.say):
            raise HTTPException(status_code=422, detail="Leave references out of the words. Each line's verse is shown under it.")
        out.append({"say": tidy(line.say), "ref": key})
    return out


@router.post("/me/declarations")
def keep_declaration(body: KeepIn, user: AuthUser = Depends(require_user)) -> dict:
    """Keeps a declaration: on its own, with a prayer, or as a new prayer."""
    lines = kept_lines(body.lines)

    db = get_supabase()
    prayer_id = str(body.prayer_id) if body.prayer_id else None
    if prayer_id:
        owned = _db(lambda: db.table("prayers").select("id").eq("id", prayer_id).eq("user_id", user.id).limit(1).execute().data)
        if not owned:
            raise HTTPException(status_code=404, detail="Prayer not found")
    row = {
        "user_id": user.id, "title": tidy(body.title), "situation": tidy(body.situation),
        "name": clean_name(body.name), "opening": clean_opening(body.opening), "lines": lines,
    }
    # Checked before a prayer is made for it, so a missing table never leaves one behind.
    _db(lambda: db.table("declarations").select("id").limit(1).execute())
    if body.as_prayer and not prayer_id:
        prayer_id = prayers.create_prayer(prayers.PrayerIn(body=row["situation"]), user)["id"]
    if prayer_id:
        db.table("declarations").delete().eq("prayer_id", prayer_id).eq("user_id", user.id).execute()
    row["prayer_id"] = prayer_id
    prayer = clean_prayer(body.prayer)
    try:
        kept = db.table("declarations").insert({**row, "prayer": prayer} if prayer else row).execute().data[0]
    except APIError as err:
        # Before the prayer migration, the declaration is kept without it.
        if err.code not in _MISSING_COLUMN_CODES:
            raise
        log.info("declarations.prayer missing (run supabase/migrations/20261123_declaration_prayers.sql)")
        kept = _db(lambda: db.table("declarations").insert(row).execute().data[0])
    return {"id": kept["id"], "prayer_id": prayer_id}


class EditIn(BaseModel):
    """What the person can change in a kept declaration: its name and words.
    The passages stay the ones it was given, though a line can be dropped."""
    title: str | None = Field(default=None, min_length=1, max_length=80)
    opening: str | None = Field(default=None, min_length=1, max_length=300)
    lines: list[KeptLine] | None = Field(default=None, min_length=1, max_length=MAX_LINES)
    # An empty prayer takes it away.
    prayer: str | None = Field(default=None, max_length=MAX_PRAYER)


@router.patch("/me/declarations/{declaration_id}")
def edit_declaration(declaration_id: uuid.UUID, body: EditIn, user: AuthUser = Depends(require_user)) -> dict:
    """Saves the person's own wording of a kept declaration."""
    rows = _db(lambda: get_supabase().table("declarations").select("id, lines")
               .eq("id", str(declaration_id)).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="Declaration not found")
    changes: dict = {}
    if body.title is not None:
        changes["title"] = tidy(body.title)
    if body.opening is not None:
        changes["opening"] = clean_opening(body.opening)
    if body.lines is not None:
        lines = kept_lines(body.lines)
        # Rewording, or dropping a line, keeps to the passages it was given.
        given = {line["ref"] for line in rows[0]["lines"]}
        if any(line["ref"] not in given for line in lines):
            raise HTTPException(status_code=422, detail="A line can be reworded or removed, but its verse stays the one it was given.")
        changes["lines"] = lines
    if body.prayer is not None:
        if find_references(body.prayer):
            raise HTTPException(status_code=422, detail="Leave references out of the prayer.")
        changes["prayer"] = tidy(body.prayer) or None
    if changes:
        hint = _PRAYER_HINT if "prayer" in changes else _SETUP_HINT
        _db_call(lambda: get_supabase().table("declarations").update(changes)
                 .eq("id", str(declaration_id)).eq("user_id", user.id).execute(), hint)
    return {"ok": True, **changes}


@router.delete("/me/declarations/{declaration_id}")
def delete_declaration(declaration_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    _db(lambda: get_supabase().table("declarations").delete()
        .eq("id", str(declaration_id)).eq("user_id", user.id).execute())
    return {"ok": True}
