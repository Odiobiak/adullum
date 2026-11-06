"""Reminders: where a notification may lead, when a weekly reminder falls
(clock changes included), and the send job's claim-send-repeat cycle, run
against a small fake database. Nothing here sends a real notification."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import reminders
from app.reminders import ReminderIn, Repeat, inside_link, is_stale, next_occurrence

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Links and shapes
# ---------------------------------------------------------------------------
def test_a_notification_only_opens_a_page_in_adullum():
    assert inside_link("#church/c/0b1e-22") == "#church/c/0b1e-22"
    assert inside_link("") is None
    for bad in ("https://example.com", "javascript:alert(1)", "//evil.example", "#church/<script>"):
        with pytest.raises(ValueError):
            inside_link(bad)


def test_reminder_shapes():
    with pytest.raises(ValueError):
        ReminderIn(key="has spaces", title="x", remind_at=datetime.now(UTC))
    with pytest.raises(ValueError):
        Repeat(day=0, time="09:00", zone="Mars/Olympus", before=30)
    assert ReminderIn(key="event:abc:2026-11-21:youth", title="Youth", url="#church").url == "#church"


# ---------------------------------------------------------------------------
# When a weekly reminder falls
# ---------------------------------------------------------------------------
def test_next_sunday_in_the_churchs_own_zone():
    rule = {"day": 0, "time": "09:00", "zone": "Africa/Lagos", "before": 30}
    friday = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    # Sunday 08:30 in Lagos (UTC+1) is 07:30 UTC.
    assert next_occurrence(rule, friday) == datetime(2026, 11, 8, 7, 30, tzinfo=UTC)


def test_once_the_reminder_time_has_passed_it_moves_to_next_week():
    rule = {"day": 0, "time": "09:00", "zone": "Africa/Lagos", "before": 30}
    sunday_after = datetime(2026, 11, 8, 7, 45, tzinfo=UTC)  # 08:45 in Lagos
    assert next_occurrence(rule, sunday_after) == datetime(2026, 11, 15, 7, 30, tzinfo=UTC)


def test_a_clock_change_never_shifts_the_reminder():
    rule = {"day": 0, "time": "10:00", "zone": "America/New_York", "before": 60}
    # 25 Oct 2026 is still daylight time (UTC-4); 1 Nov is standard time (UTC-5).
    assert next_occurrence(rule, datetime(2026, 10, 20, tzinfo=UTC)) == datetime(2026, 10, 25, 13, 0, tzinfo=UTC)
    assert next_occurrence(rule, datetime(2026, 10, 26, tzinfo=UTC)) == datetime(2026, 11, 1, 14, 0, tzinfo=UTC)


def test_stale_reminders():
    now = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
    assert not is_stale(datetime(2026, 11, 6, 9, 0, tzinfo=UTC), now)
    assert is_stale(datetime(2026, 11, 6, 5, 0, tzinfo=UTC), now)


# ---------------------------------------------------------------------------
# The send job, against a fake database
# ---------------------------------------------------------------------------
class _Result:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


class _Query:
    """Just enough of the Supabase query builder for run_due."""

    def __init__(self, rows):
        self.rows, self.filters, self.changes = rows, [], None

    def select(self, *_a, **_k):
        return self

    def update(self, changes):
        self.changes = changes
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def is_(self, col, _null):
        self.filters.append(lambda r: r.get(col) is None)
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: r[col] <= val)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        hit = [r for r in self.rows if all(f(r) for f in self.filters)]
        if self.changes is not None:
            for r in hit:
                r.update(self.changes)
        return _Result([dict(r) for r in hit])


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Query(self.rows)


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(reminders.push, "configured", lambda: True)
    monkeypatch.setattr(reminders.push, "notify_user", lambda user, payload: out.append((user, payload)) or 1)
    return out


def test_due_reminders_are_sent_once_and_weekly_ones_move_on(monkeypatch, sent):
    now = datetime(2026, 11, 8, 7, 31, tzinfo=UTC)
    rows = [
        {"id": "1", "user_id": "u1", "key": "event:a", "title": "Youth conference", "body": "Harvest House", "url": "#church/c/a",
         "remind_at": "2026-11-08T07:00:00+00:00", "repeat": None, "sent_at": None},
        {"id": "2", "user_id": "u1", "key": "gathering:a", "title": "Sunday service, Harvest House", "body": "Starts in 30 minutes.", "url": "#church/c/a",
         "remind_at": "2026-11-08T07:30:00+00:00", "repeat": {"day": 0, "time": "09:00", "zone": "Africa/Lagos", "before": 30}, "sent_at": None},
        {"id": "3", "user_id": "u2", "key": "event:old", "title": "Long gone", "body": None, "url": None,
         "remind_at": "2026-11-07T20:00:00+00:00", "repeat": None, "sent_at": None},
        {"id": "4", "user_id": "u1", "key": "event:later", "title": "Not yet", "body": None, "url": None,
         "remind_at": "2026-11-09T07:00:00+00:00", "repeat": None, "sent_at": None},
    ]
    monkeypatch.setattr(reminders, "get_supabase", lambda: _FakeDb(rows))
    assert reminders.run_due(now) == 2
    assert [p["title"] for _, p in sent] == ["Youth conference", "Sunday service, Harvest House"]
    assert sent[0][1]["url"] == "#church/c/a" and sent[0][1]["tag"] == "event:a"
    by_id = {r["id"]: r for r in rows}
    assert by_id["1"]["sent_at"] is not None                    # done
    assert by_id["2"]["sent_at"] is None                        # weekly: waiting again...
    assert by_id["2"]["remind_at"] == "2026-11-15T07:30:00+00:00"  # ...for next Sunday
    assert by_id["3"]["sent_at"] is not None                    # stale: claimed, never sent
    assert by_id["4"]["sent_at"] is None                        # not due yet
    # A second run finds nothing left to send.
    sent.clear()
    assert reminders.run_due(now) == 0 and not sent


def test_nothing_is_sent_without_push_set_up(monkeypatch):
    monkeypatch.setattr(reminders.push, "configured", lambda: False)
    assert reminders.run_due() == 0
    assert reminders.run_live() == 0


# ---------------------------------------------------------------------------
# Routes that need no account
# ---------------------------------------------------------------------------
def test_the_scheduled_send_needs_the_secret(monkeypatch):
    from app.main import app

    client = TestClient(app)
    monkeypatch.setattr(reminders.settings, "cron_secret", "")
    assert client.post("/internal/send-reminders", headers={"X-Cron-Secret": ""}).status_code == 403
    monkeypatch.setattr(reminders.settings, "cron_secret", "s3cret")
    assert client.post("/internal/send-reminders", headers={"X-Cron-Secret": "wrong"}).status_code == 403
    monkeypatch.setattr(reminders, "run_due", lambda: 2)
    monkeypatch.setattr(reminders, "run_live", lambda: 0)
    monkeypatch.setattr(reminders, "_run_digest", lambda: 1)
    assert client.post("/internal/send-reminders", headers={"X-Cron-Secret": "s3cret"}).json() == {"sent": 2, "live": 0, "digests": 1}


def test_push_key_is_null_until_set_up(monkeypatch):
    from app.main import app

    monkeypatch.setattr(reminders.settings, "vapid_public_key", "")
    assert TestClient(app).get("/push/key").json() == {"key": None}
