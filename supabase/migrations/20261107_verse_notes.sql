-- Notes on verses, written while reading the Bible (app/notes.py).
-- Paste into the Supabase SQL editor once, after 20261104_my_cave.sql.
-- Safe to re-run: every statement is guarded.
--
-- A note is pinned to book/chapter/verse rather than to one translation, so
-- it shows beside the same verse whichever translation is being read.
-- `translation` and `verse_text` record what the person was looking at when
-- they wrote it.

create table if not exists verse_notes (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    book         text not null,
    chapter      smallint not null,
    verse_start  smallint not null,
    verse_end    smallint not null,
    translation  text not null default '',
    verse_text   text,
    body         text not null,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    check (verse_end >= verse_start)
);

-- The reader asks for one chapter's notes; the cave lists them newest first.
create index if not exists verse_notes_chapter_idx on verse_notes (user_id, book, chapter);
create index if not exists verse_notes_recent_idx on verse_notes (user_id, updated_at desc);

alter table verse_notes enable row level security;
drop policy if exists "users manage their own notes" on verse_notes;
create policy "users manage their own notes" on verse_notes
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
