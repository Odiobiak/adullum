-- Reading plans shaped with Aquila ("the Gospels in 30 days") keep their own title.
-- Paste into the Supabase SQL editor once, after 20261105_hearth.sql.
-- Safe to re-run. Whole-Bible plans leave it empty and get a title from their shape
-- (see app/plan.py::plan_title).
alter table reading_plans add column if not exists title text;
