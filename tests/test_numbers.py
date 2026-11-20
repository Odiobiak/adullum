"""The desk's Numbers tab (app/numbers.py): admins only, counts passed through
from admin_numbers, and the server's memory shown even before the migration.
No network call: the database is a stand-in."""

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError

import app.main as main
from app import auth, numbers
from app.auth import AuthUser
from app.config import settings

client = TestClient(main.app)
ADMIN = AuthUser(id="33333333-3333-3333-3333-333333333333", email="keeper@example.com", email_confirmed=True)
HEADERS = {"Authorization": "Bearer token"}


class FakeDb:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("Response", (), {"data": self.result})()


@pytest.fixture
def as_admin(monkeypatch):
    monkeypatch.setattr(auth, "_verify", lambda token: ADMIN)
    monkeypatch.setattr(settings, "admin_emails", ADMIN.email)


def test_only_admins_see_the_numbers(monkeypatch):
    assert client.get("/admin/numbers").status_code == 401
    monkeypatch.setattr(auth, "_verify", lambda token: AuthUser(id="x", email="ruth@example.com", email_confirmed=True))
    assert client.get("/admin/numbers", headers=HEADERS).status_code == 403


def test_counts_come_from_admin_numbers_for_the_browsers_day(monkeypatch, as_admin):
    db = FakeDb(result={"accounts": 12, "active_today": 3})
    monkeypatch.setattr(numbers, "get_supabase", lambda: db)
    today = numbers.parse_today(None).isoformat()
    body = client.get(f"/admin/numbers?today={today}", headers=HEADERS).json()
    assert db.calls == [("admin_numbers", {"p_today": today})]
    assert body["counts"] == {"accounts": 12, "active_today": 3} and body["setup"] is None
    assert set(body["server"]) == {"memory_mb", "limit_mb", "threads", "up_hours"}


def test_before_the_migration_it_says_what_to_run_and_still_shows_the_server(monkeypatch, as_admin):
    missing = APIError({"code": "PGRST202", "message": "Could not find the function admin_numbers"})
    monkeypatch.setattr(numbers, "get_supabase", lambda: FakeDb(error=missing))
    body = client.get("/admin/numbers", headers=HEADERS).json()
    assert body["counts"] is None and "20261128_admin_numbers.sql" in body["setup"]
    assert body["server"]["threads"] >= 1


def test_memory_reads_none_where_the_system_doesnt_say(tmp_path):
    assert numbers._read_kb(str(tmp_path / "absent")) is None
    status = tmp_path / "status"
    status.write_text("Name:\tpython\nVmRSS:\t  262144 kB\n")
    assert numbers._mb(numbers._read_kb(str(status), "VmRSS:")) == 256
    limit = tmp_path / "memory.max"
    limit.write_text("max\n")
    assert numbers._read_kb(str(limit)) is None
    limit.write_text(f"{512 * 1024 * 1024}\n")
    assert numbers._mb(numbers._read_kb(str(limit))) == 512
