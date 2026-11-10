"""The prayer list: passage normalising, the note Aquila keeps about a
prayer, the home summary, and that the routes stay inside one person's list.
Supabase and auth are faked out; nothing here makes a real network call."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, memory, prayers
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")


class FakeQuery:
    """Records every chained call and returns canned rows from execute()."""

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


class TestNormalizePassage:
    def test_canonical_forms(self):
        assert prayers.normalize_passage("phil 4:6-7") == "Philippians 4:6-7"
        assert prayers.normalize_passage("Psalm 23") == "Psalms 23"
        assert prayers.normalize_passage("  ") is None
        assert prayers.normalize_passage(None) is None

    def test_rejects_what_is_not_a_reference(self):
        with pytest.raises(HTTPException) as e:
            prayers.normalize_passage("my sister's job")
        assert e.value.status_code == 422


class TestMemoryText:
    def test_open(self):
        assert prayers.prayer_memory_text({"body": "My sister's new job", "status": "open"}) == (
            'They are praying about: "My sister\'s new job"'
        )

    def test_answered_with_and_without_a_note(self):
        base = {"body": "My sister's new job", "status": "answered"}
        assert prayers.prayer_memory_text({**base, "answer_note": "She got it."}).endswith(': "She got it."')
        assert prayers.prayer_memory_text(base).endswith("count it answered.")


def test_summary_counts_open_and_recent_answers():
    today = date(2026, 11, 5)
    recent = datetime(2026, 10, 20, tzinfo=timezone.utc).isoformat()
    old = (datetime(2026, 11, 5, tzinfo=timezone.utc) - timedelta(days=90)).isoformat()
    rows = [
        {"id": "a", "body": "newest open", "status": "open", "answered_at": None},
        {"id": "b", "body": "older open", "status": "open", "answered_at": None},
        {"id": "c", "body": "answered lately", "status": "answered", "answered_at": recent},
        {"id": "d", "body": "answered long ago", "status": "answered", "answered_at": old},
    ]
    summary = prayers.prayer_summary(rows, today)
    assert (summary["open"], summary["answered_recently"], summary["total"]) == (2, 1, 4)
    assert summary["latest_open"]["id"] == "a"
    assert summary["for_today"]["status"] == "open"


def test_a_different_open_request_each_day():
    rows = [{"id": i, "status": "open"} for i in "abc"]
    day = date(2026, 11, 5)
    picks = [prayers.prayer_summary(rows, day + timedelta(days=n))["for_today"]["id"] for n in range(3)]
    assert sorted(picks) == ["a", "b", "c"]
    assert prayers.prayer_summary([], day)["for_today"] is None


def test_remembers_only_answers_old_enough_to_look_back_on():
    today = date(2026, 11, 5)
    stamp = lambda days: (datetime(2026, 11, 5, tzinfo=timezone.utc) - timedelta(days=days)).isoformat()
    rows = [
        {"id": "fresh", "body": "last week", "status": "answered", "answer_note": None, "answered_at": stamp(7)},
        {"id": "open", "body": "still open", "status": "open", "answered_at": None},
        {"id": "old", "body": "the job", "status": "answered", "answer_note": "She got it.", "answered_at": stamp(60)},
    ]
    picked = prayers.answered_to_remember(rows, today)
    assert picked == {"id": "old", "body": "the job", "answer_note": "She got it.", "answered_at": stamp(60)}
    assert prayers.answered_to_remember(rows[:2], today) is None


class TestRoutes:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        # Note-taking is exercised in TestMemoryText; here it must not reach OpenAI.
        monkeypatch.setattr(prayers, "_remember", lambda user, prayer: None)

    HEADERS = {"Authorization": "Bearer t"}

    def test_list_is_filtered_to_the_signed_in_person(self, monkeypatch):
        db = FakeDb([])
        monkeypatch.setattr(prayers, "get_supabase", lambda: db)
        assert client.get("/me/prayers", params={"status": "open"}, headers=self.HEADERS).status_code == 200
        assert ("eq", ("user_id", USER.id)) in db.calls
        assert ("eq", ("status", "open")) in db.calls

    def test_marking_answered_sets_the_date(self, monkeypatch):
        db = FakeDb([{"id": "p1", "body": "x", "status": "answered"}])
        monkeypatch.setattr(prayers, "get_supabase", lambda: db)
        resp = client.patch(
            "/me/prayers/22222222-2222-2222-2222-222222222222",
            json={"status": "answered", "answer_note": "  She got the job.  "},
            headers=self.HEADERS,
        )
        assert resp.status_code == 200
        patch = next(args[0] for name, args in db.calls if name == "update")
        assert patch["status"] == "answered" and patch["answered_at"]
        assert patch["answer_note"] == "She got the job."
        assert ("eq", ("user_id", USER.id)) in db.calls

    def test_reopening_clears_the_answer(self, monkeypatch):
        db = FakeDb([{"id": "p1", "body": "x", "status": "open"}])
        monkeypatch.setattr(prayers, "get_supabase", lambda: db)
        client.patch("/me/prayers/22222222-2222-2222-2222-222222222222", json={"status": "open"}, headers=self.HEADERS)
        patch = next(args[0] for name, args in db.calls if name == "update")
        assert (patch["status"], patch["answered_at"], patch["answer_note"]) == ("open", None, None)

    def test_someone_elses_prayer_is_a_404(self, monkeypatch):
        monkeypatch.setattr(prayers, "get_supabase", lambda: FakeDb([]))
        resp = client.patch("/me/prayers/22222222-2222-2222-2222-222222222222", json={"body": "edit"}, headers=self.HEADERS)
        assert resp.status_code == 404

    def test_a_bad_passage_is_rejected_before_saving(self, monkeypatch):
        db = FakeDb([])
        monkeypatch.setattr(prayers, "get_supabase", lambda: db)
        resp = client.post("/me/prayers", json={"body": "Peace at work", "passage_ref": "not a verse"}, headers=self.HEADERS)
        assert resp.status_code == 422
        assert not any(name == "insert" for name, _ in db.calls)


def test_remember_respects_memory_switched_off(monkeypatch):
    """With memory off, the old note is cleared and no new one is written."""
    db = FakeDb([])
    stored = []
    monkeypatch.setattr(prayers, "get_supabase", lambda: db)
    monkeypatch.setattr(memory, "memory_enabled", lambda user_id: False)
    monkeypatch.setattr(memory, "store_note", lambda *a, **k: stored.append(a))
    prayers._remember(USER, {"id": "p1", "body": "x", "status": "open"})
    assert ("eq", ("prayer_id", "p1")) in db.calls
    assert stored == []


def test_prayers_require_sign_in():
    assert client.get("/me/prayers").status_code == 401


# ---------------------------------------------------------------------------
# The week of prayer
# ---------------------------------------------------------------------------
class TestWeekOfPrayer:
    TODAY = date(2026, 11, 5)  # a Thursday

    def test_any_prayer_lights_the_day_and_requests_are_counted_on_their_own(self):
        marks = [
            {"day": "2026-11-02", "prayer_id": "p1"},
            {"day": "2026-11-05", "prayer_id": None},
            {"day": "2026-11-05", "prayer_id": "p1"},
            {"day": "2026-11-01", "prayer_id": "p1"},  # last Sunday: not this week
        ]
        week = prayers.prayer_week(marks, self.TODAY)
        assert [d["done"] for d in week["week"]] == [True, False, False, True, False, False, False]
        assert week["days_this_week"] == 2 and week["prayed_today"] is True
        assert week["by_prayer"] == {"p1": {"today": True, "this_week": 2}}

    def test_praying_for_a_request_is_not_the_same_as_i_prayed_today(self):
        week = prayers.prayer_week([{"day": "2026-11-05", "prayer_id": "p1"}], self.TODAY)
        assert week["prayed_today"] is False and week["week"][3]["done"] is True

    def test_marking_a_request_checks_it_is_theirs(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        monkeypatch.setattr(prayers, "get_supabase", lambda: FakeDb([]))
        resp = client.post("/me/prayers/log", json={"prayer_id": "22222222-2222-2222-2222-222222222222"}, headers={"Authorization": "Bearer t"})
        assert resp.status_code == 404

    def test_taking_back_i_prayed_today_touches_only_the_general_mark(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        db = FakeDb([])
        monkeypatch.setattr(prayers, "get_supabase", lambda: db)
        resp = client.post("/me/prayers/log", json={"prayed": False}, headers={"Authorization": "Bearer t"})
        assert resp.status_code == 200
        assert ("is_", ("prayer_id", "null")) in db.calls and ("eq", ("user_id", USER.id)) in db.calls
