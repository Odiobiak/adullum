"""Set (or reset) the password on an Adullum account, from the terminal.

For when someone can't get a sign-in email, or signed up with a magic link
and never had a password. It asks for the new password without echoing it,
so the password never lands in shell history, a file, or a log:

    python scripts/set_password.py someone@example.com

Uses the service-role key from .env through Supabase's admin API, so only
someone who already holds that key can run it. It also marks the email as
confirmed, since an unconfirmed account can't sign in with a password.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Run from anywhere: make the app package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import _auth_client  # noqa: E402  (a throwaway client, never the shared one)

MIN_LENGTH = 6  # Supabase's default minimum, the same rule the sign-in form shows
PAGE_SIZE = 200


def find_user_id(client, email: str) -> str | None:
    """Page through the project's users for this email (case-insensitive)."""
    page = 1
    while True:
        users = client.auth.admin.list_users(page=page, per_page=PAGE_SIZE)
        for user in users:
            if (user.email or "").lower() == email.lower():
                return user.id
        if len(users) < PAGE_SIZE:
            return None
        page += 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Set the password on an Adullum account.")
    parser.add_argument("email", help="the account's email address")
    email = parser.parse_args().email.strip()

    client = _auth_client()
    user_id = find_user_id(client, email)
    if not user_id:
        print(f"No account found for {email}. Create one on the sign-in page first.")
        return 1

    password = getpass.getpass("New password: ")
    if len(password) < MIN_LENGTH:
        print(f"Passwords need at least {MIN_LENGTH} characters. Nothing was changed.")
        return 1
    if getpass.getpass("Type it again: ") != password:
        print("Those didn't match. Nothing was changed.")
        return 1

    client.auth.admin.update_user_by_id(user_id, {"password": password, "email_confirm": True})
    print(f"Done. Sign in as {email} with the Password tab.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
