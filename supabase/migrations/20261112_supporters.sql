-- Friends of the cave: people who give monthly (app/support.py).
--
-- Run once in the Supabase SQL editor, after the other migrations. Until it
-- runs, nobody counts as a supporter and the Support page still works.
--
-- When the person became a supporter, or null if they aren't one. Set and
-- cleared by scripts/set_supporter.py (later, by a Stripe webhook). The app's
-- profile update (PATCH /me) never accepts it, so nobody can mark themselves.
alter table profiles add column if not exists supporter_since timestamptz;
