"""Speaking in Refuge's talk (app/voice.py). Deepgram is stubbed, so nothing
here sends audio anywhere."""

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, voice
from app.auth import AuthUser
from app.config import settings

client = TestClient(main.app)
HEADERS = {"Authorization": "Bearer t"}


@pytest.fixture(autouse=True)
def signed_in_with_a_key(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: AuthUser(id="u1", email="a@b.c"))
    monkeypatch.setattr(settings, "deepgram_api_key", "dg-test")


def stub_deepgram(monkeypatch, *, json=None, content=b"", fail=False):
    """Answers _deepgram's request, remembering what was asked."""
    seen = {}

    async def fake(path, params, **kwargs):
        seen.update(path=path, params=params, **kwargs)
        if fail:
            raise voice.HTTPException(status_code=502, detail=voice.TRY_AGAIN)
        return httpx.Response(200, json=json, request=httpx.Request("POST", "https://x")) if json is not None \
            else httpx.Response(200, content=content, request=httpx.Request("POST", "https://x"))

    monkeypatch.setattr(voice, "_deepgram", fake)
    return seen


class TestSpeakable:
    def test_references_are_said_the_way_a_person_says_them(self):
        assert voice.speakable("Rest (John 14:27).") == "Rest (John chapter 14, verse 27)."
        assert voice.speakable("1 John 4:7-8") == "1 John chapter 4, verses 7 to 8"
        assert voice.speakable("Song of Songs 2:4") == "Song of Songs chapter 2, verse 4"

    def test_markdown_is_never_read_out(self):
        assert voice.speakable("**Peace** to you") == "Peace to you"

    def test_a_study_answer_reads_as_sentences(self):
        answer = "## The passage\nJesus speaks to His disciples.\n\n## To think about:\n- What does [rest](#bible/John/14) look like?"
        assert voice.speakable(answer) == "The passage.\nJesus speaks to His disciples.\n\nTo think about.\nWhat does rest look like?"

    def test_a_long_reply_stops_at_a_full_sentence(self):
        text = ("This is a sentence. " * 200).strip()
        out = voice.speakable(text)
        assert len(out) <= voice.MAX_SPEAK_CHARS and out.endswith(".")


class TestTranscribe:
    def test_the_recording_becomes_words(self, monkeypatch):
        seen = stub_deepgram(monkeypatch, json={"results": {"channels": [{"alternatives": [{"transcript": " I feel tired "}]}]}})
        resp = client.post("/me/voice/transcribe", content=b"audio", headers={**HEADERS, "Content-Type": "audio/webm"})
        assert resp.json() == {"text": "I feel tired"}
        assert seen["path"] == "/listen" and seen["params"]["mip_opt_out"] == "true"
        assert seen["headers"]["Content-Type"] == "audio/webm"

    def test_only_audio_is_taken(self, monkeypatch):
        stub_deepgram(monkeypatch, json={})
        resp = client.post("/me/voice/transcribe", content=b"x", headers={**HEADERS, "Content-Type": "text/plain"})
        assert resp.status_code == 415

    def test_without_a_key_it_says_so(self, monkeypatch):
        monkeypatch.setattr(settings, "deepgram_api_key", "")
        assert client.get("/me/voice/speech", headers=HEADERS).json() == {"ready": False}
        resp = client.post("/me/voice/transcribe", content=b"a", headers={**HEADERS, "Content-Type": "audio/webm"})
        assert resp.status_code == 503 and resp.json()["detail"] == voice.NOT_SET_UP

    def test_a_daily_limit_comes_first(self, monkeypatch):
        seen = stub_deepgram(monkeypatch, json={})
        from app import quota
        monkeypatch.setattr(quota, "_record", lambda *a: "limit")
        resp = client.post("/me/voice/transcribe", content=b"a", headers={**HEADERS, "Content-Type": "audio/webm"})
        assert resp.status_code == 429 and resp.json()["detail"] == quota.LIMIT_MESSAGES["speech"]
        assert not seen


class TestSpeak:
    def test_the_reply_comes_back_as_audio(self, monkeypatch):
        seen = stub_deepgram(monkeypatch, content=b"ID3mp3")
        resp = client.post("/me/voice/speak", json={"text": "Peace (John 14:27)"}, headers=HEADERS)
        assert resp.status_code == 200 and resp.headers["content-type"] == "audio/mpeg" and resp.content == b"ID3mp3"
        assert seen["json"] == {"text": "Peace (John chapter 14, verse 27)"}
        assert seen["params"]["model"] == settings.deepgram_tts_voice

    def test_deepgram_failing_is_a_calm_message(self, monkeypatch):
        stub_deepgram(monkeypatch, fail=True)
        resp = client.post("/me/voice/speak", json={"text": "hello"}, headers=HEADERS)
        assert resp.status_code == 502 and resp.json()["detail"] == voice.TRY_AGAIN
