"""Declare: that a line is kept only when it rests on a passage Aquila was
given, that an unsafe situation gets helplines instead of words, and that the
kept ones stay inside one person's cave. The model and Supabase are faked;
nothing here makes a real network call."""

import json

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, declare
from app.agent.nodes import DeclareDraft, DeclareLine
from app.auth import AuthUser
from app.retrieval import ParsedReference
from app.schemas import Verse

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
HEADERS = {"Authorization": "Bearer t"}


def verse(book, chapter, n, text="text"):
    return Verse(book=book, chapter=chapter, verse=n, text=text, translation="KJV", source="reference")


PASSAGES = {
    "2 Timothy 1:7": [verse("2 Timothy", 1, 7, "For God hath not given us the spirit of fear;")],
    "Numbers 6:24-26": [verse("Numbers", 6, n, f"v{n}") for n in (24, 25, 26)],
}


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.db.calls.append((name, args))
            return self

        return method

    def execute(self):
        return type("Result", (), {"data": self.db.rows})()


class FakeDb:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return FakeQuery(self)


class TestKeys:
    def test_a_run_is_named_by_its_span(self):
        assert declare.ref_key(ParsedReference("Numbers", 6, 24, 26)) == "Numbers 6:24-26"
        assert declare.ref_key(ParsedReference("Isaiah", 41, 10, 10)) == "Isaiah 41:10"

    def test_long_runs_are_held_to_three_verses(self):
        assert declare.canonical_ref("Psalm 91:1-16") == "Psalms 91:1-3"

    def test_a_chapter_or_a_non_reference_is_not_a_passage(self):
        assert declare.canonical_ref("Psalm 23") is None
        assert declare.canonical_ref("my interview") is None

    def test_found_verses_name_their_own_key(self):
        assert declare.passage_key(PASSAGES["Numbers 6:24-26"]) == "Numbers 6:24-26"


class TestUsableLines:
    def test_keeps_lines_from_listed_passages_in_order(self):
        lines = [
            DeclareLine(say="I walk in without  fear.", ref="2 Tim 1:7"),
            DeclareLine(say="The Lord blesses and keeps me.", ref="Numbers 6:24-26"),
        ]
        assert declare.usable_lines(lines, PASSAGES) == [
            {"say": "I walk in without fear.", "ref": "2 Timothy 1:7"},
            {"say": "The Lord blesses and keeps me.", "ref": "Numbers 6:24-26"},
        ]

    def test_drops_unlisted_repeated_and_self_citing_lines(self):
        lines = [
            DeclareLine(say="I can do all things.", ref="Philippians 4:13"),  # never looked up
            DeclareLine(say="I am not afraid.", ref="2 Timothy 1:7"),
            DeclareLine(say="Still not afraid.", ref="2 Timothy 1:7"),  # same passage twice
            DeclareLine(say="As John 3:16 says, I am loved.", ref="Numbers 6:24-26"),  # names a verse
            DeclareLine(say="  ", ref="Numbers 6:24-26"),
        ]
        assert declare.usable_lines(lines, PASSAGES) == [{"say": "I am not afraid.", "ref": "2 Timothy 1:7"}]

    def test_an_opening_naming_a_verse_falls_back(self):
        assert declare.clean_opening("In Jesus' name, per Isaiah 41:10, I declare") == declare.FALLBACK_OPENING
        assert declare.clean_opening("In the name of Jesus, I declare over my exam.") == "In the name of Jesus, I declare over my exam."

    def test_a_prayer_naming_a_verse_is_dropped(self):
        assert declare.clean_prayer("Father, as Isaiah 41:10 says, hold me.") is None
        assert declare.clean_prayer("  ") is None
        assert declare.clean_prayer("Father,  I bring you my exam.\nKeep me steady.") == "Father, I bring you my exam. Keep me steady."


class TestSchemas:
    def test_declare_formats_carry_no_defaults_openai_would_refuse(self):
        """OpenAI's strict structured output refuses a schema with a default
        in it, which once turned every declaration into a 500."""
        from openai.lib._pydantic import to_strict_json_schema
        from app.agent.nodes import DeclareIdeas

        for model in (DeclareDraft, DeclareLine, DeclareIdeas):
            assert '"default"' not in json.dumps(to_strict_json_schema(model)), model.__name__


