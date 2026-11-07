"""Sermon notes: the pure helpers that find references and clean blocks, the
rules that keep a shared note from leaking anything private, the three
export formats, and the routes. Supabase, storage and auth are faked out;
nothing here makes a real network call."""

import base64

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, sermon_export, sermons
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="lydia@example.com")
HEADERS = {"Authorization": "Bearer t"}
NOTE_ID = "22222222-2222-2222-2222-222222222222"
PRAYER_ID = "33333333-3333-3333-3333-333333333333"
FOLDER = f"{USER.id}/{NOTE_ID}/"


class FakeQuery:
    """Records each chained call and answers execute() from the fake db."""

    def __init__(self, db, name):
        self.db, self.name = db, name

    def __getattr__(self, method):
        def call(*args, **kwargs):
            self.db.calls.append((self.name, method, args))
            if method in ("insert", "upsert", "update"):
                self.db.written.append((self.name, method, args[0]))
            return self

        return call

    def execute(self):
        data = self.db.rows.get(self.name, [])
        written = [w for w in self.db.written if w[0] == self.name]
        if written and written[-1][1] in ("insert", "update"):
            data = [{**(data[0] if data else {}), **written[-1][2]}]
        return type("Result", (), {"data": data, "count": len(data)})()


class FakeDb:
    def __init__(self, rows=None):
        self.rows = rows or {}
        self.calls, self.written = [], []

    def table(self, name):
        return FakeQuery(self, name)

    def filtered(self, table, column, value, method="eq"):
        return (table, method, (column, value)) in self.calls


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: USER)


def use_db(monkeypatch, db):
    monkeypatch.setattr(sermons, "get_supabase", lambda: db)
    # Storage is faked: every photo gets a predictable signed link.
    monkeypatch.setattr(sermons, "_signed_urls", lambda paths: {p: f"https://signed/{p}" for p in paths})
    monkeypatch.setattr(sermons, "_remove_images", lambda paths: db.calls.append(("storage", "remove", tuple(paths))))
    return db


def note_row(**extra):
    return {
        "id": NOTE_ID, "user_id": USER.id, "title": "Anxious for nothing", "speaker": "Pastor Grace",
        "church": "Hope Church", "preached_on": "2026-11-01", "series": None, "passage_ref": "Philippians 4:4-9",
        "blocks": [
            {"id": "t1", "type": "text", "text": "Compare 1 Peter 5:7 and ps 55:22."},
            {"id": "v1", "type": "verse", "ref": "Philippians 4:6-7"},
            {"id": "p1", "type": "image", "path": f"{FOLDER}slide.jpg", "caption": "Her slide"},
            {"id": "d1", "type": "todo", "items": [{"text": "Pray for Mum", "done": False, "prayer_id": PRAYER_ID}]},
        ],
        "passages": ["Philippians 4:4-9", "1 Peter 5:7", "Psalms 55:22", "Philippians 4:6-7"],
        "share_token": None, "shared_at": None, "created_at": "2026-11-01T10:00:00+00:00", "updated_at": "2026-11-01T10:00:00+00:00",
        **extra,
    }


# ---------------------------------------------------------------------------
# Finding references
# ---------------------------------------------------------------------------
class TestReferences:
    def test_every_reference_in_text_canonical_and_once(self):
        assert sermons.references_in("Compare 1 Peter 5:7, jn 3:16 and 1 Peter 5:7 again") == ["1 Peter 5:7", "John 3:16"]

    def test_a_half_typed_reference_saves_as_typed(self):
        # Notes save as you type, so "Phil" must not fail the save.
        assert sermons.canonical_or_raw("phil 4:6") == "Philippians 4:6"
        assert sermons.canonical_or_raw("Phil") == "Phil"
        assert sermons.canonical_or_raw("  ") is None

    def test_passages_put_the_main_passage_first_without_repeats(self):
        note = {"passage_ref": "Philippians 4:4-9", "blocks": [
            {"id": "a", "type": "verse", "ref": "Philippians 4:4-9"},
            {"id": "b", "type": "todo", "items": [{"text": "Read Romans 8:28"}]},
            {"id": "c", "type": "quote", "text": "As Psalm 23:1 says"},
            {"id": "d", "type": "link", "url": "https://example.com/John 3:16"},
        ]}
        assert sermons.note_passages(note) == ["Philippians 4:4-9", "Romans 8:28", "Psalms 23:1"]


