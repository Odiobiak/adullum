"""Support Adullam: the public giving links, and who counts as a friend of
the cave. No network call; settings are patched per test."""

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

    def set_links(once="", monthly="", amount="$3"):
        monkeypatch.setattr(settings, "support_once_url", once)
        monkeypatch.setattr(settings, "support_monthly_url", monthly)
        monkeypatch.setattr(settings, "support_monthly_amount", amount)

    return set_links


def test_support_is_public_and_returns_the_links(links):
    links(once="https://buy.stripe.com/once", monthly="https://buy.stripe.com/monthly", amount="$5")
    res = client.get("/support")
    assert res.status_code == 200
    assert res.json() == {
        "once_url": "https://buy.stripe.com/once",
        "monthly_url": "https://buy.stripe.com/monthly",
        "monthly_amount": "$5",
    }


def test_links_not_set_yet_come_back_as_none(links):
    links(once="  ", monthly="", amount="")
    assert support.support_links() == {"once_url": None, "monthly_url": None, "monthly_amount": None}


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
