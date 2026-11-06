"""Sending web push notifications (used by app/reminders.py).

A browser that agrees to notifications gives us a push endpoint and two
keys (stored in `push_subscriptions` by web/notify.js). To notify a person,
each of their devices is sent a small, encrypted JSON message, signed with
this server's VAPID key, and web/sw.js on that device shows it.

A push service that answers 404 or 410 is saying the device has gone (the
person turned notifications off, or the browser dropped it), so that row is
deleted. Anything else that fails is logged and left for next time.
"""

from __future__ import annotations

import json
import logging

from app.config import settings
from app.db import get_supabase

log = logging.getLogger(__name__)

# How long a push service keeps trying a device that's offline. Past that, a
# reminder would be stale anyway.
TTL_SECONDS = 6 * 60 * 60


def configured() -> bool:
    return bool(settings.vapid_public_key and settings.vapid_private_key)


def send(subscription: dict, payload: dict) -> bool:
    """Send one message to one device. False means the device is gone."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": subscription["endpoint"], "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]}},
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims={"sub": settings.vapid_subject},
            ttl=TTL_SECONDS,
            timeout=10,
        )
        return True
    except WebPushException as err:
        status = getattr(err.response, "status_code", None)
        if status in (404, 410):
            return False
        log.warning("push to a device failed (%s)", status, exc_info=True)
        return True


def notify_user(user_id: str, payload: dict) -> int:
    """Send `payload` to every device the person has, pruning gone ones.
    Returns how many devices it reached."""
    if not configured():
        return 0
    db = get_supabase()
    devices = db.table("push_subscriptions").select("endpoint, p256dh, auth").eq("user_id", user_id).execute().data
    reached = 0
    for device in devices:
        if send(device, payload):
            reached += 1
        else:
            db.table("push_subscriptions").delete().eq("endpoint", device["endpoint"]).execute()
    return reached
