"""The hearth's pure logic (embers, plan day, verse of the day) and its
routes' auth gates. No network: Supabase is never reached."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

import app.main as main
from app import auth, hearth
from app.retrieval import parse_reference

client = TestClient(main.app)
TODAY = date(2026, 11, 4)  # a Wednesday


class TestEmbers:
    def test_week_ends_today_with_weekday_labels(self):
        e = hearth.compute_embers(set(), TODAY)
        assert [d["label"] for d in e["week"]] == ["Th", "Fr", "Sa", "Su", "Mo", "Tu", "We"]
        assert e["week"][-1] == {"day": "2026-11-04", "label": "We", "lit": False, "today": True}
        assert e["streak"] == 0 and e["lit_today"] is False

    def test_streak_counts_back_from_today(self):
        days = {TODAY - timedelta(days=i) for i in range(5)}
        e = hearth.compute_embers(days, TODAY)
        assert e["streak"] == 5 and e["lit_today"] is True

    def test_streak_survives_until_today_is_lit(self):
        days = {TODAY - timedelta(days=i) for i in range(1, 4)}
        assert hearth.compute_embers(days, TODAY)["streak"] == 3

    def test_gap_breaks_streak(self):
        days = {TODAY, TODAY - timedelta(days=2)}
        assert hearth.compute_embers(days, TODAY)["streak"] == 1


class TestGoalComingUp:
    def goal(self, due_in, **extra):
        return {"id": f"g{due_in}", "kind": "goal", "status": "growing", "due_in": due_in, "measure": None, **extra}

    def test_soonest_within_two_weeks(self):
        pebbles = [self.goal(10), self.goal(3), self.goal(30), self.goal(None)]
        assert hearth.goal_coming_up(pebbles, TODAY)["id"] == "g3"

    def test_leaves_out_late_reached_and_set_aside_goals(self):
        pebbles = [
            self.goal(-1),
            self.goal(2, measure={"fraction": 1.0}),
            self.goal(4, status="set_aside"),
            {"id": "h", "kind": "habit", "status": "growing", "due_in": 1},
        ]
        assert hearth.goal_coming_up(pebbles, TODAY) is None


class TestFastUnderway:
    def fast(self, fid, starts_on, days=3):
        return {"id": fid, "kind": "full", "detail": None, "intention": None, "starts_on": starts_on, "days": days, "status": "active", "finished_on": None}

    def test_the_fast_begun_first_with_its_day(self):
        fasts = [self.fast("later", "2026-11-04"), self.fast("first", "2026-11-03")]
        picked = hearth.fast_underway(fasts, TODAY)
        assert picked["id"] == "first" and picked["progress"]["day"] == 2 and picked["progress"]["of"] == 3

    def test_one_planned_ahead_waits(self):
        assert hearth.fast_underway([self.fast("ahead", "2026-11-09")], TODAY) is None


class TestPlanToday:
    plan = {
        "id": "p1",
        "start_date": "2026-11-01",
        "days": 3,
        "schedule": [
            {"day": 1, "references": ["Genesis 1"]},
            {"day": 2, "references": ["Genesis 2"]},
            {"day": 3, "references": ["Genesis 3"]},
        ],
        "completed_days": [1],
    }

    def test_day_number_and_refs(self):
        p = hearth.plan_today(self.plan, date(2026, 11, 2))
        assert p["day"] == 2 and p["refs"] == ["Genesis 2"]
        assert p["done_today"] is False and p["completed"] == 1 and p["progress_pct"] == 33.3

    def test_clamps_before_start_and_after_end(self):
        assert hearth.plan_today(self.plan, date(2026, 10, 1))["day"] == 1
        assert hearth.plan_today(self.plan, date(2027, 1, 1))["day"] == 3

    def test_missing_completed_days_column(self):
        plan = {k: v for k, v in self.plan.items() if k != "completed_days"}
        assert hearth.plan_today(plan, date(2026, 11, 1))["completed"] == 0


class TestVerseOfTheDay:
    def test_every_reference_parses(self):
        for ref in hearth.VERSES_OF_THE_DAY:
            parsed = parse_reference(ref)
            assert parsed and parsed.verse_start, ref
            assert parsed.verse_end - parsed.verse_start <= 2, ref

    def test_same_day_same_verse_next_day_changes(self):
        assert hearth.verse_of_the_day_ref(TODAY) == hearth.verse_of_the_day_ref(TODAY)
        assert hearth.verse_of_the_day_ref(TODAY) != hearth.verse_of_the_day_ref(TODAY + timedelta(days=1))


class TestParseToday:
    def test_rejects_far_dates_and_bad_input(self):
        assert hearth._parse_today(None) == date.today()
        assert hearth._parse_today("1999-01-01") == date.today()
        assert hearth._parse_today((date.today() + timedelta(days=1)).isoformat()) == date.today() + timedelta(days=1)


class TestRoutes:
    def test_home_requires_sign_in(self):
        assert client.get("/me/home").status_code == 401
        assert client.post("/me/plans/x/progress", json={"day": 1, "done": True}).status_code == 401

    def test_plan_routes_require_sign_in(self):
        assert client.get("/me/plans").status_code == 401
        assert client.post("/me/plans/build", json={"request": "The Gospels in a month"}).status_code == 401
        assert client.delete("/me/plans/x").status_code == 401

    def test_providers_reports_google_off_by_default(self):
        assert client.get("/auth/providers").json() == {"google": False}
        assert client.get("/auth/google", follow_redirects=False).status_code == 404

    def test_google_url_uses_implicit_flow_shape(self):
        url = auth.google_authorize_url("http://localhost:8000/")
        assert url.endswith("/auth/v1/authorize?provider=google&redirect_to=http%3A%2F%2Flocalhost%3A8000%2F")
