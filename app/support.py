"""Support Adullam: giving once, or monthly as a "friend of the cave".

Adullam stays free, with no ads, and nobody's data is sold. Giving pays for
hosting, the database and Aquila's answers. Every way to give is a link or a
handle somewhere else, so this server never sees a card or an account:

- **Stripe** Payment Links, set in `.env` as SUPPORT_ONCE_URL and
  SUPPORT_MONTHLY_URL, once Stripe is registered.
- **Ways to give** set from the Giving tab on the admin desk (#desk) and kept
  in `giving_methods` (supabase/migrations/20261124_giving_methods.sql):
  PayPal, Venmo, Cash App, Zelle, or anything else with a link or a handle.
  Everything in that table is public, since the Support page shows it to
  anyone. It never holds a password or a key.

Giving monthly makes someone a friend of the cave: a small mark on their
account chip and the supporter themes in Settings. Nothing anyone relies on
(the Bible, Aquila, Refuge, prayers) is ever held back. Who counts is
`profiles.supporter_since` (supabase/migrations/20261112_supporters.sql). A
Stripe webhook can set it one day (the checkout link carries the person's id
as `client_reference_id`); for any other way to give, an admin marks them
from the Giving tab (`POST /admin/supporters`) or with
`scripts/set_supporter.py`. People can't set it themselves, because
`cave.ProfilePatch` doesn't accept it.
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthUser, _auth_client, require_admin
from app.cave import _db_call, _now
from app.config import settings
from app.db import get_supabase

log = logging.getLogger(__name__)

router = APIRouter()

GIVING_HINT = (
    "Ways to give need a database update. Run supabase/migrations/20261124_giving_methods.sql "
    "in the Supabase SQL editor."
)
MAX_METHODS = 12
USERS_PAGE = 200

Kind = Literal["paypal", "venmo", "cashapp", "zelle", "other"]

# The name each kind goes by, and how its handle becomes a link. Zelle has
# no link: people send from their own bank's app to an email or phone.
KIND_NAMES = {"paypal": "PayPal", "venmo": "Venmo", "cashapp": "Cash App", "zelle": "Zelle", "other": "Other"}
HANDLE_LINKS = {
    "paypal": "https://www.paypal.com/paypalme/{}",
    "venmo": "https://venmo.com/u/{}",
    "cashapp": "https://cash.app/${}",
}
_USERNAME = re.compile(r"^[A-Za-z0-9][\w.-]{0,39}$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE = re.compile(r"^\+?[\d ()-]{7,20}$")
_FIELDS = "id, kind, label, handle, url, note, monthly, enabled, position"


def _db(fn):
    return _db_call(fn, GIVING_HINT)


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------
def clean_handle(kind: str, handle: str | None) -> str | None:
    """A handle as it should be stored, or a ValueError a person can act on.
    PayPal, Venmo and Cash App keep the bare username (no @, $ or link);
    Zelle keeps an email or phone number; anything else is kept as typed."""
    value = " ".join((handle or "").split())
    if not value:
        return None
    if kind in HANDLE_LINKS:
        value = re.sub(r"^https?://\S+/", "", value).lstrip("@$").strip("/")
        if not _USERNAME.match(value):
            raise ValueError(f"That doesn't look like a {KIND_NAMES[kind]} username.")
    elif kind == "zelle" and not (_EMAIL.match(value) or _PHONE.match(value)):
        raise ValueError("Zelle needs the email or phone number gifts are sent to.")
    return value


def clean_url(url: str | None) -> str | None:
    value = (url or "").strip()
    if not value:
        return None
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = f"https://{value}"
    if not re.match(r"^https?://[^\s/]+\.[^\s/]+(/\S*)?$", value, re.IGNORECASE):
        raise ValueError("That link doesn't look right. It should start with https://")
    return value


class MethodIn(BaseModel):
    kind: Kind
    label: str | None = Field(default=None, max_length=40)
    handle: str | None = Field(default=None, max_length=80)
    url: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=200)
    monthly: bool = False
    enabled: bool = True


def cleaned(body: MethodIn) -> dict:
    """A method ready to store, or a 422 whose one sentence says what to fix
    (a pydantic error would reach the page as a list it can't show)."""
    try:
        row = {
            **body.model_dump(),
            "label": " ".join((body.label or "").split()) or None,
            "note": " ".join((body.note or "").split()) or None,
            "handle": clean_handle(body.kind, body.handle),
            "url": clean_url(body.url),
        }
        if body.kind == "other" and not row["label"]:
            raise ValueError("Give it a name, like Bank transfer.")
        if body.kind == "zelle" and not row["handle"]:
            raise ValueError("Zelle needs the email or phone number gifts are sent to.")
        if not (row["handle"] or row["url"]):
            raise ValueError("Add a link or a username, so people know where to give.")
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return row


class OrderIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=MAX_METHODS)


class SupporterIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    supporter: bool = True


# ---------------------------------------------------------------------------
# What the Support page shows
# ---------------------------------------------------------------------------
def give_link(method: dict) -> str | None:
    """Where the Give button goes: the link set for it, else one made from
    the handle (paypal.me, venmo.com/u, cash.app). None for Zelle and any
    method with only a handle, which the page shows to copy instead."""
    if method.get("url"):
        return method["url"]
    pattern = HANDLE_LINKS.get(method.get("kind"))
    return pattern.format(method["handle"]) if pattern and method.get("handle") else None