# ---------------------------------------------------------------------------
# Cleaning blocks before they're stored
# ---------------------------------------------------------------------------
class TestCleanBlocks:
    def test_verse_refs_are_stored_canonical(self):
        cleaned = sermons.clean_blocks([{"id": "v", "type": "verse", "ref": "ps 23:1"}], USER.id, NOTE_ID)
        assert cleaned[0]["ref"] == "Psalms 23:1"

    def test_a_photo_outside_the_notes_own_folder_is_refused(self):
        # Otherwise a note could sign, and a shared link hand out, someone else's photo.
        other = [{"id": "p", "type": "image", "path": "someone-else/their-note/photo.jpg"}]
        with pytest.raises(HTTPException) as err:
            sermons.clean_blocks(other, USER.id, NOTE_ID)
        assert err.value.status_code == 422

    @pytest.mark.parametrize("name", ["../../someone-else/their-note/photo.jpg", "..%2F..%2Fx.jpg", "sub/a.jpg", "a.jpg.exe"])
    def test_a_photo_path_that_climbs_out_of_the_folder_is_refused(self, name):
        # The storage library tidies "../" away when it builds a URL, so a
        # prefix check alone would let an export fetch another person's photo.
        with pytest.raises(HTTPException):
            sermons.clean_blocks([{"id": "p", "type": "image", "path": f"{FOLDER}{name}"}], USER.id, NOTE_ID)

    def test_a_photo_in_the_notes_folder_is_kept(self):
        mine = [{"id": "p", "type": "image", "path": f"{FOLDER}a.jpg", "caption": ""}]
        assert sermons.clean_blocks(mine, USER.id, NOTE_ID)[0]["path"] == f"{FOLDER}a.jpg"

    def test_links_must_be_web_links(self):
        with pytest.raises(ValueError):
            sermons.LinkBlock(id="l", type="link", url="javascript:alert(1)")
        assert sermons.LinkBlock(id="l", type="link", url="https://example.com").url == "https://example.com"


def test_shared_view_carries_nothing_that_identifies_the_writer(monkeypatch):
    use_db(monkeypatch, FakeDb())
    shown = sermons.shared_view(sermons.present(note_row(share_token="secret-token")), "secret-token")
    assert "user_id" not in shown and "share_token" not in shown and "id" not in shown
    photo = next(b for b in shown["blocks"] if b["type"] == "image")
    # Served through the link itself: a signed storage link names the writer's account.
    assert "path" not in photo and photo["url"].startswith("/shared/sermons/secret-token/photos/")
    assert USER.id not in str(shown)
    step = next(b for b in shown["blocks"] if b["type"] == "todo")["items"][0]
    assert step == {"text": "Pray for Mum", "done": False}


def test_related_sermons_share_a_book():
    note = {"id": "a", "passages": ["Philippians 4:6", "1 Peter 5:7"]}
    others = [
        {"id": "a", "title": "Itself", "passages": ["Philippians 4:6"], "preached_on": "2026-11-01"},
        {"id": "b", "title": "Joy", "passages": ["Philippians 1:3"], "preached_on": "2026-08-01"},
        {"id": "c", "title": "Unrelated", "passages": ["Genesis 1:1"], "preached_on": "2026-10-01"},
        {"id": "d", "title": "Both", "passages": ["Philippians 2:5", "1 Peter 1:3"], "preached_on": "2026-01-01"},
    ]
    assert [s["id"] for s in sermons.related_sermons(note, others)] == ["d", "b"]


class TestDecodeImage:
    def test_a_jpeg_decodes(self):
        data = b"\xff\xd8\xff\xe0" + b"0" * 32
        body = sermons.ImageIn(content_type="image/jpeg", data=base64.b64encode(data).decode())
        assert sermons.decode_image(body) == data

    def test_a_file_that_isnt_what_it_claims_is_refused(self):
        body = sermons.ImageIn(content_type="image/jpeg", data=base64.b64encode(b"<svg onload=alert(1)>").decode())
        with pytest.raises(HTTPException) as err:
            sermons.decode_image(body)
        assert err.value.status_code == 422


