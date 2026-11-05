"""Refuge: the pure helpers, the wall's automatic check and routes, the admin
desk's gate, Aquila's listening mode, and renaming a conversation. Supabase,
auth, OpenAI and the agent are all faked out; nothing here makes a real
network call."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, cave, one_another, refuge
from app.agent import graph, nodes
from app.auth import AuthUser
from app.config import settings
from app.schemas import Verse

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
ADMIN = AuthUser(id="33333333-3333-3333-3333-333333333333", email="keeper@example.com")
HEADERS = {"Authorization": "Bearer t"}
POST_ID = "22222222-2222-2222-2222-222222222222"


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
        if written and written[-1][1] == "insert" and not data:
            data = [{**written[-1][2], "id": "new-id", "created_at": "2026-11-05T00:00:00+00:00"}]
        return type("Result", (), {"data": data, "count": self.db.counts.get(self.name, 0)})()


class FakeDb:
    def __init__(self, rows=None, counts=None):
        self.rows, self.counts = rows or {}, counts or {}
        self.calls, self.written = [], []

    def table(self, name):
        return FakeQuery(self, name)

    def filtered(self, table, column, value, method="eq"):
        return (table, method, (column, value)) in self.calls


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: USER)


def use_db(monkeypatch, db):
    for module in (one_another, refuge, cave):
        monkeypatch.setattr(module, "get_supabase", lambda: db)
    return db


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_talk_title_is_the_start_of_what_they_said(self):
        messages = [{"role": "aquila", "content": "I'm here."}, {"role": "user", "content": "  I got   the job!  "}]
        assert refuge.talk_title(messages) == "I got the job!"
        long = refuge.talk_title([{"role": "user", "content": "word " * 40}])
        assert len(long) <= refuge.TITLE_LENGTH and long.endswith("...")

    def test_clean_steps_accepts_new_and_edited_steps(self):
        assert refuge.clean_steps(["Call Mum", "  ", {"text": "Book a flight", "done": True}]) == [
            {"text": "Call Mum", "done": False},
            {"text": "Book a flight", "done": True},
        ]
        assert len(refuge.clean_steps([f"step {n}" for n in range(30)])) == refuge.MAX_STEPS

    def test_rhythm_is_the_last_week_ending_today(self):
        today = date(2026, 11, 5)
        days = ["2026-11-05", "2026-11-03", "2026-10-20"]
        assert refuge.rhythm(days, today) == [False, False, False, False, True, False, True]


# ---------------------------------------------------------------------------
# The wall's automatic check
# ---------------------------------------------------------------------------
class TestAutomaticCheck:
    @pytest.mark.parametrize("text", [
        "message me at ruth@example.com",
        "call 07700 900123 anytime",
        "find me @ruthie_g",
        "see www.example.org",
        "my blog is ruth.me",
    ])
    def test_contact_details_are_caught(self, text):
        assert one_another.contact_details(text)

    def test_ordinary_words_pass(self):
        assert not one_another.contact_details("Six months clean today. Please pray I make it to seven.")

    def test_signs_of_risk_mean_care_not_posting(self):
        assert one_another.screen("I don't want to be here anymore", {"flagged": []}) == "care"
        assert one_another.screen("tired", {"flagged": ["self-harm/intent"], "self_harm_intent": True}) == "care"

    def test_hateful_posts_are_refused_but_violence_goes_to_a_person(self):
        assert one_another.screen("...", {"flagged": ["hate"]}) == "refuse"
        assert one_another.screen("He hit me again last night.", {"flagged": ["violence"]}) == "desk"
        assert one_another.screen("Pray for my exams", {"flagged": [], "error": "APIError"}) == "desk"

    def test_kind_words_cover_both_kinds_and_text_needs_no_lookup(self):
        assert {w["for"] for w in one_another.KIND_WORDS.values()} == {"burden", "rejoice"}
        assert one_another.kind_word("not-alone", "KJV") == {"id": "not-alone", "text": "You're not alone in this."}
        assert one_another.kind_word("made-up", "KJV") is None


# ---------------------------------------------------------------------------
# The wall's routes
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("signed_in")
class TestWallRoutes:
    def share(self, body, kind="burden"):
        return client.post("/me/refuge/posts", json={"kind": kind, "body": body}, headers=HEADERS)

    def test_links_are_refused_before_anything_is_checked_or_saved(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(one_another, "moderate", lambda text: pytest.fail("shouldn't reach moderation"))
        assert self.share("join us at www.example.org").status_code == 422
        assert not db.written

    def test_a_writer_who_may_not_be_safe_is_cared_for_and_nothing_is_posted(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(one_another, "moderate", lambda text: {"flagged": [], "self_harm_intent": False, "error": None})
        resp = self.share("I want to die")
        assert resp.json() == {"outcome": "care"}
        assert not db.written

    def test_a_good_post_waits_on_the_desk(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(one_another, "moderate", lambda text: {"flagged": [], "self_harm_intent": False, "error": None})
        resp = self.share("  Got the all clear from the doctor!  ", kind="rejoice")
        assert resp.json()["outcome"] == "waiting"
        table, method, row = db.written[-1]
        assert (table, method) == ("refuge_posts", "insert")
        assert row["status"] == "pending" and row["user_id"] == USER.id and row["kind"] == "rejoice"
        assert row["body"] == "Got the all clear from the doctor!"

    def test_three_a_day(self, monkeypatch):
        use_db(monkeypatch, FakeDb(counts={"refuge_posts": one_another.POSTS_PER_DAY}))
        monkeypatch.setattr(one_another, "moderate", lambda text: pytest.fail("shouldn't reach moderation"))
        assert self.share("one more").status_code == 429

    def test_the_wall_is_approved_posts_by_other_people(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        assert client.get("/me/refuge/wall", headers=HEADERS).status_code == 200
        assert db.filtered("refuge_posts", "status", "approved")
        assert db.filtered("refuge_posts", "user_id", USER.id, method="neq")

    def test_the_writer_never_sees_the_desks_words(self, monkeypatch):
        mine = [{"id": POST_ID, "kind": "burden", "body": "x", "status": "removed", "created_at": "2026-11-01T00:00:00+00:00"}]
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": mine}))
        body = client.get("/me/refuge/wall", headers=HEADERS).json()
        assert body["mine"][0]["status"] == "not_shared"
        assert "review_note" not in body["mine"][0]

    def test_nobody_can_pray_for_their_own_post(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": USER.id, "kind": "burden", "status": "approved"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/react", headers=HEADERS).status_code == 400

    def test_posts_waiting_on_the_desk_cant_be_responded_to(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "pending"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/react", headers=HEADERS).status_code == 404

    def test_kind_words_must_match_the_post(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved"}]}))
        resp = client.post(f"/me/refuge/posts/{POST_ID}/kind-words", json={"choice": "rejoicing"}, headers=HEADERS)
        assert resp.status_code == 422

    def test_a_report_takes_it_off_the_wall(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/report", json={"reason": "names someone"}, headers=HEADERS).status_code == 200
        assert ("refuge_posts", "update", {"status": "reported"}) in db.written


class TestDesk:
    def test_signed_in_is_not_enough(self, monkeypatch, signed_in):
        monkeypatch.setattr(settings, "admin_emails", "keeper@example.com")
        assert client.get("/admin/refuge", headers=HEADERS).status_code == 403

    def test_admins_see_the_queue_without_who_wrote_it(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: ADMIN)
        monkeypatch.setattr(settings, "admin_emails", " Keeper@Example.com , other@example.com")
        rows = [{"id": POST_ID, "kind": "burden", "body": "x", "status": "pending", "auto_check": {}, "created_at": "now"}]
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": rows}))
        body = client.get("/admin/refuge", headers=HEADERS).json()
        assert [p["id"] for p in body["pending"]] == [POST_ID]
        select = next(args for table, method, args in db.calls if table == "refuge_posts" and method == "select")
        assert "user_id" not in select[0]

    def test_approving_puts_it_on_the_wall(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: ADMIN)
        monkeypatch.setattr(settings, "admin_emails", "keeper@example.com")
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID}]}))
        assert client.post(f"/admin/refuge/{POST_ID}", json={"action": "approve"}, headers=HEADERS).json() == {"status": "approved"}
        assert db.written[-1][2]["status"] == "approved"

    def test_nobody_is_an_admin_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", "")
        assert not auth.is_admin(ADMIN)


# ---------------------------------------------------------------------------
# Talk with Aquila
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("signed_in")
class TestTalkRoute:
    def test_runs_the_graph_in_listening_mode_and_never_traces_it(self, monkeypatch):
        seen = {}

        async def fake_invoke(state, config):
            seen.update(state=state, config=config)
            return {"answer": "I'm glad you told me.", "care": False, "citations": []}

        monkeypatch.setattr(refuge.agent, "ainvoke", fake_invoke)
        messages = [{"role": "aquila", "content": "I'm here."}, {"role": "user", "content": "I got the job"}]
        resp = client.post("/me/refuge/talk", json={"messages": messages}, headers=HEADERS)
        assert resp.json() == {"reply": "I'm glad you told me.", "care": False, "verses": []}
        assert seen["state"]["mode"] == "listen" and seen["state"]["query"] == "I got the job"
        assert seen["config"] == {"callbacks": []}

    def test_the_last_word_must_be_theirs(self):
        resp = client.post("/me/refuge/talk", json={"messages": [{"role": "aquila", "content": "hi"}]}, headers=HEADERS)
        assert resp.status_code == 422

    def test_keeping_a_talk_titles_it_from_their_words(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        messages = [{"role": "aquila", "content": "I'm here."}, {"role": "user", "content": "Help me plan my year"}]
        client.post("/me/refuge/talks", json={"messages": messages}, headers=HEADERS)
        row = db.written[-1][2]
        assert row["title"] == "Help me plan my year" and row["user_id"] == USER.id


def test_listen_mode_has_its_own_entry():
    assert graph._entry({"mode": "listen"}) == "listen"
    assert graph._entry({}) == "classify_intent"


def verse(book, chapter, n):
    return Verse(book=book, chapter=chapter, verse=n, text="...", translation="KJV")


class TestUnlistedReferences:
    def test_only_listed_verses_pass(self):
        listed = [verse("Psalms", 34, 18)]
        assert nodes.unlisted_references("The LORD is near (Psalm 34:18).", listed) == []
        assert nodes.unlisted_references("Read Jeremiah 29:11 tonight.", listed) == ["Jeremiah 29:11"]

    def test_a_range_needs_every_verse(self):
        assert nodes.unlisted_references("Psalm 34:17-18", [verse("Psalms", 34, 18)]) == ["Psalms 34:17"]


class FakeLLM:
    """Stands in for both ChatOpenAI clients: a fixed care check, and replies
    handed out in order."""

    def __init__(self, check=None, replies=()):
        self.check, self.replies, self.prompts = check, list(replies), []

    def with_structured_output(self, schema):
        return type("Structured", (), {"invoke": lambda _, messages, config=None: self.check})()

    def invoke(self, messages, config=None):
        self.prompts.append(messages[0].content)
        return type("Reply", (), {"content": self.replies.pop(0)})()


class TestListen:
    def run(self, monkeypatch, text, check, replies, verses=()):
        warm = FakeLLM(replies=replies)
        monkeypatch.setattr(nodes, "_llm", FakeLLM(check=check))
        monkeypatch.setattr(nodes, "_warm_llm", warm)
        monkeypatch.setattr(nodes, "hybrid_retrieve", lambda query, translation, k: list(verses))
        state = {"mode": "listen", "query": text, "history": [{"role": "user", "content": text}], "translation": "KJV"}
        return nodes.listen(state, config=None), warm

    def test_words_of_risk_count_even_if_the_model_misses_them(self, monkeypatch):
        result, warm = self.run(monkeypatch, "honestly I want to die", nodes.CareCheck(at_risk=False, wants_verse=False), ["I'm so glad you told me."])
        assert result["care"] is True
        assert nodes.CARE_INSTRUCTION in warm.prompts[0]

    def test_an_invented_verse_is_written_out(self, monkeypatch):
        listed = [verse("Psalms", 34, 18)]
        result, warm = self.run(
            monkeypatch, "Could I have a verse?", nodes.CareCheck(at_risk=False, wants_verse=True),
            ["Try Jeremiah 29:11.", "Still Jeremiah 29:11.", "I'm here with you."], verses=listed,
        )
        assert result["answer"] == "I'm here with you."
        assert result["citations"] == [] and result["verses"] == []
        assert "No verses are listed" in warm.prompts[-1]

    def test_a_listed_verse_is_cited(self, monkeypatch):
        listed = [verse("Psalms", 34, 18)]
        result, _ = self.run(
            monkeypatch, "yes please", nodes.CareCheck(at_risk=False, wants_verse=True),
            ["Here's one: Psalms 34:18."], verses=listed,
        )
        assert result["citations"] == listed and result["care"] is False


# ---------------------------------------------------------------------------
# Conversations now live with Aquila: renaming one
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("signed_in")
def test_renaming_a_conversation_stays_inside_ones_own(monkeypatch):
    db = use_db(monkeypatch, FakeDb(rows={"chat_sessions": [{"id": POST_ID, "title": "old", "created_at": "now"}]}))
    resp = client.patch(f"/me/sessions/{POST_ID}", json={"title": "  Romans   with the group "}, headers=HEADERS)
    assert resp.json()["title"] == "Romans with the group"
    assert db.filtered("chat_sessions", "user_id", USER.id)


def test_refuge_requires_sign_in():
    assert client.get("/me/refuge").status_code == 401
    assert client.post("/me/refuge/talk", json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 401
