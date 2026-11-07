"""Fasting: where a fast stands on a given day, which start dates are
allowed, and that the routes stay inside one person's fasts. Supabase and
auth are faked out; nothing here makes a real network call."""

from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, fasting
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
HEADERS = {"Authorization": "Bearer t"}
TODAY = date(2026, 11, 5)
# The routes trust the browser's date only within a day of the server's
# (app/days.py::parse_today), so route tests send the real one.
NOW = date.today()


class FakeQuery:
    def __init__(self, rows, calls):
        self.rows, self.calls = rows, calls

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.calls.append((name, args))
            return self

        return method

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class FakeDb:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def table(self, name):
        self.calls.append(("table", (name,)))
        return FakeQuery(self.rows, self.calls)


class TestProgress:
    def test_which_day_it_is(self):
        progress = fasting.fast_progress({"starts_on": "2026-11-04", "days": 3}, TODAY)
        assert progress == {"day": 2, "of": 3, "fraction": 2 / 3, "ends_on": "2026-11-06", "starts_in": 0, "last_day_reached": False}

    def test_a_planned_fast_has_not_started(self):
        progress = fasting.fast_progress({"starts_on": "2026-11-08", "days": 21}, TODAY)
        assert progress["day"] == 0 and progress["starts_in"] == 3

    def test_after_the_last_day_it_stays_full(self):
        progress = fasting.fast_progress({"starts_on": "2026-11-01", "days": 1}, TODAY)
        assert progress["day"] == 1 and progress["last_day_reached"] is True

    def test_a_finished_fast_counts_to_the_day_it_finished(self):
        fast = {"starts_on": "2026-11-01", "days": 21, "finished_on": "2026-11-03"}
        assert fasting.fast_progress(fast, TODAY)["day"] == 3


class TestStart:
    def test_up_to_a_week_ago_or_two_months_ahead(self):
        fasting.check_start(date(2026, 10, 29), TODAY)
        fasting.check_start(date(2027, 1, 4), TODAY)
        for start in (date(2026, 10, 28), date(2027, 1, 5)):
            with pytest.raises(HTTPException):
                fasting.check_start(start, TODAY)


class TestRoutes:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    def test_starting_a_fast_saves_it_for_this_person(self, monkeypatch):
        db = FakeDb([{"id": "f1", "starts_on": NOW.isoformat(), "days": 3, "status": "active"}])
        monkeypatch.setattr(fasting, "get_supabase", lambda: db)
        resp = client.post("/me/fasts", json={"kind": "daniel", "days": 3, "intention": "  Wisdom  ", "today": NOW.isoformat()}, headers=HEADERS)
        assert resp.status_code == 200 and resp.json()["progress"]["of"] == 3
        row = next(args[0] for name, args in db.calls if name == "insert")
        assert row["user_id"] == USER.id and row["intention"] == "Wisdom" and row["kind"] == "daniel"

    def test_too_long_a_fast_is_refused(self, monkeypatch):
        monkeypatch.setattr(fasting, "get_supabase", lambda: FakeDb([]))
        assert client.post("/me/fasts", json={"days": 41}, headers=HEADERS).status_code == 422

    def test_finishing_records_the_day_and_stays_inside_ones_own(self, monkeypatch):
        db = FakeDb([{"id": "f1", "starts_on": "2026-11-04", "days": 3, "status": "finished", "finished_on": NOW.isoformat()}])
        monkeypatch.setattr(fasting, "get_supabase", lambda: db)
        resp = client.patch("/me/fasts/22222222-2222-2222-2222-222222222222", json={"status": "finished", "reflection": "Quieter.", "today": NOW.isoformat()}, headers=HEADERS)
        assert resp.status_code == 200
        patch = next(args[0] for name, args in db.calls if name == "update")
        assert patch["finished_on"] == NOW.isoformat() and patch["reflection"] == "Quieter."
        assert ("eq", ("user_id", USER.id)) in db.calls

    def test_someone_elses_fast_is_a_404(self, monkeypatch):
        monkeypatch.setattr(fasting, "get_supabase", lambda: FakeDb([]))
        resp = client.patch("/me/fasts/22222222-2222-2222-2222-222222222222", json={"status": "finished"}, headers=HEADERS)
        assert resp.status_code == 404


def test_fasts_require_sign_in():
    assert client.get("/me/fasts").status_code == 401
