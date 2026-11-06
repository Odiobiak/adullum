-- Declare: kept declarations (app/declare.py).
-- Each line keeps what the person says and the reference it rests on, never
-- the verse's words, which are read from the verses table whenever it's
-- opened. A declaration over a prayer goes with it when the prayer is deleted.
--
-- Run once, after the others, in the Supabase SQL editor. Safe to re-run.

create table if not exists declarations (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    prayer_id   uuid references prayers(id) on delete cascade,
    title       text not null,
    situation   text not null,
    name        text,                                  -- who it's spoken over, when not themselves
    opening     text not null,
    lines       jsonb not null default '[]'::jsonb,    -- [{say, ref}]
    created_at  timestamptz not null default now()
);

create index if not exists declarations_user_idx on declarations (user_id, created_at desc);
create index if not exists declarations_prayer_idx on declarations (prayer_id) where prayer_id is not null;

alter table declarations enable row level security;
drop policy if exists "users manage their own declarations" on declarations;
create policy "users manage their own declarations" on declarations
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
