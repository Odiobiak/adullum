-- Prayers, highlights and verses to memorize (app/prayers.py,
-- app/highlights.py, app/memorize.py).
-- Paste into the Supabase SQL editor once, after the earlier migrations.
-- Safe to re-run: every statement is guarded.
--
-- All three are small per person (tens to hundreds of rows), and none of them
-- stores an embedding of its own.

-- ---------------------------------------------------------------------------
-- Prayer list: requests, and when and how they were answered
-- ---------------------------------------------------------------------------
create table if not exists prayers (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    body         text not null,
    passage_ref  text,                          -- e.g. 'Philippians 4:6-7'
    status       text not null default 'open' check (status in ('open', 'answered')),
    answer_note  text,                          -- how it was answered, in their words
    answered_at  timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists prayers_user_idx on prayers (user_id, status, created_at desc);
alter table prayers enable row level security;
drop policy if exists "users manage their own prayers" on prayers;
create policy "users manage their own prayers" on prayers
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Aquila keeps a short note about each prayer (when memory is on), so she can
-- bring an open request up when it is relevant. The note goes with the prayer.
alter table user_memories add column if not exists prayer_id uuid references prayers(id) on delete cascade;
alter table user_memories drop constraint if exists user_memories_kind_check;
alter table user_memories add constraint user_memories_kind_check check (kind in ('note', 'journal', 'prayer'));

-- ---------------------------------------------------------------------------
-- Highlights: one colour per verse, pinned to book/chapter/verse like notes,
-- so a highlight shows in whichever translation is open. `translation` and
-- `verse_text` record what was on screen when it was made.
-- ---------------------------------------------------------------------------
create table if not exists verse_highlights (
    user_id      uuid not null references auth.users(id) on delete cascade,
    book         text not null,
    chapter      smallint not null,
    verse        smallint not null,
    color        text not null check (color in ('gold', 'green', 'blue', 'rose')),
    translation  text not null default '',
    verse_text   text,
    created_at   timestamptz not null default now(),
    primary key (user_id, book, chapter, verse)
);
alter table verse_highlights enable row level security;
drop policy if exists "users manage their own highlights" on verse_highlights;
create policy "users manage their own highlights" on verse_highlights
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Verses to memorize, with their spaced-repetition schedule
-- (app/memorize.py::next_review decides the next `due` date).
-- ---------------------------------------------------------------------------
create table if not exists memory_verses (
    id             uuid primary key default gen_random_uuid(),
    user_id        uuid not null references auth.users(id) on delete cascade,
    book           text not null,
    chapter        smallint not null,
    verse_start    smallint not null,
    verse_end      smallint not null,
    translation    text not null,
    verse_text     text not null,               -- the words being learned, from the verses table
    reps           smallint not null default 0, -- reviews in a row recalled
    interval_days  smallint not null default 0,
    ease           real not null default 2.5,
    due            date not null default current_date,
    last_reviewed  date,
    created_at     timestamptz not null default now(),
    check (verse_end >= verse_start),
    unique (user_id, book, chapter, verse_start, verse_end)
);
create index if not exists memory_verses_due_idx on memory_verses (user_id, due);
alter table memory_verses enable row level security;
drop policy if exists "users manage their own memory verses" on memory_verses;
create policy "users manage their own memory verses" on memory_verses
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
