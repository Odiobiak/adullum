"""Error reports to Sentry, from the server only, once SENTRY_DSN is set.

People write very personal things here, so a report carries the error, its
stack trace and the route it happened on, and nothing a person sent: no
request body, headers, cookies, query string or address (a shared sermon's
link holds its token), no local variables, no breadcrumbs, and a log line's
template without the values filled into it, since those can quote what
someone wrote. The Privacy page promises exactly this; keep the two in step.
There is no browser script, since one would run beside the sign-in tokens.
"""

from app.config import settings

# What a report may keep of the request. The route template ("/me/prayers/{id}")
# comes through separately as the event's transaction.
_REQUEST_KEPT = ("method",)
# Parts of an event that can carry what a person sent or who they are.
_DROPPED = ("user", "breadcrumbs", "extra")


def scrub(event: dict, _hint: dict | None = None) -> dict:
    """Strips an event down to the error and where it happened (Sentry's before_send)."""
    if "request" in event:
        event["request"] = {k: v for k, v in event["request"].items() if k in _REQUEST_KEPT}
    for key in _DROPPED:
        event.pop(key, None)
    if "logentry" in event:
        event["logentry"] = {k: v for k, v in event["logentry"].items() if k == "message"}
    return event


def init() -> None:
    """Turns error reports on when a DSN is set. Call before the FastAPI app is
    made, so Sentry's FastAPI integration can wrap it."""
    if not settings.sentry_dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        max_breadcrumbs=0,
        before_send=scrub,
    )