class TestOtherWords:
    def test_a_used_passage_is_left_out_with_any_that_overlap_it(self):
        passages = {**PASSAGES, "Numbers 6:26": [verse("Numbers", 6, 26)], "Psalm 23:1": [verse("Psalm", 23, 1)]}
        assert list(declare.without_used(passages, ["Numbers 6:24-26"])) == ["2 Timothy 1:7", "Psalm 23:1"]
        assert declare.without_used(passages, []) == passages

    @pytest.fixture
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    def test_other_words_rest_on_different_verses(self, monkeypatch, signed_in):
        more = {**PASSAGES, "Psalm 23:1": [verse("Psalm", 23, 1)], "Isaiah 41:10": [verse("Isaiah", 41, 10)], "Joshua 1:9": [verse("Joshua", 1, 9)]}
        asked = {}
        monkeypatch.setattr(declare, "gather_passages", lambda situation, translation, config, avoid=None: asked.update(avoid=avoid) or more)

        def write(situation, name, passages, extra="", config=None):
            asked["given"] = sorted(passages)
            return DeclareDraft(title="t", opening="o", lines=[DeclareLine(say=f"Line {i}.", ref=k) for i, k in enumerate(passages)], prayer="")

        monkeypatch.setattr(declare, "write_declaration", write)
        body = client.post("/declare", json={"situation": "An exam", "avoid": ["2 tim 1:7", "Numbers 6:24-26"]}, headers=HEADERS).json()
        assert asked["avoid"] == ["2 Timothy 1:7", "Numbers 6:24-26"]
        assert asked["given"] == ["Isaiah 41:10", "Joshua 1:9", "Psalm 23:1"]
        assert body["fresh"] is True

    def test_with_too_few_others_the_same_verses_come_back_reworded(self, monkeypatch, signed_in):
        monkeypatch.setattr(declare, "gather_passages", lambda situation, translation, config, avoid=None: PASSAGES)
        extras = []

        def write(situation, name, passages, extra="", config=None):
            extras.append(extra)
            return DeclareDraft(title="t", opening="o", lines=[DeclareLine(say="a", ref="2 Timothy 1:7"), DeclareLine(say="b", ref="Numbers 6:24-26")], prayer="")

        monkeypatch.setattr(declare, "write_declaration", write)
        body = client.post("/declare", json={"situation": "An exam", "avoid": ["2 Timothy 1:7"]}, headers=HEADERS).json()
        assert body["fresh"] is False and "differently" in extras[0]


class TestDeclareRoute:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        monkeypatch.setattr(declare, "gather_passages", lambda situation, translation, config, avoid=None: PASSAGES)

    def test_lines_come_back_with_verse_text_from_the_database(self, monkeypatch):
        draft = DeclareDraft(title="For your interview", opening="In the name of Jesus, I declare over my interview.", lines=[
            DeclareLine(say="I walk in without fear.", ref="2 Timothy 1:7"),
            DeclareLine(say="The Lord keeps me.", ref="Numbers 6:24-26"),
        ], prayer="Father, I bring you this interview. Give me peace.")
        monkeypatch.setattr(declare, "write_declaration", lambda *a, **k: draft)
        res = client.post("/declare", json={"situation": "A job interview tomorrow", "translation": "kjv"}, headers=HEADERS)
        assert res.status_code == 200
        body = res.json()
        assert body["translation"] == "KJV"
        assert body["lines"][0]["text"] == "For God hath not given us the spirit of fear;"
        assert body["lines"][1]["text"] == "v24 v25 v26"
        assert body["prayer"] == "Father, I bring you this interview. Give me peace."

    def test_writes_again_once_when_too_few_lines_survive(self, monkeypatch):
        drafts = iter([
            DeclareDraft(title="t", opening="o", lines=[DeclareLine(say="x", ref="John 3:16")], prayer=""),
            DeclareDraft(title="t", opening="o", lines=[
                DeclareLine(say="a", ref="2 Timothy 1:7"), DeclareLine(say="b", ref="Numbers 6:24-26"),
            ], prayer=""),
        ])
        extras = []

        def write(*args, extra="", **kwargs):
            extras.append(extra)
            return next(drafts)

        monkeypatch.setattr(declare, "write_declaration", write)
        res = client.post("/declare", json={"situation": "An exam"}, headers=HEADERS)
        assert [line["ref"] for line in res.json()["lines"]] == ["2 Timothy 1:7", "Numbers 6:24-26"]
        assert extras[0] == "" and "only the listed passages" in extras[1]

    def test_no_usable_lines_is_an_honest_error(self, monkeypatch):
        bad = DeclareDraft(title="t", opening="o", lines=[DeclareLine(say="x", ref="John 3:16")], prayer="")
        monkeypatch.setattr(declare, "write_declaration", lambda *a, **k: bad)
        res = client.post("/declare", json={"situation": "An exam"}, headers=HEADERS)
        assert res.status_code == 502

    def test_an_unsafe_situation_gets_no_words(self, monkeypatch):
        monkeypatch.setattr(declare, "write_declaration", lambda *a, **k: pytest.fail("should not write"))
        res = client.post("/declare", json={"situation": "I want to kill myself"}, headers=HEADERS)
        assert res.json() == {"care": True}

    def test_requires_sign_in(self):
        assert client.post("/declare", json={"situation": "An exam"}).status_code == 401


