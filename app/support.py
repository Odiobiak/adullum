"""Support Adullam: giving once, or monthly as a "friend of the cave".

Adullam stays free, with no ads, and nobody's data is sold. Giving pays for
hosting, the database and Aquila's answers. There are two ways to give, both
links to a checkout page that lives somewhere else (Stripe Payment Links, set
in `.env` as SUPPORT_ONCE_URL and SUPPORT_MONTHLY_URL):

- **Give once**: a gift of any size. Nothing changes in the app.
- **Monthly**: the person becomes a friend of the cave. That earns a small
  mark on their account chip and the supporter themes in Settings. Nothing
  anyone relies on (the Bible, Aquila, Refuge, prayers) is ever held back.

This server never sees a card. Who counts as a friend of the cave is
`profiles.supporter_since` (supabase/migrations/20261112_supporters.sql), set
by `scripts/set_supporter.py` for now. People can't set it themselves, because
`cave.ProfilePatch` doesn't accept it. When Stripe is set up, a webhook can
set and clear the same column. The page passes the person's id to the
checkout as `client_reference_id`, so the webhook can tell whose gift it was.
"""

from fastapi import APIRouter

from app.config import settings

router = APIRouter()


def support_links() -> dict:
    """The giving links the page should show, or None for each one not set yet."""
    return {
        "once_url": settings.support_once_url.strip() or None,
        "monthly_url": settings.support_monthly_url.strip() or None,
        "monthly_amount": settings.support_monthly_amount.strip() or None,
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
