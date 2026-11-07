"""Sermon notes: the cave's Sermons tab (web/sermons.js).

A sermon note is the details of the sermon (title, speaker, church, date,
series, main passage) and an ordered list of blocks: text, a point, a verse,
a photo, a quote, a to-do list, a link. The browser saves the whole note a
moment after each edit; the server checks every block's shape, works out
every Bible reference in it with the same parser Aquila uses
(app/retrieval.py::find_references), and returns the note with those
references, so the page never has to recognise a reference itself.

Photos are shrunk in the browser, sent here, and stored in the private
`sermon-images` bucket under <user id>/<note id>/. A photo block keeps only
that path, and the server signs a short-lived link each time the note is
read. A block can only point inside its own note's folder.

A note can be shared with a read-only link. The link carries a random token;
GET /shared/sermons/{token} needs no account and returns the note without
anything that identifies its writer (no user id, no storage paths, no prayer
ids). Turning sharing off clears the token, which breaks the link for good.

Same rule as app/cave.py: the server's Supabase client bypasses RLS, so every
/me query here filters by the signed-in user's id itself. Never drop the
`.eq("user_id", user.id)`.
"""

import base64
import binascii
import io
import logging
import re
import secrets
import uuid
import zipfile
from datetime import date
from typing import Annotated, Literal, Union
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator

from app import sermon_export
from app.auth import AuthUser, require_user
from app.cave import _db_call, _now
from app.config import settings
from app.db import get_supabase
from app.retrieval import ParsedReference, find_references, lookup_by_reference

log = logging.getLogger(__name__)

router = APIRouter()

_SETUP_HINT = (
    "Sermon notes aren't set up on the database yet. Run "
    "supabase/migrations/20261111_sermon_notes.sql in the Supabase SQL editor."
)

BUCKET = "sermon-images"
_PHOTO_FAILED = (
    "The photo couldn't be stored. If this keeps happening, the photo storage may not be set up: "
    "run supabase/migrations/20261111_sermon_notes.sql in the Supabase SQL editor."
)
SIGNED_URL_SECONDS = 60 * 60
MAX_IMAGE_BYTES = 5 * 1024 * 1024
# What each allowed image type's file starts with, so a declared type can't
# smuggle in something else.
_IMAGE_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

_LIST_FIELDS = "id, title, speaker, church, preached_on, series, passage_ref, passages, share_token, updated_at"
_NOTE_FIELDS = "id, user_id, title, speaker, church, preached_on, series, passage_ref, blocks, passages, share_token, shared_at, created_at, updated_at"


def _db(fn):
    return _db_call(fn, _SETUP_HINT)


# ---------------------------------------------------------------------------
# Block shapes. The browser makes up each block's id; the type decides the
# rest.
# ---------------------------------------------------------------------------
BlockId = Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")]


class TextBlock(BaseModel):
    id: BlockId
    type: Literal["text"]
    text: str = Field(default="", max_length=20000)


class HeadingBlock(BaseModel):
    id: BlockId
    type: Literal["heading"]
    text: str = Field(default="", max_length=300)


class VerseBlock(BaseModel):
    id: BlockId
    type: Literal["verse"]
    ref: str = Field(default="", max_length=120)


class ImageBlock(BaseModel):
    id: BlockId
    type: Literal["image"]
    path: str | None = Field(default=None, max_length=300)
    caption: str = Field(default="", max_length=500)


class QuoteBlock(BaseModel):
    id: BlockId
    type: Literal["quote"]
    text: str = Field(default="", max_length=2000)
    who: str = Field(default="", max_length=200)


class TodoItem(BaseModel):
    text: str = Field(default="", max_length=500)
    done: bool = False
    # Set once the step has been added to the prayer list (app/prayers.py).
    prayer_id: uuid.UUID | None = None


class TodoBlock(BaseModel):
    id: BlockId
    type: Literal["todo"]
    items: list[TodoItem] = Field(default_factory=list, max_length=50)