def public_method(method: dict) -> dict:
    """A method as anyone may see it."""
    kind = method["kind"]
    handle = method.get("handle")
    shown = f"${handle}" if kind == "cashapp" and handle else f"@{handle}" if kind == "venmo" and handle else handle
    return {
        "id": method["id"],
        "kind": kind,
        "name": method.get("label") or KIND_NAMES[kind],
        "handle": shown,
        "link": give_link(method),
        "note": method.get("note"),
        "monthly": bool(method.get("monthly")),
    }


def _methods(enabled_only: bool) -> list[dict]:
    query = get_supabase().table("giving_methods").select(_FIELDS)
    if enabled_only:
        query = query.eq("enabled", True)
    return _db(lambda: query.order("position").order("created_at").limit(MAX_METHODS).execute().data)


def support_links() -> dict:
    """Everything the Support page shows: Stripe's links (None until set)
    and the ways to give switched on at the desk ([] before its migration)."""
    try:
        methods = [public_method(m) for m in _methods(enabled_only=True)]
    except Exception:
        log.info("couldn't read giving_methods", exc_info=True)
        methods = []
    return {
        "once_url": settings.support_once_url.strip() or None,
        "monthly_url": settings.support_monthly_url.strip() or None,
        "monthly_amount": settings.support_monthly_amount.strip() or None,
        "methods": methods,
    }


def is_supporter(profile: dict | None) -> bool:
    """Whether a profile row belongs to a friend of the cave.

    False before the supporters migration has run, since the column isn't
    there yet, so nothing breaks in the meantime.
    """
    return bool(profile and profile.get("supporter_since"))


@router.get("/support")
def support() -> dict:
    """Public: the Support page is open to guests too."""
    return support_links()


# ---------------------------------------------------------------------------
# The Giving tab on the admin desk
# ---------------------------------------------------------------------------
def _admin_row(method: dict) -> dict:
    return {**method, "link": give_link(method)}


@router.get("/admin/giving")
def list_methods(admin: AuthUser = Depends(require_admin)) -> dict:
    return {
        "methods": [_admin_row(m) for m in _methods(enabled_only=False)],
        "stripe": {"once": bool(settings.support_once_url.strip()), "monthly": bool(settings.support_monthly_url.strip())},
    }


@router.post("/admin/giving")
def add_method(body: MethodIn, admin: AuthUser = Depends(require_admin)) -> dict:
    existing = _methods(enabled_only=False)
    if len(existing) >= MAX_METHODS:
        raise HTTPException(status_code=422, detail=f"There can be up to {MAX_METHODS} ways to give.")
    row = {**cleaned(body), "position": max((m["position"] for m in existing), default=-1) + 1}
    return _admin_row(_db(lambda: get_supabase().table("giving_methods").insert(row).execute().data[0]))


@router.put("/admin/giving/{method_id}")
def update_method(method_id: uuid.UUID, body: MethodIn, admin: AuthUser = Depends(require_admin)) -> dict:
    rows = _db(lambda: get_supabase().table("giving_methods").update({**cleaned(body), "updated_at": _now()}).eq("id", str(method_id)).execute().data)
    if not rows:
        raise HTTPException(status_code=404, detail="That way to give isn't here anymore.")
    return _admin_row(rows[0])


@router.delete("/admin/giving/{method_id}")
def remove_method(method_id: uuid.UUID, admin: AuthUser = Depends(require_admin)) -> dict:
    _db(lambda: get_supabase().table("giving_methods").delete().eq("id", str(method_id)).execute())
    return {"status": "deleted"}


@router.post("/admin/giving/order")
def reorder(body: OrderIn, admin: AuthUser = Depends(require_admin)) -> dict:
    """The order the Support page lists them in, as the desk arranged them."""
    for position, method_id in enumerate(body.ids):
        _db(lambda: get_supabase().table("giving_methods").update({"position": position}).eq("id", str(method_id)).execute())
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Friends of the cave, marked by hand for gifts that don't come through Stripe
# ---------------------------------------------------------------------------
def find_user_id(email: str) -> str | None:
    """The account with this email (case-insensitive), paging through users
    on a throwaway auth client (app/auth.py::_auth_client)."""
    client, page = _auth_client(), 1
    while True:
        users = client.auth.admin.list_users(page=page, per_page=USERS_PAGE)
        for user in users:
            if (user.email or "").lower() == email.lower():
                return user.id
        if len(users) < USERS_PAGE:
            return None
        page += 1


def set_supporter(email: str, supporter: bool) -> bool:
    """Marks or unmarks an account as a friend of the cave. False when no
    account has that email. An upsert, so it works for someone who hasn't
    opened their cave yet and has no profile row."""
    user_id = find_user_id(email.strip())
    if not user_id:
        return False
    since = datetime.now(timezone.utc).isoformat() if supporter else None
    get_supabase().table("profiles").upsert({"id": user_id, "supporter_since": since}).execute()
    return True


@router.post("/admin/supporters")
def mark_supporter(body: SupporterIn, admin: AuthUser = Depends(require_admin)) -> dict:
    if not set_supporter(body.email, body.supporter):
        raise HTTPException(status_code=404, detail="No account uses that email.")
    return {"status": "ok"}
