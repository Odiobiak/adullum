"""Mark an account as a friend of the cave (a monthly supporter), or stop.

Until a Stripe webhook does this on its own, run it (or use the Giving tab
on the admin desk) when someone starts or stops giving monthly:

    python scripts/set_supporter.py someone@example.com
    python scripts/set_supporter.py someone@example.com --remove

It sets or clears `profiles.supporter_since`, which unlocks the supporter mark
and themes (see app/support.py). Needs supabase/migrations/20261112_supporters.sql
to have run, and the service-role key from .env.
"""

import argparse
import sys
from pathlib import Path

# Run from anywhere: make the app package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.support import set_supporter  # noqa: E402  (the same lookup the admin desk uses)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mark an account as a friend of the cave.")
    parser.add_argument("email", help="the account's email address")
    parser.add_argument("--remove", action="store_true", help="they've stopped giving monthly")
    args = parser.parse_args()
    email = args.email.strip()
    if not set_supporter(email, not args.remove):
        print(f"No account found for {email}.")
        return 1
    print(f"{email} is no longer marked as a supporter." if args.remove else f"{email} is now a friend of the cave.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
