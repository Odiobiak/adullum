-- The welcome tour (web/welcome.js): a short walk through the five tabs that
-- opens once over the home screen for a new account. When it was seen (or
-- skipped) is kept on the profile, so it never opens again on another device.
--
-- Everyone who already has a profile has found their way round, so they're
-- counted as welcomed. Run once, after the others, in the Supabase SQL editor.
-- Until it runs, the tour is remembered on each device instead.

alter table profiles add column if not exists welcomed_at timestamptz;

update profiles set welcomed_at = coalesce(created_at, now()) where welcomed_at is null;
