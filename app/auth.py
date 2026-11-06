"""Sign-in for My Cave, brokered entirely by this server.

The browser never holds a Supabase key of any kind. It sends an email (and a
password, or nothing for a magic link) here, this module asks Supabase Auth on
its behalf, and hands back the resulting access/refresh tokens. Every later
request carries the access token as a Bearer header, which `current_user`
checks with Supabase before any `/me` route touches the database.

Two things to know before changing this file:
- Auth calls run on a throwaway client from `_auth_client()`, never on the
  shared `get_supabase()` one. A supabase-py client that signs someone in
  swaps its own Authorization header to that person's token, which would
  quietly turn the app-wide service-role client into one user's client.
- That throwaway client uses the implicit flow. The library's default, PKCE,
  keeps a code verifier in the client that started the sign-in and needs it
  back to finish, and a throwaway client is gone by the time the magic link
  is clicked. Implicit puts the tokens straight in the redirect's URL
  fragment, where web/cave.js picks them up.
"""

import time
from dataclasses import dataclass
from threading import Lock

from fastapi import Header, HTTPException
from supabase import Client, ClientOptions, create_client
from supabase_auth.errors import AuthError

from app.config import settings

_TOKEN_TTL_SECONDS = 120
_TOKEN_CACHE_MAX = 2000


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None
    # From the sign-up form, kept in Supabase's user metadata until the
    # profile row exists (see app/cave.py::_ensure_profile).
    display_name: str | None = None


def _auth_client() -> Client:
    # ClientOptions(...) is constructed directly: its .replace() helper
    # treats False as "unset" and turns auto_refresh_token back on.
    options = ClientOptions(auto_refresh_token=False, persist_session=False, flow_type="implicit")
    return create_client(settings.supabase_url, settings.supabase_service_key, options=options)


def session_payload(session) -> dict:
    """The token bundle web/cave.js stores. Shared by every sign-in path."""
    user = session.user
    return {
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at or int(time.time()) + (session.expires_in or 3600),
        "user": {"id": user.id, "email": user.email} if user else None,
    }


def auth_error_message(err: AuthError) -> str:
    """Supabase's own messages are already short and human ("Invalid login
    credentials"), so they pass through, with a fallback for the rare blank."""
    return getattr(err, "message", None) or str(err) or "Sign-in failed. Please try again."


def _signup_options(redirect_to: str | None, display_name: str | None) -> dict:
    options: dict = {}
    if redirect_to:
        options["email_redirect_to"] = redirect_to
    if display_name:
        options["data"] = {"display_name": display_name}
    return options


def sign_up(email: str, password: str, redirect_to: str | None, display_name: str | None = None) -> dict | None:
    """Returns a session, or None when the project requires the person to
    confirm their email first (Supabase's default for hosted projects)."""
    options = _signup_options(redirect_to, display_name)
    resp = _auth_client().auth.sign_up({"email": email, "password": password, "options": options})
    return session_payload(resp.session) if resp.session else None


def sign_in_password(email: str, password: str) -> dict:
    resp = _auth_client().auth.sign_in_with_password({"email": email, "password": password})
    return session_payload(resp.session)


def send_magic_link(email: str, redirect_to: str | None, display_name: str | None = None) -> None:
    # The name only lands for a brand-new account; Supabase ignores `data`
    # for someone who already has one.
    options: dict = {"should_create_user": True, **_signup_options(redirect_to, display_name)}
    _auth_client().auth.sign_in_with_otp({"email": email, "options": options})


def verify_email_code(email: str, token: str) -> dict:
    """For the six-digit code, when the email template includes one."""
    resp = _auth_client().auth.verify_otp({"email": email, "token": token, "type": "email"})
    return session_payload(resp.session)


def google_authorize_url(redirect_to: str) -> str:
    """Supabase's hosted Google sign-in. Without a PKCE challenge it answers
    with the implicit flow, so tokens come back in the URL fragment exactly
    like a magic link, and web/cave.js handles both the same way."""
    from urllib.parse import urlencode

    query = urlencode({"provider": "google", "redirect_to": redirect_to})
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/authorize?{query}"


def refresh(refresh_token: str) -> dict:
    resp = _auth_client().auth.refresh_session(refresh_token)
    return session_payload(resp.session)


# ---------------------------------------------------------------------------
# Verifying a request's token
# ---------------------------------------------------------------------------
# Asking Supabase "whose token is this" costs a network round trip, and a
# single chat turn makes several authenticated calls in a row, so verdicts are
# kept briefly. Short enough that a signed-out or deleted user stops working
# within two minutes even though nothing here is told about it.
_token_cache: dict[str, tuple[AuthUser, float]] = {}
_cache_lock = Lock()


def _verify(token: str) -> AuthUser | None:
    now = time.time()
    with _cache_lock:
        hit = _token_cache.get(token)
        if hit and hit[1] > now:
            return hit[0]
    try:
        resp = _auth_client().auth.get_user(token)
    except AuthError:
        return None
    if not resp or not resp.user:
        return None
    meta = resp.user.user_metadata or {}
    user = AuthUser(id=resp.user.id, email=resp.user.email, display_name=meta.get("display_name"))
    with _cache_lock:
        if len(_token_cache) >= _TOKEN_CACHE_MAX:
            _token_cache.clear()
        _token_cache[token] = (user, now + _TOKEN_TTL_SECONDS)
    return user


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def optional_user(authorization: str | None = Header(default=None)) -> AuthUser | None:
    """FastAPI dependency for routes that work signed in or out (chat, plans).
    A bad or expired token is treated as signed out rather than an error, so
    a stale tab keeps working as a guest instead of failing every question."""
    token = _bearer(authorization)
    return _verify(token) if token else None


def require_user(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency for everything under /me."""
    token = _bearer(authorization)
    user = _verify(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Sign in to open your cave.")
    return user


def is_admin(user: AuthUser | None) -> bool:
    """Whether this person can open the admin desk (settings.admin_emails)."""
    if not user or not user.email:
        return False
    admins = {e.strip().lower() for e in settings.admin_emails.split(",") if e.strip()}
    return user.email.lower() in admins


def require_admin(authorization: str | None = Header(default=None)) -> AuthUser:
    """FastAPI dependency for the admin desk. Signed out is a 401, signed in
    without admin rights is a 403, so the client can tell the two apart."""
    user = require_user(authorization)
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Only the people who look after Adullum can open the admin desk.")
    return user
