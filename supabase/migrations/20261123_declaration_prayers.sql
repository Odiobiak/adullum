-- Declare: the prayer prayed after a declaration's lines (app/declare.py).
-- It's Aquila's words, or the person's own once they've made it theirs, and
-- it never names a reference. Until this runs, declarations are kept and
-- opened without their prayer.
--
-- Run once, after the others, in the Supabase SQL editor. Safe to re-run.

alter table declarations add column if not exists prayer text;
