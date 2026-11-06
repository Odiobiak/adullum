"""Reflections: which stretch of time a reflection looks back on and ahead to,
how a stretch is named, the halfway check-in, the small counting helpers, what
a tracked goal becomes in Pebbles, and that the routes stay inside one
person's reflections. Supabase and auth are faked out; nothing here makes a
real network call."""

from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, reflections
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
HEADERS = {"Authorization": "Bearer t"}
SOMEONE = "22222222-2222-2222-2222-222222222222"


class FakeQuery:
    def __init__(self, rows, calls):
        self.rows, self.calls = rows, calls

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            return self

        return method

    def execute(self):
        return type("Result", (), {"data": self.rows, "count": len(self.rows)})()


class FakeDb:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return FakeQuery(self.rows, self.calls)


def dates(period: reflections.Period) -> tuple[str, str, str, str]:
    return tuple(d.isoformat() for d in (period.starts_on, period.ends_on, period.ahead_starts_on, period.ahead_ends_on))


class TestPeriods:
    def test_a_month_looks_at_the_one_ending(self):
        assert dates(reflections.period_for("month", date(2026, 10, 28))) == ("2026-10-01", "2026-10-31", "2026-11-01", "2026-11-30")

    def test_early_in_a_month_it_looks_at_the_one_just_gone(self):
        assert dates(reflections.period_for("month", date(2026, 11, 3)))[:2] == ("2026-10-01", "2026-10-31")

    def test_a_month_can_be_moved(self):
        assert dates(reflections.period_for("month", date(2026, 12, 20), shift=1)) == ("2027-01-01", "2027-01-31", "2027-02-01", "2027-02-28")

    def test_a_quarter_and_the_one_after_it(self):
        assert dates(reflections.period_for("quarter", date(2026, 12, 10))) == ("2026-10-01", "2026-12-31", "2027-01-01", "2027-03-31")

    def test_two_weeks_into_a_quarter_it_still_looks_back(self):
        assert dates(reflections.period_for("quarter", date(2027, 1, 9)))[:2] == ("2026-10-01", "2026-12-31")

    def test_a_year_looks_back_on_last_year_until_march(self):
        assert dates(reflections.period_for("year", date(2027, 2, 10))) == ("2026-01-01", "2026-12-31", "2027-01-01", "2027-12-31")
        assert dates(reflections.period_for("year", date(2026, 11, 6)))[0] == "2026-01-01"

    def test_a_season_and_one_as_long_after_it(self):
        period = reflections.season_period(date(2026, 3, 1), date(2026, 9, 30))
        assert dates(period) == ("2026-03-01", "2026-09-30", "2026-10-01", "2027-04-30")

    def test_a_season_of_days_is_followed_by_as_many_days(self):
        period = reflections.season_period(date(2026, 3, 4), date(2026, 3, 13))
        assert dates(period)[2:] == ("2026-03-14", "2026-03-23")

    def test_a_season_must_end_after_it_starts_and_not_run_for_ever(self):
        for start, end in ((date(2026, 5, 1), date(2026, 4, 1)), (date(2020, 1, 1), date(2026, 1, 1))):
            with pytest.raises(HTTPException):
                reflections.season_period(start, end)


class TestLabels:
    @pytest.mark.parametrize(
        ("start", "end", "label"),
        [
            (date(2026, 1, 1), date(2026, 12, 31), "2026"),
            (date(2026, 10, 1), date(2026, 10, 31), "October 2026"),
            (date(2026, 10, 1), date(2026, 12, 31), "Oct to Dec 2026"),
            (date(2026, 11, 1), date(2027, 2, 28), "Nov 2026 to Feb 2027"),
            (date(2026, 3, 4), date(2026, 9, 30), "4 Mar to 30 Sep 2026"),
            (date(2026, 10, 1), date(2027, 4, 20), "1 Oct 2026 to 20 Apr 2027"),
        ],
    )
    def test_a_stretch_is_named_as_people_say_it(self, start, end, label):
        assert reflections.period_label(start, end) == label


