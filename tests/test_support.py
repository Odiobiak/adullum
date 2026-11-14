"""Support Adullam: the public giving links, the ways to give set at the
admin desk, and who counts as a friend of the cave. No network call or
database: settings and the giving_methods read are patched per test."""

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import support
from app.cave import ProfilePatch
from app.config import settings

client = TestClient(main.app)


@pytest.fixture
def links(monkeypatch):
    """Set the three giving settings for one test."""

    def set_links(once="", monthly="", amount="$3", methods=()):
        monkeypatch.setattr(settings, "support_once_url", once)
        monkeypatch.setattr(settings, "support_monthly_url", monthly)
        monkeypatch.setattr(settings, "support_monthly_amount", amount)
        monkeypatch.setattr(support, "_methods", lambda enabled_only: list(methods))

    return set_links


def test_support_is_public_and_returns_the_links(links):
    links(once="https://buy.stripe.com/once", monthly="https://buy.stripe.com/monthly", amount="$5")
    res = client.get("/support")
    assert res.status_code == 200
    assert res.json() == {
        "once_url": "https://buy.stripe.com/once",
        "monthly_url": "https://buy.stripe.com/monthly",
        "monthly_amount": "$5",
        "methods": [],
    }


def test_links_not_set_yet_come_back_as_none(links):
    links(once="  ", monthly="", amount="")
    assert support.support_links() == {"once_url": None, "monthly_url": None, "monthly_amount": None, "methods": []}


@pytest.mark.parametrize(
    "profile, expected",
    [
        ({"supporter_since": "2026-11-06T10:00:00+00:00"}, True),
        ({"supporter_since": None}, False),
        ({}, False),  # before the supporters migration, the column isn't there
        (None, False),
    ],
)
def test_is_supporter(profile, expected):
    assert support.is_supporter(profile) is expected


def test_nobody_can_mark_themselves_a_supporter():
    """PATCH /me's body drops supporter_since, so only the server can set it."""
    patch = ProfilePatch(**{"display_name": "Ruth", "supporter_since": "2026-11-06"})
    assert patch.model_dump(exclude_none=True) == {"display_name": "Ruth"}


# ---------------------------------------------------------------------------
# Ways to give, set at the admin desk
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind, typed, kept", [
    ("paypal", "https://paypal.me/adullam", "adullam"),
    ("venmo", "@Adullam-Give", "Adullam-Give"),
    ("cashapp", "$adullam", "adullam"),
    ("cashapp", "https://cash.app/$adullam", "adullam"),
    ("zelle", "give@adullam.app", "give@adullam.app"),
    ("zelle", "+1 (555) 010-2000", "+1 (555) 010-2000"),
    ("other", "Sort code 00-00-00,  account 12345678", "Sort code 00-00-00, account 12345678"),
    ("paypal", "   ", None),
])
def test_handles_are_kept_bare(kind, typed, kept):
    assert support.clean_handle(kind, typed) == kept


@pytest.mark.parametrize("kind, typed", [("venmo", "two words"), ("zelle", "not an address"), ("paypal", "@")])
def test_a_handle_that_cant_be_right_says_so(kind, typed):
    with pytest.raises(ValueError):
        support.clean_handle(kind, typed)


def test_give_links_come_from_the_link_or_the_handle():
    assert support.give_link({"kind": "paypal", "handle": "adullam"}) == "https://www.paypal.com/paypalme/adullam"
    assert support.give_link({"kind": "venmo", "handle": "adullam"}) == "https://venmo.com/u/adullam"
    assert support.give_link({"kind": "cashapp", "handle": "adullam"}) == "https://cash.app/$adullam"
    assert support.give_link({"kind": "paypal", "handle": "adullam", "url": "https://www.paypal.com/donate/?hosted_button_id=X"}).endswith("=X")
    assert support.give_link({"kind": "zelle", "handle": "give@adullam.app"}) is None  # sent from a bank's app, so copied


def test_the_page_gets_only_what_anyone_may_see(links):
    row = {"id": "1", "kind": "venmo", "label": None, "handle": "adullam", "url": None, "note": "Put Adullam in the note",
           "monthly": False, "enabled": True, "position": 0}
    links(methods=[row])
    (method,) = client.get("/support").json()["methods"]
    assert method == {"id": "1", "kind": "venmo", "name": "Venmo", "handle": "@adullam", "link": "https://venmo.com/u/adullam",
                      "note": "Put Adullam in the note", "monthly": False}


def test_the_page_still_opens_before_the_migration(monkeypatch):
    def missing(enabled_only):
        raise RuntimeError("relation giving_methods does not exist")
    monkeypatch.setattr(support, "_methods", missing)
    assert support.support_links()["methods"] == []


@pytest.mark.parametrize("body, message", [
    ({"kind": "other", "url": "https://give.example.org"}, "Give it a name"),
    ({"kind": "zelle"}, "email or phone"),
    ({"kind": "paypal"}, "Add a link or a username"),
    ({"kind": "paypal", "url": "javascript:alert(1)"}, "link doesn't look right"),
])
def test_a_way_to_give_missing_something_gets_one_plain_sentence(body, message):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as caught:
        support.cleaned(support.MethodIn(**body))
    assert caught.value.status_code == 422 and message in caught.value.detail


def test_only_admins_can_change_the_ways_to_give():
    assert client.get("/admin/giving").status_code == 401
    assert client.post("/admin/giving", json={"kind": "paypal", "handle": "adullam"}).status_code == 401
    assert client.post("/admin/supporters", json={"email": "a@b.co"}).status_code == 401
