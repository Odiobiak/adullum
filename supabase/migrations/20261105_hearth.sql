-- The hearth: embers (one per day someone comes in) and reading plan progress.
-- Paste into the Supabase SQL editor once, after 20261104_my_cave.sql.
-- Safe to re-run: every statement is guarded.

-- One row per person per local day they opened the app. The streak and the
-- week of embers on the home screen are both read from this.
create table if not exists user_activity (
    user_id  uuid not null references auth.users(id) on delete cascade,
    day      date not null,
    primary key (user_id, day)
);
alter table user_activity enable row level security;
drop policy if exists "users manage their own activity" on user_activity;
create policy "users manage their own activity" on user_activity
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Which days of a plan have been marked as read (1-based day numbers).
alter table reading_plans add column if not exists completed_days smallint[] not null default '{}';