class TestCheckIn:
    def test_two_weeks_from_the_middle_of_a_year(self):
        start, end = date(2027, 1, 1), date(2027, 12, 31)
        assert not reflections.in_check_in(date(2027, 7, 1), start, end)
        assert reflections.in_check_in(date(2027, 7, 2), start, end)
        assert reflections.in_check_in(date(2027, 7, 15), start, end)
        assert not reflections.in_check_in(date(2027, 7, 16), start, end)

    def test_a_month_has_no_check_in(self):
        assert not reflections.in_check_in(date(2026, 11, 15), date(2026, 11, 1), date(2026, 11, 30))


class TestCounting:
    def test_verses_of_one_chapter_count_together(self):
        refs = ["Psalms 23:1", "Psalms 23:4", "John 15:4", "Romans 8", "John 15", "Psalms 23", "not a ref"]
        assert reflections.top_passages(refs, limit=2) == ["Psalms 23", "John 15"]

    def test_weeks_a_habit_was_kept(self):
        # Meant for two days a week: kept in the first week, not the second.
        days = {date(2027, 1, 4), date(2027, 1, 6), date(2027, 1, 12)}
        assert reflections.weeks_kept(days, 2, date(2027, 1, 4), date(2027, 1, 17)) == {"kept": 1, "weeks": 2}

    def test_a_pebble_in_a_reflections_words(self):
        assert reflections.seed_status({"status": "fulfilled"}) == "reached"
        assert reflections.seed_status({"status": "growing"}) == "on_the_way"
        assert reflections.seed_progress({"target": 12, "progress": 9}) == "9 of 12"
        assert reflections.seed_progress({"steps": []}) is None


class TestPebbles:
    def test_each_kind_of_goal_becomes_the_right_pebble(self):
        habit = reflections.seed_for({"text": "Go to church more", "kind": "habit", "per_week": 1}, "Spiritual", "2027")
        assert habit["kind"] == "habit" and habit["per_week"] == 1 and habit["note"] == "Spiritual, from your reflection on 2027"
        number = reflections.seed_for({"text": "Pay off the move", "kind": "number", "target": 1200, "unit": "pounds"}, "Money", "2027")
        assert number["kind"] == "goal" and number["target"] == 1200 and number["unit"] == "pounds"
        dated = reflections.seed_for({"text": "Find a small group", "kind": "date", "due_on": "2027-03-31"}, "Social", "2027")
        assert dated["due_on"] == "2027-03-31"

    def test_a_hope_and_an_empty_number_stay_out_of_pebbles(self):
        assert reflections.seed_for({"text": "Pray with someone", "kind": "hope"}, "Spiritual", "2027") is None
        assert reflections.seed_for({"text": "Save", "kind": "number"}, "Money", "2027") is None

    def test_only_the_persons_own_numbers_become_pebbles(self):
        own = reflections.seed_for_number({"label": "Sundays at church", "target": 40}, "2027")
        assert own["title"] == "40 Sundays at church" and own["target"] == 40
        assert reflections.seed_for_number({"key": "verses", "label": "verses learned", "target": 12}, "2027") is None


class TestStartingLookBack:
    def test_it_starts_with_the_usual_counts_and_last_times_areas(self):
        previous = {"look_ahead": {"areas": [{"name": "Social", "aim": "steady", "goals": []}]}}
        start = reflections.starting_look_back({"entries": 48, "answered": 12, "days": 200}, [], previous)
        assert [n["key"] for n in start["numbers"]] == ["entries", "answered"]
        assert start["numbers"][0] == {"key": "entries", "label": "journal entries", "value": "48"}
        assert start["areas"] == [{"name": "Social", "rating": None, "note": ""}]


