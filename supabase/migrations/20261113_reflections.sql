-- Reflections: a guided time with God over a month, a quarter, a year or a
-- season of the person's own choosing (app/reflections.py, web/reflections.js).
--
-- Paste into the Supabase SQL editor once, after the other migrations. Safe to
-- re-run: every statement is guarded. Until it runs, the Journal tab works as
-- before and "Reflection" under New entry says what to run.
--
-- A reflection can have a name the person gives it ("A year of new
-- beginnings"); without one it's called by its dates.
--
-- A reflection looks back over one stretch of time (starts_on to ends_on) and
-- ahead to the next (ahead_starts_on to ahead_ends_on). It has three parts,
-- each kept as JSON in the shape the pydantic models in app/reflections.py
-- describe, so the page can add a question without a migration:
--   look_back    numbers the person chose to count, goals, areas of life with
--                how each went, and their answers
--   lay_down     gratitude, what to set down, forgiveness
--   look_ahead   a word, a verse (a reference only; its text is always read
--                from the verses table), numbers to aim for, and for each area
--                where they'd like it to be and the goals they hope to see.
--                A goal tracked in Pebbles keeps its refuge_seeds id.
-- It is a draft while it's being written and kept once the person keeps it.
-- Kept, its look_ahead is the plan for the stretch ahead, and the next
-- reflection opens by setting that plan beside what happened.
--
-- Private to the person. None of it feeds Aquila's memory.

create table if not exists reflections (
    id               uuid primary key default gen_random_uuid(),
    user_id          uuid not null references auth.users(id) on delete cascade,
    title            text,                      -- the person's own name for it, optional
    span             text not null check (span in ('month', 'quarter', 'year', 'season')),
    starts_on        date not null,
    ends_on          date not null,
    ahead_starts_on  date not null,
    ahead_ends_on    date not null,
    status           text not null default 'draft' check (status in ('draft', 'kept')),
    look_back        jsonb not null default '{}'::jsonb,
    lay_down         jsonb not null default '{}'::jsonb,
    look_ahead       jsonb not null default '{}'::jsonb,
    kept_at          timestamptz,
    created_at       timestamptz not null default now(),
    updated_at       timestamptz not null default now(),
    check (ends_on >= starts_on),
    check (ahead_ends_on >= ahead_starts_on)
);
-- For a database that ran this file before reflections had names.
alter table reflections add column if not exists title text;

create index if not exists reflections_user_idx on reflections (user_id, ahead_ends_on desc);

-- The server reads and writes with the service role, which bypasses RLS, and
-- filters by user in code. This policy is for a future client that talks to
-- Supabase directly.
alter table reflections enable row level security;
drop policy if exists "users manage their own reflections" on reflections;
create policy "users manage their own reflections" on reflections
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
