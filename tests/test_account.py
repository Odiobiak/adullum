"""Tests for app/account.py: the data export and closing an account, against
a small in-memory stand-in for the Supabase client."""

import io
import json
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.account as account
import app.main as main
from app import auth
from app.auth import AuthUser, require_user

ME = AuthUser(id="u1", email="Ruth@example.com")


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.deleting = db, table, [], False

    def select(self, *_a, **_k):
        return self

    def delete(self):
        self.deleting = True
        return self

    def eq(self, column, value):
        self.filters.append(lambda r: r.get(column) == value)
        return self

    def in_(self, column, values):
        self.filters.append(lambda r: r.get(column) in values)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def range(self, *_a):
        return self

    def execute(self):
        rows = [r for r in self.db.tables.get(self.table, []) if all(f(r) for f in self.filters)]
        if self.deleting:
            self.db.tables[self.table] = [r for r in self.db.tables[self.table] if r not in rows]
        return type("Result", (), {"data": rows})()


class FakeBucket:
    def __init__(self, files):
        self.files = files

    def list(self, prefix, _opts=None):
        depth = prefix.count("/") + 1
        names = {p.split("/")[depth] for p in self.files if p.startswith(prefix + "/")}
        return [{"name": n, "id": "f" if f"{prefix}/{n}" in self.files else None} for n in sorted(names)]

    def download(self, path):
        return self.files[path]

    def remove(self, paths):
        for p in paths:
            self.files.pop(p, None)


class FakeDB:
    def __init__(self):
        self.tables = {
            "profiles": [{"id": "u1", "display_name": "Ruth"}, {"id": "u2", "display_name": "Naomi"}],
            "journal_entries": [{"id": "j1", "user_id": "u1", "body": "mine"}, {"id": "j2", "user_id": "u2", "body": "hers"}],
            "user_memories": [{"id": 1, "user_id": "u1", "content": "likes Psalms", "embedding": [0.1]}],
            "chat_sessions": [{"id": "s1", "user_id": "u1"}, {"id": "s2", "user_id": "u2"}],
            "chat_messages": [{"id": 1, "session_id": "s1", "content": "hi"}, {"id": 2, "session_id": "s2", "content": "not mine"}],
            "reading_plans": [{"id": "p1", "user_id": "u1"}, {"id": "p2", "user_id": "u2"}],
        }
        self.bucket = FakeBucket({"u1/n1/a.jpg": b"jpg", "u2/n9/b.jpg": b"other"})
        self.deleted_users = []
        self.fail_delete = False
        self.auth = type("Auth", (), {"admin": self})()
        self.storage = type("Storage", (), {"from_": lambda _s, _b: self.bucket})()

    def table(self, name):
        return FakeQuery(self, name)

    def delete_user(self, user_id):
        if self.fail_delete:
            raise RuntimeError("auth is down")
        self.deleted_users.append(user_id)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(account, "get_supabase", lambda: fake)
    main.app.dependency_overrides[require_user] = lambda: ME
    yield fake
    main.app.dependency_overrides.clear()


client = TestClient(main.app)


def test_export_holds_only_my_data(db):
    resp = client.get("/me/export")
    assert resp.status_code == 200
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    read = lambda name: json.loads(archive.read(name))
    assert [e["body"] for e in read("journal_entries.json")] == ["mine"]
    assert [m["content"] for m in read("chat_messages.json")] == ["hi"]
    assert read("profile.json") == [{"id": "u1", "display_name": "Ruth"}]
    assert "embedding" not in read("user_memories.json")[0]
    assert read("refuge_posts.json") == []  # a table with no rows (or no migration) is still listed
    assert archive.read("sermon-photos/n1/a.jpg") == b"jpg"
    assert not any("n9" in n for n in archive.namelist())
    assert "README.txt" in archive.namelist()


def test_delete_needs_the_email_typed(db):
    resp = client.request("DELETE", "/me", json={"confirm": "someone@else.com"})
    assert resp.status_code == 422
    assert db.deleted_users == []


def test_delete_closes_the_account_and_clears_what_does_not_cascade(db):
    resp = client.request("DELETE", "/me", json={"confirm": " ruth@EXAMPLE.com "})
    assert resp.status_code == 200
    assert db.deleted_users == ["u1"]
    assert [p["id"] for p in db.tables["reading_plans"]] == ["p2"]
    assert list(db.bucket.files) == ["u2/n9/b.jpg"]


def test_a_failed_delete_removes_nothing(db):
    db.fail_delete = True
    resp = client.request("DELETE", "/me", json={"confirm": "ruth@example.com"})
    assert resp.status_code == 502
    assert len(db.tables["reading_plans"]) == 2
    assert "u1/n1/a.jpg" in db.bucket.files


def test_forget_user_drops_only_that_persons_tokens():
    later = time.time() + 60
    auth._token_cache.update({"t1": (ME, later), "t2": (AuthUser(id="u2", email=None), later)})
    auth.forget_user("u1")
    assert "t1" not in auth._token_cache and "t2" in auth._token_cache
    auth._token_cache.clear()