class TestRoutes:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    def test_saving_normalizes_the_verse_and_stays_inside_ones_own(self, monkeypatch):
        db = FakeDb([{"id": SOMEONE, "updated_at": "now", "look_ahead": {"verse_ref": "John 15:4"}}])
        monkeypatch.setattr(reflections, "get_supabase", lambda: db)
        body = {"look_ahead": {"word": "Abide", "verse_ref": "john 15:4", "areas": [{"name": "Social", "aim": "steady", "goals": [{"text": "Go out more", "kind": "habit", "per_week": 1, "track": True}]}]}}
        resp = client.put(f"/me/reflections/{SOMEONE}", json=body, headers=HEADERS)
        assert resp.status_code == 200
        patch = next(args[0] for name, args in db.calls if name == "update")
        assert patch["look_ahead"]["verse_ref"] == "John 15:4"
        assert ("eq", ("user_id", USER.id)) in db.calls

    def test_a_verse_that_isnt_one_yet_is_kept_as_typed(self, monkeypatch):
        db = FakeDb([{"id": SOMEONE, "updated_at": "now", "look_ahead": {"verse_ref": "Jhn"}}])
        monkeypatch.setattr(reflections, "get_supabase", lambda: db)
        resp = client.put(f"/me/reflections/{SOMEONE}", json={"look_ahead": {"verse_ref": "  Jhn  "}}, headers=HEADERS)
        assert resp.status_code == 200 and resp.json()["verse_error"]
        patch = next(args[0] for name, args in db.calls if name == "update")
        assert patch["look_ahead"]["verse_ref"] == "Jhn"

    def test_a_name_is_tidied_and_a_blank_one_cleared(self, monkeypatch):
        db = FakeDb([{"id": SOMEONE, "updated_at": "now", "title": "A year of new beginnings", "look_ahead": {}}])
        monkeypatch.setattr(reflections, "get_supabase", lambda: db)
        client.put(f"/me/reflections/{SOMEONE}", json={"title": "  A year of   new beginnings "}, headers=HEADERS)
        client.put(f"/me/reflections/{SOMEONE}", json={"title": "   "}, headers=HEADERS)
        patches = [args[0] for name, args in db.calls if name == "update"]
        assert patches[0]["title"] == "A year of new beginnings" and patches[1]["title"] is None

    def test_a_rating_that_isnt_one_of_the_four_is_refused(self, monkeypatch):
        monkeypatch.setattr(reflections, "get_supabase", lambda: FakeDb([]))
        body = {"look_back": {"areas": [{"name": "Work", "rating": "amazing"}]}}
        assert client.put(f"/me/reflections/{SOMEONE}", json=body, headers=HEADERS).status_code == 422

    def test_someone_elses_reflection_is_a_404(self, monkeypatch):
        monkeypatch.setattr(reflections, "get_supabase", lambda: FakeDb([]))
        assert client.put(f"/me/reflections/{SOMEONE}", json={"lay_down": {"grateful": "x"}}, headers=HEADERS).status_code == 404
        assert client.post(f"/me/reflections/{SOMEONE}/keep", json={}, headers=HEADERS).status_code == 404

    def test_a_season_needs_its_dates(self, monkeypatch):
        monkeypatch.setattr(reflections, "get_supabase", lambda: FakeDb([]))
        assert client.get("/me/reflections/period?span=season", headers=HEADERS).status_code == 422

    def test_the_period_preview_names_both_stretches(self, monkeypatch):
        monkeypatch.setattr(reflections, "get_supabase", lambda: FakeDb([]))
        resp = client.get("/me/reflections/period?span=season&starts_on=2026-03-01&ends_on=2026-09-30", headers=HEADERS)
        assert resp.status_code == 200
        assert resp.json()["label"] == "Mar to Sep 2026" and resp.json()["ahead_label"] == "Oct 2026 to Apr 2027" and resp.json()["last_word"] is None


def test_reflections_require_sign_in():
    assert client.get("/me/reflections").status_code == 401