class TestKeeping:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    BODY = {
        "title": "For your interview", "situation": "Interview tomorrow", "opening": "In the name of Jesus.",
        "lines": [{"say": "I walk in without fear.", "ref": "2 tim 1:7"}],
    }

    def test_keeps_lines_with_canonical_references_and_no_verse_text(self, monkeypatch):
        db = FakeDb([{"id": "d1"}])
        monkeypatch.setattr(declare, "get_supabase", lambda: db)
        assert client.post("/me/declarations", json=self.BODY, headers=HEADERS).json() == {"id": "d1", "prayer_id": None}
        inserted = next(args[0] for name, args in db.calls if name == "insert")
        assert inserted["user_id"] == USER.id
        assert inserted["lines"] == [{"say": "I walk in without fear.", "ref": "2 Timothy 1:7"}]

    def test_a_line_that_is_not_a_verse_is_refused(self, monkeypatch):
        monkeypatch.setattr(declare, "get_supabase", lambda: FakeDb([]))
        body = {**self.BODY, "lines": [{"say": "Something", "ref": "my interview"}]}
        assert client.post("/me/declarations", json=body, headers=HEADERS).status_code == 422

    def test_someone_elses_prayer_is_a_404(self, monkeypatch):
        monkeypatch.setattr(declare, "get_supabase", lambda: FakeDb([]))
        body = {**self.BODY, "prayer_id": "22222222-2222-2222-2222-222222222222"}
        assert client.post("/me/declarations", json=body, headers=HEADERS).status_code == 404

    def test_a_quick_one_becomes_a_prayer_when_kept(self, monkeypatch):
        db = FakeDb([{"id": "d1"}])
        monkeypatch.setattr(declare, "get_supabase", lambda: db)
        made = []
        monkeypatch.setattr(declare.prayers, "create_prayer", lambda body, user: made.append(body.body) or {"id": "p1"})
        res = client.post("/me/declarations", json={**self.BODY, "as_prayer": True}, headers=HEADERS)
        assert res.json() == {"id": "d1", "prayer_id": "p1"} and made == ["Interview tomorrow"]
        # A prayer keeps one declaration, so an older one is replaced.
        assert ("eq", ("prayer_id", "p1")) in db.calls

    def test_list_and_delete_stay_inside_one_cave(self, monkeypatch):
        db = FakeDb([])
        monkeypatch.setattr(declare, "get_supabase", lambda: db)
        client.get("/me/declarations", headers=HEADERS)
        client.delete("/me/declarations/33333333-3333-3333-3333-333333333333", headers=HEADERS)
        assert db.calls.count(("eq", ("user_id", USER.id))) == 2

    def test_a_kept_one_can_be_reworded_within_its_own_passages(self, monkeypatch):
        db = FakeDb([{"id": "d1", "lines": [{"say": "Old words.", "ref": "2 Timothy 1:7"}]}])
        monkeypatch.setattr(declare, "get_supabase", lambda: db)
        path = "/me/declarations/33333333-3333-3333-3333-333333333333"
        res = client.patch(path, json={"lines": [{"say": "My own words.", "ref": "2 Timothy 1:7"}]}, headers=HEADERS)
        assert res.json()["lines"] == [{"say": "My own words.", "ref": "2 Timothy 1:7"}]
        assert db.calls.count(("eq", ("user_id", USER.id))) == 2
        # A new passage, or a reference typed into the words, is refused.
        assert client.patch(path, json={"lines": [{"say": "Words.", "ref": "John 3:16"}]}, headers=HEADERS).status_code == 422
        assert client.patch(path, json={"lines": [{"say": "As John 3:16 says.", "ref": "2 Timothy 1:7"}]}, headers=HEADERS).status_code == 422

    def test_editing_someone_elses_is_a_404(self, monkeypatch):
        monkeypatch.setattr(declare, "get_supabase", lambda: FakeDb([]))
        res = client.patch("/me/declarations/33333333-3333-3333-3333-333333333333", json={"title": "Mine"}, headers=HEADERS)
        assert res.status_code == 404

    def test_the_prayer_is_kept_and_can_be_reworded_without_references(self, monkeypatch):
        db = FakeDb([{"id": "d1", "lines": [{"say": "Old words.", "ref": "2 Timothy 1:7"}]}])
        monkeypatch.setattr(declare, "get_supabase", lambda: db)
        client.post("/me/declarations", json={**self.BODY, "prayer": "Lord, go before me."}, headers=HEADERS)
        inserted = next(args[0] for name, args in db.calls if name == "insert")
        assert inserted["prayer"] == "Lord, go before me."
        path = "/me/declarations/33333333-3333-3333-3333-333333333333"
        assert client.patch(path, json={"prayer": "Lord, keep me."}, headers=HEADERS).json()["prayer"] == "Lord, keep me."
        assert client.patch(path, json={"prayer": "Lord, as Psalm 23:1 says."}, headers=HEADERS).status_code == 422
