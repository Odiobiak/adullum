"""Listen: reading the source filter, taking catalog sources in turn, which
sermons a season picks, and that the route keeps the person's churches and
the catalog apart. Feeds, the model and Supabase are faked out; nothing here
makes a real network call."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.main as main
from app import auth, listen
from app.auth import AuthUser

client = TestClient(main.app)
USER = AuthUser(id="11111111-1111-1111-1111-111111111111", email="ruth@example.com")
HEADERS = {"Authorization": "Bearer t"}


class TestSources:
    def test_each_kind_of_source(self):
        assert listen.parse_source(None) == listen.SourceFilter(mine=True, catalog=True)
        assert listen.parse_source("mine") == listen.SourceFilter(mine=True, catalog=False)
        assert listen.parse_source("catalog") == listen.SourceFilter(mine=False, catalog=True)
        assert listen.parse_source("church:abc").church_id == "abc"
        assert listen.parse_source("catalog:keller").catalog_key == "keller"

    @pytest.mark.parametrize("value", ["church:", "catalog:nobody", "everything"])
    def test_anything_else_is_refused(self, value):
        with pytest.raises(HTTPException):
            listen.parse_source(value)

    def test_the_catalog_spans_traditions_and_keys_are_unique(self):
        keys = [s.key for s in listen.CATALOG]
        assert len(keys) == len(set(keys))
        assert len({s.tradition for s in listen.CATALOG}) >= 6
        assert all(s.feed.startswith("https://") for s in listen.CATALOG)


class TestPicking:
    def test_sources_take_turns(self):
        a = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        b = [{"id": "b1"}]
        assert [i["id"] for i in listen.interleave([a, b], 3)] == ["a1", "b1", "a2"]

    def test_a_season_picks_its_sermons_and_any_season_picks_them_all(self):
        tags = {"s1": ["weary"], "s2": [], "s3": ["joyful", "grateful"]}
        items = [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}, {"id": "s4"}]
        assert [i["id"] for i in items if listen.matches(i, tags, "grateful")] == ["s3"]
        assert [i["id"] for i in items if listen.matches(i, tags, None)] == ["s1", "s2", "s3", "s4"]
        assert [i["id"] for i in listen.untagged(items, tags)] == ["s4"]


class TestRoute:
    @pytest.fixture(autouse=True)
    def faked(self, monkeypatch):
        monkeypatch.setattr(auth, "_verify", lambda token: USER)
        churches = [{"id": "c1", "name": "Hope Church"}, {"id": "c2", "name": "Grace Chapel"}]
        monkeypatch.setattr(listen, "_all", lambda user: churches)
        monkeypatch.setattr(listen, "_ensure_channel_id", lambda church, user: church)
        monkeypatch.setattr(listen, "church_sermons", lambda church: [
            {"id": f"{church['id']}-new", "title": "New", "published": "2026-11-01", "church": church["name"], "description": "long"},
            {"id": f"{church['id']}-old", "title": "Old", "published": "2026-01-01", "church": church["name"], "description": "long"},
        ])
        monkeypatch.setattr(listen, "catalog_sermons", lambda source: [{"id": f"{source.key}-1", "title": "Catalog", "church": source.name, "catalog": True}])
        self.tagged = {"c1-new": ["weary"], "c1-old": ["joyful"], "c2-new": ["weary"], "keller-1": ["weary"], "begg-1": ["joyful"]}
        kept = lambda items: {k: v for k, v in self.tagged.items() if k in {i["id"] for i in items}}
        self.asked_model = False

        def tag(items):
            self.asked_model = True
            return kept(items)

        monkeypatch.setattr(listen, "tag_moods", tag)
        monkeypatch.setattr(listen, "known_moods", kept)

    def test_a_season_from_everywhere(self):
        body = client.get("/me/listen?mood=weary", headers=HEADERS).json()
        assert [i["id"] for i in body["mine"]] == ["c1-new", "c2-new"]
        assert [i["id"] for i in body["catalog"]] == ["keller-1"]
        assert "description" not in body["mine"][0]
        assert body["pending"] is True  # most catalog sources aren't sorted yet

    def test_no_season_shows_everything_without_waiting_for_the_model(self, monkeypatch):
        sorted_after = []
        monkeypatch.setattr(listen, "_tag_the_rest", sorted_after.extend)
        body = client.get("/me/listen", headers=HEADERS).json()
        assert [i["id"] for i in body["mine"]] == ["c1-new", "c2-new", "c1-old", "c2-old"]
        assert len(body["catalog"]) == len(listen.CATALOG)
        assert body["pending"] is False and not self.asked_model
        assert "c2-old" in {i["id"] for i in sorted_after}  # still sorted, after the answer

    def test_one_church_only(self):
        body = client.get("/me/listen?source=church:c2", headers=HEADERS).json()
        assert [i["id"] for i in body["mine"]] == ["c2-new", "c2-old"] and body["catalog"] == []

    def test_one_catalog_source_only(self):
        body = client.get("/me/listen?source=catalog:begg", headers=HEADERS).json()
        assert body["mine"] == [] and [i["id"] for i in body["catalog"]] == ["begg-1"] and body["pending"] is False

    def test_an_unknown_season_or_source_is_refused(self):
        assert client.get("/me/listen?mood=bored", headers=HEADERS).status_code == 422
        assert client.get("/me/listen?source=catalog:nobody", headers=HEADERS).status_code == 422

    def test_the_source_filter_lists_churches_and_the_catalog(self):
        body = client.get("/me/listen/sources", headers=HEADERS).json()
        assert [c["name"] for c in body["churches"]] == ["Hope Church", "Grace Chapel"]
        assert len(body["catalog"]) == len(listen.CATALOG)


def test_listen_requires_sign_in():
    assert client.get("/me/listen").status_code == 401