class LinkBlock(BaseModel):
    id: BlockId
    type: Literal["link"]
    url: str = Field(default="", max_length=1000)
    label: str = Field(default="", max_length=200)

    @field_validator("url")
    @classmethod
    def web_links_only(cls, url: str) -> str:
        # A shared note is shown to people who didn't write it, so a link can
        # never be javascript: or anything else that runs when clicked.
        url = url.strip()
        if url and not re.match(r"^https?://", url, re.IGNORECASE):
            raise ValueError("A link needs to start with http:// or https://")
        return url


Block = Annotated[
    Union[TextBlock, HeadingBlock, VerseBlock, ImageBlock, QuoteBlock, TodoBlock, LinkBlock],
    Field(discriminator="type"),
]


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    speaker: str | None = Field(default=None, max_length=200)
    church: str | None = Field(default=None, max_length=200)
    preached_on: date | None = None
    series: str | None = Field(default=None, max_length=200)
    passage_ref: str | None = Field(default=None, max_length=120)
    blocks: list[Block] = Field(default_factory=list, max_length=200)


class NotePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    speaker: str | None = Field(default=None, max_length=200)
    church: str | None = Field(default=None, max_length=200)
    preached_on: date | None = None
    series: str | None = Field(default=None, max_length=200)
    passage_ref: str | None = Field(default=None, max_length=120)
    blocks: list[Block] | None = Field(default=None, max_length=200)


class ImageIn(BaseModel):
    content_type: Literal["image/jpeg", "image/png", "image/webp"]
    # Base64, so a photo travels in the same JSON requests as everything else.
    data: str = Field(min_length=8, max_length=(MAX_IMAGE_BYTES * 4) // 3 + 8)


# ---------------------------------------------------------------------------
# Pure helpers (unit tested in tests/test_sermons.py)
# ---------------------------------------------------------------------------
def format_reference(ref: ParsedReference) -> str:
    """The canonical way a reference is written everywhere in the app:
    "Philippians 4", "Philippians 4:6", "Philippians 4:6-7"."""
    text = f"{ref.book} {ref.chapter}"
    if ref.verse_start is not None:
        end = ref.verse_end or ref.verse_start
        text += f":{ref.verse_start}" if end == ref.verse_start else f":{ref.verse_start}-{end}"
    return text


def references_in(text: str | None) -> list[str]:
    """Every reference written in `text`, canonical and without repeats."""
    seen: list[str] = []
    for ref in find_references(text or ""):
        formatted = format_reference(ref)
        if formatted not in seen:
            seen.append(formatted)
    return seen


def canonical_or_raw(text: str | None) -> str | None:
    """A typed reference in canonical form when it is one, or the text as
    typed when it isn't yet. Notes save as you type, so a half-written
    "Phil" must save quietly rather than fail."""
    text = (text or "").strip()
    if not text:
        return None
    found = references_in(text)
    return found[0] if found else text


def block_references(block: dict) -> list[str]:
    """The references a single block names."""
    kind = block.get("type")
    if kind == "verse":
        return references_in(block.get("ref"))
    if kind in ("text", "heading"):
        return references_in(block.get("text"))
    if kind == "quote":
        return references_in(block.get("text"))
    if kind == "todo":
        return references_in(" ; ".join(i.get("text", "") for i in block.get("items") or []))
    if kind == "image":
        return references_in(block.get("caption"))
    return []


def note_passages(note: dict) -> list[str]:
    """Every passage the note touches, main passage first, without repeats."""
    found: list[str] = []
    for ref in references_in(note.get("passage_ref")) + [r for b in note.get("blocks") or [] for r in block_references(b)]:
        if ref not in found:
            found.append(ref)
    return found


def image_paths(blocks: list[dict]) -> set[str]:
    return {b["path"] for b in blocks if b.get("type") == "image" and b.get("path")}


def folder(user_id: str, note_id: str) -> str:
    """Where a note's photos live in the bucket."""
    return f"{user_id}/{note_id}/"


# A photo's file name inside its note's folder. No dots but the extension's,
# no slashes and no percent signs, so a stored path can never climb out of
# the folder ("../") once the storage library tidies it into a URL.
_PHOTO_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}\.(?:jpg|png|webp)")


def photo_path_ok(path: object, user_id: str, note_id: str) -> bool:
    """Whether `path` is a photo directly inside this note's own folder."""
    prefix = folder(user_id, note_id)
    return isinstance(path, str) and path.startswith(prefix) and bool(_PHOTO_NAME.fullmatch(path[len(prefix):]))


