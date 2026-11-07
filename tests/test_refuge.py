"""Refuge: the pure helpers, the wall's automatic check and routes, the admin
desk's gate, Aquila's listening mode, and renaming a conversation. Supabase,
auth, OpenAI and the agent are all faked out; nothing here makes a real
network call."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, cave, desk, one_another, refuge
from app.agent import graph, nodes
from app.auth import AuthUser
from app.config import settings
from app.schemas import Verse

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
ADMIN = AuthUser(id="33333333-3333-3333-3333-333333333333", email="keeper@example.com", email_confirmed=True)
HEADERS = {"Authorization": "Bearer t"}
POST_ID = "22222222-2222-2222-2222-222222222222"
# A post that went up yesterday and is on the wall for a while yet.
LIVE = {"approved_at": "2026-01-01T00:00:00+00:00", "expires_at": "2999-01-01T00:00:00+00:00"}


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

    def rpc(self, name, params):
        """A database function: answered from rows["rpc:<name>"]."""
        self.calls.append(("rpc", name, params))
        return FakeQuery(self, f"rpc:{name}")

    def rpc_params(self, name):
        return [params for kind, called, params in self.calls if kind == "rpc" and called == name]

    def filtered(self, table, column, value, method="eq"):
        return (table, method, (column, value)) in self.calls


@pytest.fixture
def signed_in(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: USER)


def use_db(monkeypatch, db):
    for module in (one_another, refuge, cave, desk):
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

    def test_a_goal_is_measured_by_its_number_or_its_steps(self):
        assert refuge.goal_measure({"target": 12, "progress": 3}) == {"by": "number", "done": 3.0, "of": 12.0, "fraction": 0.25}
        # Going past the number still fills the bar, and no further.
        assert refuge.goal_measure({"target": 10, "progress": 14})["fraction"] == 1.0
        steps = [{"text": "Call Mum", "done": True}, {"text": "Book it", "done": False}]
        assert refuge.goal_measure({"target": None, "steps": steps}) == {"by": "steps", "done": 1, "of": 2, "fraction": 0.5}
        assert refuge.goal_measure({"target": None, "steps": []}) is None

    def test_a_goal_is_tracked_one_way_and_a_number_wins(self):
        assert refuge.goal_tracking(["Read Ruth"], 12) == ([], 12)
        assert refuge.goal_tracking(["Read Ruth", " "], None) == ([{"text": "Read Ruth", "done": False}], None)
        assert refuge.goal_tracking([], None) == ([], None)


# ---------------------------------------------------------------------------
# Pebbles: goals and habits
# ---------------------------------------------------------------------------
SEED_ID = "44444444-4444-4444-4444-444444444444"


class TestPebbles:
    def test_a_habit_comes_with_this_week_and_a_goal_with_its_progress(self, monkeypatch, signed_in):
        habit = {"id": "h", "kind": "habit", "title": "Walk", "per_week": 5, "status": "growing", "steps": [], "target": None, "due_on": None}
        goal = {"id": "g", "kind": "goal", "title": "Read 12 books", "status": "growing", "steps": [], "target": 12, "progress": 3, "due_on": "2026-11-10"}
        db = use_db(monkeypatch, FakeDb({
            "refuge_seeds": [habit, goal],
            # Thursday 5 November: Monday and today are done, last Sunday doesn't count this week.
            "refuge_checkins": [{"seed_id": "h", "day": "2026-11-02"}, {"seed_id": "h", "day": "2026-11-05"}, {"seed_id": "h", "day": "2026-11-01"}],
        }))
        monkeypatch.setattr(refuge, "parse_today", lambda today: date(2026, 11, 5))
        rows = {r["id"]: r for r in client.get("/me/refuge/seeds", headers=HEADERS).json()}
        assert rows["h"]["week_done"] == 2 and rows["h"]["tended_today"] is True
        assert [m["done"] for m in rows["h"]["week"]] == [True, False, False, True, False, False, False]
        assert rows["g"]["measure"]["fraction"] == 0.25 and rows["g"]["due_in"] == 5
        assert db.filtered("refuge_seeds", "user_id", USER.id)

    def test_home_shows_only_active_habits_and_whether_they_prayed_today(self, monkeypatch, signed_in):
        from app import hearth

        habit = {"id": "h", "kind": "habit", "title": "Walk", "per_week": 5, "status": "growing", "steps": [], "target": None, "due_on": None}
        set_aside = {"id": "s", "kind": "habit", "title": "Run", "per_week": 3, "status": "set_aside", "steps": [], "target": None, "due_on": None}
        goal = {"id": "g", "kind": "goal", "title": "Read Ruth", "status": "growing", "steps": [], "target": None, "due_on": None}
        db = use_db(monkeypatch, FakeDb({
            "profiles": [{"id": USER.id, "display_name": "Ruth"}],
            "refuge_seeds": [habit, set_aside, goal],
            "prayer_days": [{"day": date.today().isoformat()}],
        }))
        monkeypatch.setattr(hearth, "get_supabase", lambda: db)
        # The real date: the server trusts the browser's only within a day of its own.
        body = client.get(f"/me/home?today={date.today().isoformat()}", headers=HEADERS).json()
        assert [p["id"] for p in body["pebbles"]] == ["h"]
        assert body["prayers"]["prayed_today"] is True
        # Only the general "I prayed today", the same mark the Prayers tab's button keeps.
        assert db.filtered("prayer_days", "user_id", USER.id) and db.filtered("prayer_days", "prayer_id", "null", "is_")

    def test_only_habits_are_marked_day_by_day(self, monkeypatch, signed_in):
        use_db(monkeypatch, FakeDb({"refuge_seeds": [{"id": SEED_ID, "kind": "goal"}]}))
        resp = client.post(f"/me/refuge/seeds/{SEED_ID}/tend", json={"tended": True}, headers=HEADERS)
        assert resp.status_code == 422

    def test_a_past_day_this_week_can_be_marked_but_not_tomorrow(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb({"refuge_seeds": [{"id": SEED_ID, "kind": "habit"}]}))
        monkeypatch.setattr(refuge, "parse_today", lambda today: date(2026, 11, 5))
        ok = client.post(f"/me/refuge/seeds/{SEED_ID}/tend", json={"day": "2026-11-03"}, headers=HEADERS)
        assert ok.status_code == 200 and ok.json()["day"] == "2026-11-03"
        assert ("refuge_checkins", "upsert", {"seed_id": SEED_ID, "user_id": USER.id, "day": "2026-11-03"}) in db.written
        later = client.post(f"/me/refuge/seeds/{SEED_ID}/tend", json={"day": "2026-11-06"}, headers=HEADERS)
        assert later.status_code == 422

    def test_a_number_goal_keeps_no_steps(self, monkeypatch, signed_in):
        db = use_db(monkeypatch, FakeDb())
        body = {"kind": "goal", "title": "Read 12 books", "target": 12, "unit": "  books ", "steps": ["one"], "due_on": "2026-12-31"}
        assert client.post("/me/refuge/seeds", json=body, headers=HEADERS).status_code == 200
        row = next(w[2] for w in db.written if w[0] == "refuge_seeds")
        assert row["steps"] == [] and row["target"] == 12 and row["unit"] == "books" and row["due_on"] == "2026-12-31"

    def test_hopes_and_prayers_are_no_longer_pebbles(self, monkeypatch, signed_in):
        use_db(monkeypatch, FakeDb())
        for kind in ("hope", "prayer"):
            assert client.post("/me/refuge/seeds", json={"kind": kind, "title": "x"}, headers=HEADERS).status_code == 422


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

    def test_a_post_the_check_is_clear_about_goes_up_straight_away(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(one_another, "moderate", lambda text: {"flagged": [], "self_harm_intent": False, "error": None})
        resp = self.share("  Got the all clear from the doctor!  ", kind="rejoice")
        assert resp.json()["outcome"] == "shared"
        table, method, row = db.written[-1]
        assert (table, method) == ("refuge_posts", "insert")
        assert row["status"] == "approved" and row["approved_at"] and row["user_id"] == USER.id and row["kind"] == "rejoice"
        assert row["body"] == "Got the all clear from the doctor!"

    @pytest.mark.parametrize("check", [
        {"flagged": ["violence"], "self_harm_intent": False, "error": None},  # someone describing harm done to them
        {"flagged": [], "self_harm_intent": False, "error": "APIError"},      # the check didn't run
    ])
    def test_a_post_the_check_isnt_sure_of_waits_for_a_person(self, monkeypatch, check):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(one_another, "moderate", lambda text: check)
        assert self.share("He hit me again last night.").json()["outcome"] == "waiting"
        assert db.written[-1][2]["status"] == "pending" and "approved_at" not in db.written[-1][2]

    def test_with_going_up_straight_away_off_every_post_waits(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(settings, "amens_auto_approve", False)
        monkeypatch.setattr(one_another, "moderate", lambda text: {"flagged": [], "self_harm_intent": False, "error": None})
        assert self.share("Pray for my exams").json()["outcome"] == "waiting"
        assert db.written[-1][2]["status"] == "pending"

    def test_three_a_day(self, monkeypatch):
        use_db(monkeypatch, FakeDb(counts={"refuge_posts": one_another.POSTS_PER_DAY}))
        monkeypatch.setattr(one_another, "moderate", lambda text: pytest.fail("shouldn't reach moderation"))
        assert self.share("one more").status_code == 429

    def test_the_wall_is_this_persons_fair_page_and_never_says_who_wrote(self, monkeypatch):
        page = [{"id": f"p{i}", "kind": "burden", "body": "x", "created_at": "now", "amen_count": i, "reacted": False, "sent_kind_word": False}
                for i in range(one_another.WALL_PAGE + 1)]
        db = use_db(monkeypatch, FakeDb(rows={"rpc:amens_wall": page}))
        body = client.get("/me/refuge/wall?page=1", headers=HEADERS).json()
        params = db.rpc_params("amens_wall")[0]
        assert params["viewer"] == USER.id and params["skip"] == one_another.WALL_PAGE
        assert len(body["posts"]) == one_another.WALL_PAGE and body["has_more"] is True
        assert body["posts"][3]["reactions"] == 3
        assert all("user_id" not in p for p in body["posts"])
        # Later pages carry only the wall, not the person's own posts.
        assert "mine" not in body

    def test_opening_the_wall_marks_when_they_last_looked(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        client.get("/me/refuge/wall", headers=HEADERS)
        visit = next(row for table, method, row in db.written if table == "refuge_wall_visits")
        assert visit["user_id"] == USER.id

    def test_the_writer_never_sees_the_desks_words(self, monkeypatch):
        mine = [{"id": POST_ID, "kind": "burden", "body": "x", "status": "removed", "created_at": "2026-11-01T00:00:00+00:00"}]
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": mine}))
        body = client.get("/me/refuge/wall", headers=HEADERS).json()
        assert body["mine"][0]["status"] == "not_shared"
        assert "review_note" not in body["mine"][0]

    def test_kind_words_come_back_counted_by_word(self, monkeypatch):
        mine = [{"id": POST_ID, "kind": "burden", "body": "x", "status": "approved", "created_at": "now", "amen_count": 40, "kind_word_count": 3}]
        tally = [{"post_id": POST_ID, "choice": "not-alone", "n": 2}, {"post_id": POST_ID, "choice": "god-sees", "n": 1}]
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": mine, "rpc:kind_word_tally": tally}))
        post = client.get("/me/refuge/wall", headers=HEADERS).json()["mine"][0]
        assert post["reactions"] == 40 and post["kind_word_count"] == 3
        assert [(w["id"], w["count"]) for w in post["kind_words"]] == [("not-alone", 2), ("god-sees", 1)]

    def test_nobody_can_pray_for_their_own_post(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": USER.id, "kind": "burden", "status": "approved", **LIVE}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/react", headers=HEADERS).status_code == 400

    def test_posts_waiting_on_the_desk_cant_be_responded_to(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "pending"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/react", headers=HEADERS).status_code == 404

    def test_kind_words_must_match_the_post(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved", **LIVE}]}))
        resp = client.post(f"/me/refuge/posts/{POST_ID}/kind-words", json={"choice": "rejoicing"}, headers=HEADERS)
        assert resp.status_code == 422

    def test_an_answered_prayer_takes_good_news_words(self, monkeypatch):
        post = {"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved", "answered_at": "2026-11-01T00:00:00+00:00", **LIVE}
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [post]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/kind-words", json={"choice": "rejoicing"}, headers=HEADERS).status_code == 200
        assert client.post(f"/me/refuge/posts/{POST_ID}/kind-words", json={"choice": "not-alone"}, headers=HEADERS).status_code == 422

    def test_a_post_that_has_left_the_wall_cant_be_responded_to(self, monkeypatch):
        post = {"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved", "approved_at": "2026-01-01T00:00:00+00:00", "expires_at": "2026-01-15T00:00:00+00:00"}
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [post]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/react", headers=HEADERS).status_code == 404

    def test_a_report_takes_it_off_the_wall(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/report", json={"reason": "names someone"}, headers=HEADERS).status_code == 200
        assert ("refuge_posts", "update", {"status": "reported"}) in db.written

    def test_a_new_report_goes_to_the_desk_with_why(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb(rows={
            "refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved"}],
            "refuge_reports": [{"post_id": POST_ID}],  # the upsert added one
        }))
        heard = []
        monkeypatch.setattr(desk, "report_received", lambda *args: heard.append(args))
        body = {"category": "danger", "reason": "  they sound scared "}
        assert client.post(f"/me/refuge/posts/{POST_ID}/report", json=body, headers=HEADERS).status_code == 200
        report = next(row for table, method, row in db.written if table == "refuge_reports")
        assert report["category"] == "danger" and report["reason"] == "they sound scared"
        assert heard == [(POST_ID, "approved", "danger", "they sound scared")]

    def test_a_report_needs_a_known_reason(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": "someone", "kind": "burden", "status": "approved"}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/report", json={"category": "boring"}, headers=HEADERS).status_code == 422


class TestDesk:
    def test_signed_in_is_not_enough(self, monkeypatch, signed_in):
        monkeypatch.setattr(settings, "admin_emails", "keeper@example.com")
        assert client.get("/admin/refuge", headers=HEADERS).status_code == 403

    @pytest.fixture
    def as_admin(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: ADMIN)
        monkeypatch.setattr(settings, "admin_emails", " Keeper@Example.com , other@example.com")

    def test_admins_see_the_queue_without_who_wrote_it(self, monkeypatch, as_admin):
        rows = [
            {"id": "older", "kind": "burden", "body": "x", "status": "pending", "auto_check": {}, "created_at": "2026-11-01"},
            {"id": POST_ID, "kind": "burden", "body": "y", "status": "reported", "auto_check": {}, "created_at": "2026-11-02"},
        ]
        reports = [{"post_id": POST_ID, "category": "danger", "reason": None, "created_at": "2026-11-03"}]
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": rows, "refuge_reports": reports}, counts={"refuge_posts": 7}))
        body = client.get("/admin/refuge", headers=HEADERS).json()
        # Someone may be in danger, so it jumps the older post.
        assert [p["id"] for p in body["queue"]] == [POST_ID, "older"]
        assert body["queue"][0]["urgent"] and body["queue"][0]["reports"] == [{"category": "danger", "reason": None, "created_at": "2026-11-03"}]
        assert body["stats"]["to_review"] == 2 and body["stats"]["urgent"] == 1 and body["stats"]["on_wall"] == 7
        selects = [args[0] for table, method, args in db.calls if method == "select" and table in ("refuge_posts", "refuge_reports", "refuge_moderation_log")]
        assert selects and all("user_id" not in s for s in selects)

    def test_approving_puts_it_on_the_wall_and_on_the_trail(self, monkeypatch, as_admin):
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"kind": "rejoice", "status": "pending"}], "rpc:desk_decide": "pending"}))
        resp = client.post(f"/admin/refuge/{POST_ID}", json={"action": "approve", "note": "  fine  "}, headers=HEADERS)
        assert resp.json() == {"status": "approved"}
        [params] = db.rpc_params("desk_decide")
        assert params["new_status"] == "approved" and params["actor"] == ADMIN.id and params["note"] == "fine"
        # Good news gets its week from the moment it goes up.
        went_up, ends = datetime.fromisoformat(params["went_up"]), datetime.fromisoformat(params["ends"])
        assert (ends - went_up).days == one_another.LIFETIME_DAYS["rejoice"]

    def test_putting_back_keeps_the_time_it_had(self, monkeypatch, as_admin):
        post = {"kind": "burden", "status": "reported", "approved_at": "2026-11-01T00:00:00+00:00"}
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [post], "rpc:desk_decide": "reported"}))
        client.post(f"/admin/refuge/{POST_ID}", json={"action": "approve"}, headers=HEADERS)
        [params] = db.rpc_params("desk_decide")
        assert params["went_up"] is None and params["ends"] is None

    def test_only_a_post_on_the_wall_can_be_held(self, monkeypatch, as_admin):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"kind": "burden", "status": "pending"}]}))
        assert client.post(f"/admin/refuge/{POST_ID}", json={"action": "hold"}, headers=HEADERS).status_code == 409

    def test_a_second_decision_on_the_same_post_changes_nothing(self, monkeypatch, as_admin):
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"kind": "burden", "status": "removed"}]}))
        assert client.post(f"/admin/refuge/{POST_ID}", json={"action": "remove"}, headers=HEADERS).json() == {"status": "removed"}
        assert not db.rpc_params("desk_decide")

    def test_the_wall_tab_says_how_long_each_post_has(self, monkeypatch, as_admin):
        rows = [{"id": POST_ID, "kind": "burden", "body": "x", "status": "approved", "created_at": "2026-11-01", **LIVE}]
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": rows}))
        post = client.get("/admin/refuge/live?show=ending", headers=HEADERS).json()["posts"][0]
        assert post["on_wall"] and post["days_left"] > 0 and post["reports"] == [] and post["history"] == []

    def test_an_unconfirmed_email_is_never_an_admin(self, monkeypatch):
        # Otherwise anyone could sign up with an admin's address before they do.
        monkeypatch.setattr(settings, "admin_emails", ADMIN.email)
        assert auth.is_admin(ADMIN)
        assert not auth.is_admin(AuthUser(id="x", email=ADMIN.email, email_confirmed=False))

    def test_nobody_is_an_admin_by_default(self, monkeypatch):
        monkeypatch.setattr(settings, "admin_emails", "")
        assert not auth.is_admin(ADMIN)


class TestDeskHelpers:
    def test_violence_or_self_harm_or_danger_is_urgent(self):
        assert desk.check_is_urgent({"flagged": ["violence/graphic"]})
        assert desk.check_is_urgent({"flagged": ["self-harm"]})
        assert not desk.check_is_urgent({"flagged": ["harassment"]}) and not desk.check_is_urgent(None)
        assert desk.is_urgent({"auto_check": {}, "reports": [{"category": "danger"}]})
        assert not desk.is_urgent({"auto_check": {}, "reports": [{"category": "spam"}]})

    def test_a_post_put_back_more_than_once_is_counted(self):
        history = [
            {"action": "report", "from_status": "approved"},
            {"action": "approve", "from_status": "reported"},
            {"action": "hold", "from_status": "approved"},
            {"action": "approve", "from_status": "held"},
            {"action": "approve", "from_status": "pending"},
        ]
        assert desk.times_put_back(history) == 2

    def test_a_report_reads_as_one_line(self):
        assert desk.report_note("danger", None) == "Someone may be in danger"
        assert desk.report_note("spam", "selling") == "It's spam or selling something: selling"
        assert len(desk.report_note("other", "x" * 400)) == 300

    def test_a_report_goes_on_the_trail_without_the_reporter(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb())
        monkeypatch.setattr(desk, "get_supabase", lambda: db)
        monkeypatch.setattr(desk, "alert_admins", lambda: pytest.fail("only danger alerts the admins"))
        desk.report_received(POST_ID, "approved", "unkind", "cruel")
        entry = next(row for table, method, row in db.written if table == "refuge_moderation_log")
        assert entry["to_status"] == "reported" and "user_id" not in entry and "actor_id" not in entry

    def test_danger_alerts_the_admins(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb(rows={"rpc:desk_admin_ids": ["a1", "a2"]}))
        monkeypatch.setattr(desk, "get_supabase", lambda: db)
        monkeypatch.setattr(settings, "admin_emails", "Keeper@example.com")
        from app import push

        sent = []
        monkeypatch.setattr(push, "configured", lambda: True)
        monkeypatch.setattr(push, "notify_user", lambda user_id, payload: sent.append((user_id, payload["url"])) or 1)
        desk.report_received(POST_ID, "approved", "danger", None)
        assert db.rpc_params("desk_admin_ids") == [{"emails": ["keeper@example.com"]}]
        assert sent == [("a1", "#desk"), ("a2", "#desk")]

    def test_the_writer_sees_a_held_post_as_waiting(self):
        assert one_another.WRITER_STATUS["held"] == one_another.WRITER_STATUS["reported"] == "waiting"


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


# ---------------------------------------------------------------------------
# The home screen's Amens card
# ---------------------------------------------------------------------------
class TestAmensGlance:
    """The home card is the one place the wall reaches outside Refuge, so it
    must only ever show the wall's public side, never the person's own posts.
    """

    def test_featured_is_the_newest_post_still_waiting_for_an_amen(self):
        posts = [{"id": "newest"}, {"id": "middle"}, {"id": "oldest"}]
        assert one_another.featured_post(posts, {"newest"}) == {"id": "middle"}
        assert one_another.featured_post(posts, {"newest", "middle", "oldest"}) is None
        assert one_another.featured_post([], set()) is None

    def test_glance_counts_the_week_and_features_someone_elses_post(self, monkeypatch):
        db = use_db(monkeypatch, FakeDb(rows={
            "refuge_amen_days": [{"amens": 5}, {"amens": 7}],
            "rpc:amens_waiting": 3,
            "rpc:amens_wall": [{"id": "first", "kind": "rejoice", "body": "I got the job.", "amen_count": 2, "reacted": False}],
        }))

        glance = one_another.amens_glance(USER)

        assert glance["this_week"] == 12
        assert glance["waiting"] == 3
        assert glance["post"] == {"id": "first", "kind": "rejoice", "body": "I got the job.", "amens": 2}
        # Both read the wall as this person sees it: other people's posts only
        # (amens_wall and amens_waiting leave out the viewer's own).
        assert db.rpc_params("amens_waiting")[0]["viewer"] == USER.id
        assert db.rpc_params("amens_wall")[0]["viewer"] == USER.id
        assert not db.filtered("refuge_posts", "user_id", USER.id)

    def test_a_post_already_prayed_for_isnt_featured(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"rpc:amens_wall": [{"id": "done", "kind": "burden", "body": "x", "amen_count": 9, "reacted": True}]}))
        assert one_another.amens_glance(USER)["post"] is None


# ---------------------------------------------------------------------------
# The evening digest
# ---------------------------------------------------------------------------
class TestDigest:
    def test_the_words_fit_what_came_back(self):
        assert one_another.digest_message(0, 0, 0) is None
        one = one_another.digest_message(1, 0, 0)
        assert one["title"] == "Someone prayed for you today" and one["body"] == "1 person prayed for you."
        many = one_another.digest_message(12, 0, 3)
        assert many["title"] == "People prayed for you today"
        assert many["body"] == "12 people prayed for you and 3 kind words were sent to you."
        both = one_another.digest_message(2, 5, 0)
        assert both["title"] == "From the Amens wall" and both["body"] == "2 people prayed for you and 5 people rejoiced with you."
        assert both["url"] == "#amens"

    def test_it_waits_for_the_writers_evening(self):
        six_utc = datetime(2026, 11, 6, 18, 30, tzinfo=timezone.utc)
        assert one_another.is_evening("Africa/Lagos", six_utc.replace(hour=17))      # 6:30pm in Lagos
        assert not one_another.is_evening("America/New_York", six_utc)              # 1:30pm in New York
        assert one_another.is_evening(None, six_utc) and one_another.is_evening("Not/AZone", six_utc)

    def test_each_writer_is_claimed_before_sending(self, monkeypatch):
        from app import push

        due = [
            {"user_id": "a", "time_zone": None, "prayed": 3, "rejoiced": 0, "kind_words": 0},
            {"user_id": "b", "time_zone": None, "prayed": 1, "rejoiced": 0, "kind_words": 0},  # the other sender claimed it
            {"user_id": "c", "time_zone": None, "prayed": 0, "rejoiced": 0, "kind_words": 0},  # nothing came back
        ]
        claims = {"a": True, "b": False}
        sent = []
        monkeypatch.setattr(push, "configured", lambda: True)
        monkeypatch.setattr(push, "notify_user", lambda user_id, payload: sent.append((user_id, payload["body"])) or 1)
        monkeypatch.setattr(one_another, "_rpc", lambda name, params: due if name == "amens_digest_due" else claims[params["writer"]])
        evening = datetime(2026, 11, 6, 19, 0, tzinfo=timezone.utc)
        assert one_another.run_digest(evening) == 1
        assert sent == [("a", "3 people prayed for you.")]


# ---------------------------------------------------------------------------
# How long a post stays on the wall
# ---------------------------------------------------------------------------
class TestLifetimes:
    NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)

    def request(self, went_up_days_ago, ends_in_days, **extra):
        return {
            "kind": "burden", "status": "approved",
            "approved_at": (self.NOW - timedelta(days=went_up_days_ago)).isoformat(),
            "expires_at": (self.NOW + timedelta(days=ends_in_days)).isoformat(),
            **extra,
        }

    def test_a_prayer_stays_two_weeks_and_good_news_a_week(self):
        assert (one_another.expires_for("burden", self.NOW) - self.NOW).days == 14
        assert (one_another.expires_for("rejoice", self.NOW) - self.NOW).days == 7

    def test_it_can_be_kept_up_only_near_its_end(self):
        assert one_another.kept_up_until(self.request(5, 9), self.NOW) is None
        until = one_another.kept_up_until(self.request(12, 2), self.NOW)
        assert (until - self.NOW).days == 16  # two weeks on from its current end

    def test_one_just_ended_comes_back_for_two_weeks_from_today(self):
        until = one_another.kept_up_until(self.request(15, -1), self.NOW)
        assert (until - self.NOW).days == 14

    def test_never_past_two_months(self):
        until = one_another.kept_up_until(self.request(50, 2), self.NOW)
        assert (until - self.NOW).days == 10  # 60 days from when it went up
        assert one_another.kept_up_until(self.request(60, 0), self.NOW) is None

    def test_good_news_and_answered_prayers_arent_kept_up(self):
        assert one_another.kept_up_until({**self.request(12, 2), "kind": "rejoice"}, self.NOW) is None
        assert one_another.kept_up_until(self.request(12, 2, answered_at="x"), self.NOW) is None

    def test_where_a_writers_post_stands(self):
        standing = one_another.lifetime(self.request(12, 2), self.NOW)
        assert standing == {"on_wall": True, "days_left": 2, "can_keep_up": True, "answered": False}
        assert one_another.lifetime(self.request(20, -6), self.NOW)["on_wall"] is False


@pytest.mark.usefixtures("signed_in")
class TestKeepUpAndAnswered:
    def test_keeping_up_moves_the_end_and_stays_inside_ones_own(self, monkeypatch):
        now = datetime.now(timezone.utc)
        post = {"id": POST_ID, "user_id": USER.id, "kind": "burden", "status": "approved", "kept_up": 0,
                "approved_at": (now - timedelta(days=12)).isoformat(), "expires_at": (now + timedelta(days=2)).isoformat()}
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [post]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/keep-up", headers=HEADERS).status_code == 200
        patch = db.written[-1][2]
        assert patch["kept_up"] == 1 and patch["expires_at"] > post["expires_at"]
        assert db.filtered("refuge_posts", "user_id", USER.id)

    def test_someone_elses_post_cant_be_kept_up(self, monkeypatch):
        use_db(monkeypatch, FakeDb())
        assert client.post(f"/me/refuge/posts/{POST_ID}/keep-up", headers=HEADERS).status_code == 404

    def test_answered_stays_five_days_as_good_news(self, monkeypatch):
        post = {"id": POST_ID, "user_id": USER.id, "kind": "burden", "status": "approved", **LIVE}
        db = use_db(monkeypatch, FakeDb(rows={"refuge_posts": [post]}))
        resp = client.post(f"/me/refuge/posts/{POST_ID}/answered", json={"note": "  Mum's surgery   went well  "}, headers=HEADERS)
        assert resp.status_code == 200
        patch = db.written[-1][2]
        assert patch["answer_note"] == "Mum's surgery went well" and patch["answered_at"] and patch["expires_at"]

    def test_good_news_isnt_marked_answered_and_notes_cant_carry_contact_details(self, monkeypatch):
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": USER.id, "kind": "rejoice", "status": "approved", **LIVE}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/answered", json={}, headers=HEADERS).status_code == 422
        use_db(monkeypatch, FakeDb(rows={"refuge_posts": [{"id": POST_ID, "user_id": USER.id, "kind": "burden", "status": "approved", **LIVE}]}))
        assert client.post(f"/me/refuge/posts/{POST_ID}/answered", json={"note": "call me on 07700 900123"}, headers=HEADERS).status_code == 422
