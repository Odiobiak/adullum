"""The web client is sent so browsers check it's current on every load, and
a deploy reaches everyone at once."""

from fastapi.testclient import TestClient

import app.main as main

client = TestClient(main.app)


def test_the_web_client_is_always_checked_for_a_newer_copy():
    for path in ("/", "/app.css", "/refuge.js"):
        res = client.get(path)
        assert res.status_code == 200 and res.headers["cache-control"] == "no-cache"


def test_an_unchanged_file_costs_only_a_304():
    first = client.get("/support.js")
    again = client.get("/support.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