def own_image_paths(note: dict) -> list[str]:
    """The note's photo paths that really are its own, checked again on every
    read so that a path stored before the check existed is never fetched."""
    return sorted(p for p in image_paths(note.get("blocks") or []) if photo_path_ok(p, str(note.get("user_id")), str(note.get("id"))))


def clean_blocks(blocks: list[dict], user_id: str, note_id: str) -> list[dict]:
    """Blocks as stored: a verse's reference in canonical form, and every
    photo checked to point inside this note's own folder, so a note can
    never show (or, once shared, hand out) someone else's photo."""
    cleaned = []
    for block in blocks:
        block = dict(block)
        if block.get("type") == "verse":
            block["ref"] = canonical_or_raw(block.get("ref")) or ""
        if block.get("type") == "image" and block.get("path") and not photo_path_ok(block["path"], user_id, note_id):
            raise HTTPException(status_code=422, detail="That photo doesn't belong to this note.")
        if block.get("type") == "todo":
            block["items"] = [{**i, "prayer_id": str(i["prayer_id"]) if i.get("prayer_id") else None} for i in block.get("items") or []]
        cleaned.append(block)
    return cleaned


def shared_view(note: dict, token: str) -> dict:
    """What a read-only link shows: the note, minus everything that would
    identify its writer or reach into their account. A photo is served
    through this link (`shared_photo`), never a signed storage link, since
    that names the writer's account id in its path."""
    blocks = []
    for index, block in enumerate(note.get("blocks") or []):
        if block.get("type") == "image":
            block = {**block, "url": f"/shared/sermons/{token}/photos/{index}" if block.get("url") else None}
        block = {k: v for k, v in block.items() if k != "path"}
        if block.get("type") == "todo":
            block["items"] = [{"text": i.get("text", ""), "done": bool(i.get("done"))} for i in block.get("items") or []]
        blocks.append(block)
    keep = ("title", "speaker", "church", "preached_on", "series", "passage_ref", "passages", "updated_at", "block_refs")
    return {**{k: note.get(k) for k in keep}, "blocks": blocks}


def related_sermons(note: dict, others: list[dict], limit: int = 4) -> list[dict]:
    """Other notes that share a book of the Bible with this one, the most
    books in common first, then the most recent."""
    def books(n: dict) -> set[str]:
        return {re.sub(r"\s\d+(?::.*)?$", "", p) for p in n.get("passages") or []}

    mine = books(note)
    if not mine:
        return []
    scored = [(len(mine & books(o)), o) for o in others if o["id"] != note["id"]]
    scored = [(s, o) for s, o in scored if s]
    scored.sort(key=lambda pair: (pair[0], pair[1].get("preached_on") or ""), reverse=True)
    return [{"id": o["id"], "title": o.get("title"), "preached_on": o.get("preached_on")} for _, o in scored[:limit]]


def decode_image(body: ImageIn) -> bytes:
    """The photo's bytes, checked to be the type it claims and within size."""
    try:
        data = base64.b64decode(body.data, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail="That photo didn't arrive whole. Try adding it again.")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="That photo is too large. Try a smaller one.")
    if not data.startswith(_IMAGE_SIGNATURES[body.content_type]):
        raise HTTPException(status_code=422, detail="That file isn't a photo Adullum can keep. Use a JPEG, PNG or WebP.")
    return data


# ---------------------------------------------------------------------------
# Storage and database helpers
# ---------------------------------------------------------------------------
def _bucket():
    return get_supabase().storage.from_(BUCKET)


def _signed_urls(paths: list[str]) -> dict[str, str]:
    """Short-lived links for photos. A missing bucket (migration not run) or
    a missing file leaves the photo without a link rather than failing."""
    if not paths:
        return {}
    try:
        signed = _bucket().create_signed_urls(paths, SIGNED_URL_SECONDS)
    except Exception:
        log.warning("couldn't sign sermon photo links", exc_info=True)
        return {}
    urls = {}
    for item in signed:
        url = item.get("signedURL") or item.get("signedUrl")
        if url and item.get("path"):
            urls[item["path"]] = url
    return urls


