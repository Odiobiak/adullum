"""Memory verses: the spaced-repetition schedule, how a card's status is
read, and the add route's checks. Supabase and auth are faked out; nothing
here makes a real network call."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import auth, memorize
from app.auth import AuthUser
from app.schemas import Verse

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
TODAY = date(2026, 11, 5)
NEW = {"reps": 0, "interval_days": 0, "ease": 2.5}


class TestNextReview:
    def test_good_grows_one_then_three_then_by_ease(self):
        first = memorize.next_review(NEW, "good", TODAY)
        assert (first["reps"], first["interval_days"], first["due"]) == (1, 1, "2026-11-06")
        second = memorize.next_review(first, "good", TODAY)
        assert second["interval_days"] == 3
        third = memorize.next_review(second, "good", TODAY)
        assert third["interval_days"] == round(3 * 2.5)
        assert third["last_reviewed"] == TODAY.isoformat()

    def test_again_starts_over_tomorrow_with_less_ease(self):
        card = {"reps": 4, "interval_days": 20, "ease": 2.5}
        after = memorize.next_review(card, "again", TODAY)
        assert (after["reps"], after["interval_days"], after["due"]) == (0, 1, "2026-11-06")
        assert after["ease"] == 2.3

    def test_hard_is_a_little_longer_than_last_time(self):
        after = memorize.next_review({"reps": 3, "interval_days": 10, "ease": 2.5}, "hard", TODAY)
        assert after["interval_days"] == 12
        assert after["ease"] == 2.35

    def test_ease_never_drops_below_the_floor(self):
        after = memorize.next_review({"reps": 0, "interval_days": 1, "ease": 1.35}, "again", TODAY)
        assert after["ease"] == memorize.MIN_EASE

    def test_gap_is_capped(self):
        after = memorize.next_review({"reps": 9, "interval_days": 150, "ease": 2.5}, "good", TODAY)
        assert after["interval_days"] == memorize.MAX_INTERVAL_DAYS


class TestStatus:
    def test_due_learning_and_learned(self):
        assert memorize.card_status({"due": "2026-11-05", "interval_days": 30}, TODAY) == "due"
        assert memorize.card_status({"due": "2026-11-01", "interval_days": 3}, TODAY) == "due"
        assert memorize.card_status({"due": "2026-11-08", "interval_days": 3}, TODAY) == "learning"
        assert memorize.card_status({"due": "2026-12-20", "interval_days": 45}, TODAY) == "learned"

    def test_summary_counts(self):
        rows = [
            {"due": "2026-11-05", "interval_days": 1},
            {"due": "2026-11-09", "interval_days": 4},
            {"due": "2027-01-01", "interval_days": 60},
        ]
        assert memorize.memorize_summary(rows, TODAY) == {"total": 3, "due": 1, "learned": 1}


class TestAddRoute:
    @pytest.fixture(autouse=True)
    def signed_in(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)

    def post(self, ref):
        return client.post("/me/memorize", json={"ref": ref, "translation": "KJV"}, headers={"Authorization": "Bearer t"})

    def test_rejects_a_whole_chapter(self):
        resp = self.post("John 3")
        assert resp.status_code == 422
        assert "whole chapter" in resp.json()["detail"]

    def test_rejects_a_long_passage(self):
        assert self.post("Psalms 119:1-20").status_code == 422

    def test_rejects_something_that_is_not_a_reference(self):
        assert self.post("my favourite verse").status_code == 422

    def test_reads_the_words_from_the_database(self, monkeypatch):
        """The text being learned comes from the verses table, never the browser."""
        inserted = {}

        class FakeTable:
            def insert(self, row):
                inserted.update(row)
                return self

            def execute(self):
                return type("Result", (), {"data": [{**inserted, "id": "v1", "reps": 0, "interval_days": 0, "ease": 2.5, "last_reviewed": None, "created_at": "now"}]})()

        monkeypatch.setattr(memorize, "lookup_by_reference", lambda ref, tr: [
            Verse(book="John", chapter=3, verse=16, text="For God so loved the world,", translation=tr, source="reference"),
        ])
        monkeypatch.setattr(memorize, "get_supabase", lambda: type("Db", (), {"table": lambda self, name: FakeTable()})())

        body = self.post("jn 3:16").json()
        assert inserted["user_id"] == USER.id
        assert inserted["verse_text"] == "For God so loved the world,"
        assert (inserted["book"], inserted["translation"]) == ("John", "KJV")
        assert body["ref"] == "John 3:16" and body["already"] is False


def test_memorize_requires_sign_in():
    assert client.get("/me/memorize").status_code == 401
    assert client.post("/me/memorize", json={"ref": "John 3:16"}).status_code == 401
