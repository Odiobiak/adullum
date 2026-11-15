"""Error reports carry the error and where it happened, never what a person sent."""

from app import monitoring


def test_a_report_keeps_the_error_and_drops_what_the_person_sent():
    event = {
        "exception": {"values": [{"type": "KeyError", "value": "'kind'"}]},
        "transaction": "/me/prayers/{prayer_id}",
        "request": {
            "method": "POST",
            "url": "https://www.adullamapp.com/shared/sermons/secret-token",
            "query_string": "key=mcp-secret",
            "data": {"text": "Please pray for my marriage"},
            "headers": {"Authorization": "Bearer token"},
            "cookies": {"session": "x"},
            "env": {"REMOTE_ADDR": "203.0.113.9"},
        },
        "user": {"ip_address": "203.0.113.9"},
        "breadcrumbs": {"values": [{"message": "Please pray for my marriage"}]},
        "extra": {"body": "Please pray for my marriage"},
        "logentry": {"message": "couldn't save %s", "params": ["Please pray"], "formatted": "couldn't save Please pray"},
    }
    kept = monitoring.scrub(event)
    assert kept["request"] == {"method": "POST"}
    assert kept["logentry"] == {"message": "couldn't save %s"}
    assert kept["exception"] == event["exception"] and kept["transaction"] == "/me/prayers/{prayer_id}"
    assert not {"user", "breadcrumbs", "extra"} & kept.keys()
    assert "Please pray" not in repr(kept)


def test_nothing_starts_without_a_dsn(monkeypatch):
    monkeypatch.setattr(monitoring.settings, "sentry_dsn", None)
    monitoring.init()  # returns before importing sentry_sdk at all