def _remove_images(paths: list[str]) -> None:
    """Best effort: an orphaned photo costs a little storage, never a failed save."""
    if not paths:
        return
    try:
        _bucket().remove(paths)
    except Exception:
        log.warning("couldn't remove %d sermon photos", len(paths), exc_info=True)


def present(note: dict) -> dict:
    """A note as the page receives it: each block's references, and a signed
    link on every photo."""
    blocks = note.get("blocks") or []
    urls = _signed_urls(own_image_paths(note))
    shown = [{**b, "url": urls.get(b.get("path"))} if b.get("type") == "image" else b for b in blocks]
    out = {k: v for k, v in note.items() if k != "user_id"}
    out["blocks"] = shown
    out["block_refs"] = {b["id"]: refs for b in blocks if (refs := block_references(b))}
    out["shared"] = bool(note.get("share_token"))
    return out


def _own_note(note_id: uuid.UUID, user: AuthUser, fields: str = _NOTE_FIELDS) -> dict:
    rows = _db(lambda: get_supabase().table("sermon_notes").select(fields).eq("id", str(note_id)).eq("user_id", user.id).limit(1).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That sermon note isn't here anymore.")
    return rows[0]


def _verse_texts(note: dict, translation: str) -> dict[str, str]:
    """The text of every verse block, read from the database in `translation`.
    A whole-chapter reference stays a reference, so an export never dumps a
    chapter the note only pointed at."""
    texts = {}
    for block in note.get("blocks") or []:
        ref = block.get("ref") if block.get("type") == "verse" else None
        if not ref or ref in texts:
            continue
        found = find_references(ref)
        if not found or found[0].verse_start is None:
            continue
        try:
            verses = lookup_by_reference(found[0], translation)
        except Exception:
            log.warning("couldn't read %s for an export", ref, exc_info=True)
            continue
        if verses:
            texts[ref] = " ".join(v.text for v in verses)
    return texts


def _image_bytes(note: dict) -> dict[str, bytes]:
    images = {}
    for path in own_image_paths(note):
        try:
            images[path] = _bucket().download(path)
        except Exception:
            log.warning("couldn't read sermon photo %s for an export", path, exc_info=True)
    return images


def _translation(translation: str | None) -> str:
    return (translation or settings.default_translation).upper()


def _download(content: bytes, media_type: str, name: str) -> Response:
    # RFC 5987 form, so an apostrophe or accent in a title survives.
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


# ---------------------------------------------------------------------------
# Routes: the list and one note
# ---------------------------------------------------------------------------
@router.get("/me/sermons")
def list_notes(user: AuthUser = Depends(require_user)) -> list[dict]:
    """Every note, most recently preached first, without their blocks."""
    rows = _db(lambda: (
        get_supabase().table("sermon_notes").select(_LIST_FIELDS).eq("user_id", user.id)
        .order("preached_on", desc=True, nullsfirst=False).order("updated_at", desc=True)
        .limit(500).execute().data
    ))
    return [{**{k: v for k, v in r.items() if k != "share_token"}, "shared": bool(r.get("share_token"))} for r in rows]


@router.post("/me/sermons")
def create_note(body: NoteIn, user: AuthUser = Depends(require_user)) -> dict:
    note_id = str(uuid.uuid4())
    blocks = clean_blocks([b.model_dump(mode="json") for b in body.blocks], user.id, note_id)
    row = {
        "id": note_id,
        "user_id": user.id,
        "title": body.title.strip(),
        "speaker": (body.speaker or "").strip() or None,
        "church": (body.church or "").strip() or None,
        "preached_on": body.preached_on.isoformat() if body.preached_on else None,
        "series": (body.series or "").strip() or None,
        "passage_ref": canonical_or_raw(body.passage_ref),
        "blocks": blocks,
    }
    row["passages"] = note_passages(row)
    note = _db(lambda: get_supabase().table("sermon_notes").insert(row).execute().data[0])
    return present(note)


# Declared before /me/sermons/{note_id} so "export.zip" is never read as an id.
@router.get("/me/sermons/export.zip")
def export_all(translation: str | None = None, user: AuthUser = Depends(require_user)) -> Response:
    """Every note as Markdown in one zip, with its photos in a folder beside it."""
    tr = _translation(translation)
    notes = _db(lambda: get_supabase().table("sermon_notes").select(_NOTE_FIELDS).eq("user_id", user.id).limit(500).execute().data)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used: set[str] = set()
        for note in notes:
            stem = sermon_export.filename(note, "md")[:-3]
            while stem in used:
                stem += " (2)"
            used.add(stem)
            image_files = {}
            for n, (path, data) in enumerate(_image_bytes(note).items(), start=1):
                name = f"images/{stem}/{n}.{path.rsplit('.', 1)[-1]}"
                archive.writestr(name, data)
                image_files[path] = name.replace(" ", "%20")
            archive.writestr(f"{stem}.md", sermon_export.to_markdown(note, _verse_texts(note, tr), tr, image_files))
    return _download(buffer.getvalue(), "application/zip", "Sermon notes.zip")


@router.get("/me/sermons/{note_id}")
def get_note(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    return present(_own_note(note_id, user))


@router.patch("/me/sermons/{note_id}")
def update_note(note_id: uuid.UUID, body: NotePatch, user: AuthUser = Depends(require_user)) -> dict:
    """Saves whatever changed. The page sends the whole note a moment after
    each edit; a photo dropped from the note is deleted from storage."""
    existing = _own_note(note_id, user)
    sent = body.model_dump(exclude_unset=True, mode="json")
    patch: dict = {"updated_at": _now()}
    if "title" in sent:
        patch["title"] = (sent["title"] or "").strip()
    for key in ("speaker", "church", "series"):
        if key in sent:
            patch[key] = (sent[key] or "").strip() or None
    if "preached_on" in sent:
        patch["preached_on"] = sent["preached_on"]
    if "passage_ref" in sent:
        patch["passage_ref"] = canonical_or_raw(sent["passage_ref"])
    if "blocks" in sent:
        patch["blocks"] = clean_blocks(sent["blocks"] or [], user.id, str(note_id))
    merged = {**existing, **patch}
    patch["passages"] = note_passages(merged)

    rows = _db(lambda: get_supabase().table("sermon_notes").update(patch).eq("id", str(note_id)).eq("user_id", user.id).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That sermon note isn't here anymore.")
    if "blocks" in patch:
        _remove_images(sorted(image_paths(existing.get("blocks") or []) - image_paths(patch["blocks"])))
    return present(rows[0])


@router.delete("/me/sermons/{note_id}")
def delete_note(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    note = _own_note(note_id, user, "id, blocks")
    _db(lambda: get_supabase().table("sermon_notes").delete().eq("id", str(note_id)).eq("user_id", user.id).execute())
    _remove_images(sorted(image_paths(note.get("blocks") or [])))
    return {"status": "deleted"}


# ---------------------------------------------------------------------------
# Routes: photos, sharing, what a note connects to, export
# ---------------------------------------------------------------------------
@router.post("/me/sermons/{note_id}/images")
def add_image(note_id: uuid.UUID, body: ImageIn, user: AuthUser = Depends(require_user)) -> dict:
    """Stores one photo for this note and returns its path (for the photo
    block to keep) and a link to show it now. The block itself arrives with
    the next save."""
    _own_note(note_id, user, "id")
    data = decode_image(body)
    path = f"{folder(user.id, str(note_id))}{uuid.uuid4().hex}.{_EXTENSIONS[body.content_type]}"
    try:
        _bucket().upload(path, data, {"content-type": body.content_type})
    except Exception as err:
        log.warning("sermon photo upload failed", exc_info=True)
        raise HTTPException(status_code=503, detail=_PHOTO_FAILED) from err
    return {"path": path, "url": _signed_urls([path]).get(path)}


@router.post("/me/sermons/{note_id}/share")
def share_note(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """Turns on the read-only link, or returns the one already on."""
    note = _own_note(note_id, user, "id, share_token")
    if note.get("share_token"):
        return {"token": note["share_token"]}
    token = secrets.token_urlsafe(12)
    _db(lambda: get_supabase().table("sermon_notes").update({"share_token": token, "shared_at": _now()}).eq("id", str(note_id)).eq("user_id", user.id).execute())
    return {"token": token}


@router.delete("/me/sermons/{note_id}/share")
def stop_sharing(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """Turns the link off for good. Sharing again makes a new link."""
    _own_note(note_id, user, "id")
    _db(lambda: get_supabase().table("sermon_notes").update({"share_token": None, "shared_at": None}).eq("id", str(note_id)).eq("user_id", user.id).execute())
    return {"status": "private"}


@router.get("/me/sermons/{note_id}/connected")
def connected(note_id: uuid.UUID, user: AuthUser = Depends(require_user)) -> dict:
    """What else in the cave this note touches: prayers added from its
    to-do lists, journal entries on its passages, and other sermons on the
    same books. Each part comes back empty on its own if it can't be read."""
    note = _own_note(note_id, user)
    db = get_supabase()

    def part(name, fn):
        try:
            return fn()
        except Exception:
            log.warning("sermon connections: %s unavailable", name, exc_info=True)
            return []

    prayer_ids = [i["prayer_id"] for b in note.get("blocks") or [] if b.get("type") == "todo" for i in b.get("items") or [] if i.get("prayer_id")]
    passages = note.get("passages") or []
    return {
        "prayers": part("prayers", lambda: (
            db.table("prayers").select("id, body, status").eq("user_id", user.id).in_("id", prayer_ids).execute().data
            if prayer_ids else []
        )),
        "journal": part("journal", lambda: (
            db.table("journal_entries").select("id, passage_ref, reflection, created_at").eq("user_id", user.id)
            .in_("passage_ref", passages).order("created_at", desc=True).limit(4).execute().data
            if passages else []
        )),
        "sermons": part("sermons", lambda: related_sermons(
            note, db.table("sermon_notes").select("id, title, preached_on, passages").eq("user_id", user.id).limit(500).execute().data
        )),
    }


_FORMATS = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "pdf": ("application/pdf", "pdf"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
}


@router.get("/me/sermons/{note_id}/export")
def export_note(
    note_id: uuid.UUID,
    format: Literal["md", "pdf", "docx"] = Query(default="pdf"),
    translation: str | None = None,
    user: AuthUser = Depends(require_user),
) -> Response:
    """One note as a file. Verses are written out in `translation`, read from
    the database like every verse the app shows."""
    note = _own_note(note_id, user)
    tr = _translation(translation)
    texts = _verse_texts(note, tr)
    media_type, extension = _FORMATS[format]
    if format == "md":
        content = sermon_export.to_markdown(note, texts, tr).encode("utf-8")
    elif format == "pdf":
        content = sermon_export.render_pdf(note, texts, tr, _image_bytes(note))
    else:
        content = sermon_export.render_docx(note, texts, tr, _image_bytes(note))
    return _download(content, media_type, sermon_export.filename(note, extension))


# ---------------------------------------------------------------------------
# The read-only link: no account needed
# ---------------------------------------------------------------------------
def _shared_row(token: str) -> dict:
    gone = HTTPException(status_code=404, detail="This sermon note isn't shared anymore.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", token):
        raise gone
    rows = _db(lambda: get_supabase().table("sermon_notes").select(_NOTE_FIELDS).eq("share_token", token).limit(1).execute().data)
    if not rows:
        raise gone
    return rows[0]


@router.get("/shared/sermons/{token}")
def shared_note(token: str) -> dict:
    return shared_view(present(_shared_row(token)), token)


@router.get("/shared/sermons/{token}/photos/{index}")
def shared_photo(token: str, index: int) -> Response:
    """One photo in a shared note, by its place among the note's blocks."""
    note = _shared_row(token)
    blocks = note.get("blocks") or []
    path = blocks[index].get("path") if 0 <= index < len(blocks) and blocks[index].get("type") == "image" else None
    if path not in own_image_paths(note):
        raise HTTPException(status_code=404, detail="That photo isn't here.")
    try:
        data = _bucket().download(path)
    except Exception as err:
        raise HTTPException(status_code=404, detail="That photo isn't here.") from err
    kind = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[path.rsplit(".", 1)[1]]
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=3600"})
