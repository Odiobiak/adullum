"""Speak with Aquila, through Deepgram: a voice conversation with the study
Aquila on the Aquila page and from the home screen (web/speak.js).

The person speaks, `transcribe` turns it into words, the page asks them as an
ordinary question (/chat/stream, so it's the same grounded Aquila with her
citations on screen), and `speak` reads the answer aloud, a piece at a time.
Nothing here is stored: the audio and the words pass through to Deepgram and
back. The Deepgram key never leaves this server.

Refuge doesn't use this; its voice is the Cognigy call (docs/cognigy-voice.md).
"""

import asyncio
import logging
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import quota
from app.auth import AuthUser, require_user
from app.config import settings

log = logging.getLogger(__name__)
router = APIRouter()

DEEPGRAM = "https://api.deepgram.com"
# A minute of speech is well under a megabyte in the browser's formats.
MAX_AUDIO_BYTES = 8 * 1024 * 1024
# Deepgram reads up to 2,000 characters a request; the page sends an answer in
# smaller pieces (web/speak.js::pieces), so this only guards against misuse.
MAX_SPEAK_CHARS = 2000
NOT_SET_UP = "Speaking isn't set up here yet. You can keep typing."
TRY_AGAIN = "Voice isn't working just now. You can keep typing, or try again in a moment."

# "John 14:27" read aloud as "John chapter 14, verse 27", and "1 John 4:7-8" as
# "1 John chapter 4, verses 7 to 8", so a reference sounds the way a person says it.
_REFERENCE_RE = re.compile(r"\b((?:[1-3] )?[A-Z][a-z]+(?: of [A-Z][a-z]+)?) (\d{1,3}):(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?")
_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*(.+?)[ \t]*$", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_BULLET_RE = re.compile(r"^[ \t]*(?:[-*•]|\d+\.)[ \t]+", re.MULTILINE)
_MARKDOWN_RE = re.compile(r"[*_#`>]+")


def speakable(text: str) -> str:
    """An answer as it should sound: a heading becomes a short sentence of its
    own ("The passage."), links read as their words, no Markdown, and
    references in words."""
    def say(m: re.Match) -> str:
        book, chapter, first, last = m.groups()
        return f"{book} chapter {chapter}, verses {first} to {last}" if last else f"{book} chapter {chapter}, verse {first}"
    text = _HEADING_RE.sub(lambda m: f"{m.group(1).rstrip('.:')}.", text)
    text = _BULLET_RE.sub("", _LINK_RE.sub(r"\1", text))
    text = _MARKDOWN_RE.sub("", _REFERENCE_RE.sub(say, text))
    if len(text) <= MAX_SPEAK_CHARS:
        return text.strip()
    # Too long: stop at the last full sentence that fits.
    cut = text[:MAX_SPEAK_CHARS]
    end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    return (cut[: end + 1] if end > 0 else cut).strip()


def _key() -> str:
    if not settings.deepgram_api_key:
        raise HTTPException(status_code=503, detail=NOT_SET_UP)
    return settings.deepgram_api_key


async def _deepgram(path: str, params: dict, **kwargs) -> httpx.Response:
    """One call to Deepgram. Any failure becomes a calm 502 for the page."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(f"{DEEPGRAM}{path}", params=params, **kwargs)
        response.raise_for_status()
        return response
    except httpx.HTTPError as err:
        log.warning("Deepgram %s failed: %s", path, err)
        raise HTTPException(status_code=502, detail=TRY_AGAIN) from err


@router.get("/me/voice/speech")
def speech_ready(user: AuthUser = Depends(require_user)) -> dict:
    """Whether the talk can offer Speak here (a Deepgram key is set)."""
    return {"ready": bool(settings.deepgram_api_key)}


@router.post("/me/voice/transcribe")
async def transcribe(request: Request, user: AuthUser = Depends(require_user)) -> dict:
    """The person's words from one spoken turn. The body is the recording
    itself (webm, mp4 or ogg, whatever the browser makes)."""
    key = _key()
    kind = request.headers.get("content-type", "")
    if not kind.startswith("audio/"):
        raise HTTPException(status_code=415, detail="That doesn't sound like audio.")
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="I didn't catch anything. Try again?")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="That was a long one. Try saying it in a shorter piece.")
    await _spend(user)
    response = await _deepgram(
        "/v1/listen",
        # mip_opt_out: Deepgram doesn't keep the audio to improve its models.
        {"model": settings.deepgram_stt_model, "smart_format": "true", "language": "en", "mip_opt_out": "true"},
        headers={"Authorization": f"Token {key}", "Content-Type": kind},
        content=audio,
    )
    try:
        text = response.json()["results"]["channels"][0]["alternatives"][0]["transcript"]
    except (KeyError, IndexError, ValueError):
        text = ""
    return {"text": text.strip()}


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


@router.post("/me/voice/speak")
async def speak(body: SpeakIn, user: AuthUser = Depends(require_user)) -> Response:
    """Aquila's reply read aloud, as mp3."""
    key = _key()
    words = speakable(body.text)
    if not words:
        raise HTTPException(status_code=422, detail="There's nothing to read.")
    await _spend(user)
    path, params = speak_request()
    response = await _deepgram(path, params, headers={"Authorization": f"Token {key}"}, json={"text": words})
    return Response(content=response.content, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


def speak_request() -> tuple[str, dict]:
    """Where to send a reply to be read aloud, and how. Flux voices live on
    /v2/speak, read mp3 by default and take a speed and expressivity; Aura
    voices are on /v1/speak and are asked for mp3."""
    voice = settings.deepgram_tts_voice
    if voice.startswith("flux-"):
        return "/v2/speak", {"model": voice, "speed": settings.deepgram_tts_speed, "expressivity": settings.deepgram_tts_expressivity}
    return "/v1/speak", {"model": voice, "encoding": "mp3"}


async def _spend(user: AuthUser) -> None:
    """Counts one spoken turn or reply against the day (app/quota.py)."""
    await asyncio.to_thread(quota.spend, "speech", user.id, user)