# ---------------------------------------------------------------------------
# Export layouts
# ---------------------------------------------------------------------------
class TestExport:
    def note(self):
        return {**note_row(), "blocks": note_row()["blocks"] + [
            {"id": "h1", "type": "heading", "text": "1. Prayer"},
            {"id": "q1", "type": "quote", "text": "Worry is a conversation with yourself.", "who": "Pastor Grace"},
            {"id": "l1", "type": "link", "url": "https://example.com/watch", "label": "Recording"},
        ]}

    def test_markdown_writes_verses_out_and_marks_steps(self):
        md = sermon_export.to_markdown(self.note(), {"Philippians 4:6-7": "Be anxious for nothing."}, "BSB")
        assert md.startswith("# Anxious for nothing")
        assert "> Be anxious for nothing." in md and "> Philippians 4:6-7 (BSB)" in md
        assert "- [ ] Pray for Mum" in md
        assert "[Recording](https://example.com/watch)" in md
        assert "*[Photo: Her slide]*" in md  # a lone .md can't carry the photo

    def test_markdown_keeps_line_breaks_and_lists(self):
        text = "Three things to hold:\n• Pray first\n• Give thanks\nThen rest.\n1. Read it\n2. Live it"
        assert sermon_export.markdown_text(text) == [
            "Three things to hold:  ",
            "",
            "- Pray first",
            "- Give thanks",
            "",
            "Then rest.  ",
            "",
            "1. Read it",
            "2. Live it",
        ]

    def test_markdown_reads_typed_dashes_as_bullets_but_not_a_minus(self):
        assert sermon_export.markdown_text("- one\n* two") == ["- one", "- two"]
        assert sermon_export.markdown_text("-5 degrees outside") == ["-5 degrees outside  "]

    def test_lists_render_in_pdf_and_word(self):
        note = {**self.note(), "blocks": [{"id": "t9", "type": "text", "text": "• Pray first\n• Give thanks\n1. Read it"}]}
        assert sermon_export.render_pdf(note, {}, "BSB", {}).startswith(b"%PDF")
        assert sermon_export.render_docx(note, {}, "BSB", {}).startswith(b"PK")

    def test_pdf_and_word_render(self):
        texts = {"Philippians 4:6-7": "Be anxious for nothing."}
        assert sermon_export.render_pdf(self.note(), texts, "BSB", {}).startswith(b"%PDF")
        assert sermon_export.render_docx(self.note(), texts, "BSB", {}).startswith(b"PK")

    def test_filename_is_dated_and_safe(self):
        assert sermon_export.filename({"title": "Peace / Part 2?", "preached_on": "2026-11-01"}, "pdf") == "2026-11-01 Peace  Part 2.pdf"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class TestRoutes:
    def test_sermons_require_sign_in(self):
        assert client.get("/me/sermons").status_code == 401

    def test_creating_a_note_stores_it_for_this_person_with_its_passages(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb())
        res = client.post("/me/sermons", headers=HEADERS, json={
            "title": "Bread for today", "passage_ref": "mt 6:11",
            "blocks": [{"id": "a", "type": "text", "text": "See also John 6:35"}],
        })
        assert res.status_code == 200
        stored = db.written[-1][2]
        assert stored["user_id"] == USER.id
        assert stored["passage_ref"] == "Matthew 6:11"
        assert stored["passages"] == ["Matthew 6:11", "John 6:35"]
        assert res.json()["block_refs"] == {"a": ["John 6:35"]}
        assert "user_id" not in res.json()

    def test_saving_filters_by_user_and_removes_dropped_photos(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb({"sermon_notes": [note_row()]}))
        res = client.patch(f"/me/sermons/{NOTE_ID}", headers=HEADERS, json={"blocks": [{"id": "t1", "type": "text", "text": "Only words now"}]})
        assert res.status_code == 200
        assert db.filtered("sermon_notes", "user_id", USER.id)
        assert ("storage", "remove", (f"{FOLDER}slide.jpg",)) in db.calls

    def test_a_javascript_link_is_refused(self, monkeypatch, signed_in):
        use_db(monkeypatch, FakeDb({"sermon_notes": [note_row()]}))
        res = client.patch(f"/me/sermons/{NOTE_ID}", headers=HEADERS, json={"blocks": [{"id": "l", "type": "link", "url": "javascript:alert(1)"}]})
        assert res.status_code == 422

    def test_sharing_makes_a_token_once(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb({"sermon_notes": [note_row()]}))
        token = client.post(f"/me/sermons/{NOTE_ID}/share", headers=HEADERS).json()["token"]
        assert len(token) >= 12 and db.written[-1][2]["share_token"] == token
        db.rows["sermon_notes"] = [note_row(share_token="already-on-link")]
        db.written.clear()
        assert client.post(f"/me/sermons/{NOTE_ID}/share", headers=HEADERS).json()["token"] == "already-on-link"

    def test_a_shared_link_opens_without_an_account(self, monkeypatch):
        use_db(monkeypatch, FakeDb({"sermon_notes": [note_row(share_token="abcdefghijkl")]}))
        res = client.get("/shared/sermons/abcdefghijkl")
        assert res.status_code == 200
        body = res.json()
        assert body["title"] == "Anxious for nothing" and "user_id" not in body

    def test_an_unshared_or_malformed_token_is_not_found(self, monkeypatch):
        use_db(monkeypatch, FakeDb({"sermon_notes": []}))
        assert client.get("/shared/sermons/abcdefghijkl").status_code == 404
        assert client.get("/shared/sermons/bad token!").status_code == 404

    def test_markdown_export_downloads_with_its_name(self, monkeypatch, signed_in):
        use_db(monkeypatch, FakeDb({"sermon_notes": [note_row()]}))
        monkeypatch.setattr(sermons, "_verse_texts", lambda note, tr: {})
        res = client.get(f"/me/sermons/{NOTE_ID}/export?format=md", headers=HEADERS)
        assert res.status_code == 200
        assert "2026-11-01%20Anxious%20for%20nothing.md" in res.headers["content-disposition"]
        assert res.text.startswith("# Anxious for nothing")
