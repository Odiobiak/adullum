"""Mark an account as a friend of the cave (a monthly supporter), or stop.

Until a Stripe webhook does this on its own, run it when someone starts or
stops giving monthly:

    python scripts/set_supporter.py someone@example.com
    python scripts/set_supporter.py someone@example.com --remove

It sets or clears `profiles.supporter_since`, which unlocks the supporter mark
and themes (see app/support.py). Needs supabase/migrations/20261112_supporters.sql
to have run, and the service-role key from .env.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Run from anywhere: make the app package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth import _auth_client  # noqa: E402  (a throwaway client, never the shared one)
from app.db import get_supabase  # noqa: E402

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
    parser = argparse.ArgumentParser(description="Mark an account as a friend of the cave.")
    parser.add_argument("email", help="the account's email address")
    parser.add_argument("--remove", action="store_true", help="they've stopped giving monthly")
    args = parser.parse_args()
    email = args.email.strip()

    user_id = find_user_id(_auth_client(), email)
    if not user_id:
        print(f"No account found for {email}.")
        return 1

    since = None if args.remove else datetime.now(timezone.utc).isoformat()
    # Upsert, so it works even for someone who hasn't opened their cave yet
    # and has no profile row. A display name is filled in on their first visit.
    get_supabase().table("profiles").upsert({"id": user_id, "supporter_since": since}).execute()
    print(f"{email} is no longer marked as a supporter." if args.remove else f"{email} is now a friend of the cave.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
