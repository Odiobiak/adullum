-- Sermon notes: the cave's Sermons tab (app/sermons.py, web/sermons.js).
--
-- Run once in the Supabase SQL editor, after the earlier migrations. Safe to
-- run again.
--
-- One row per sermon. The note itself is an ordered list of blocks (text,
-- point, verse, photo, quote, to-do list, link) kept as JSON, because the
-- blocks are only ever read and written as a whole note and their shapes
-- differ. `passages` is every Bible reference found in the note, worked out
-- by the server on each save, so lists and "also in your cave" can match on
-- it without reading every note's blocks.
--
-- Photos live in the private `sermon-images` storage bucket under
-- <user id>/<note id>/, and a photo block stores only that path. The server
-- hands out short-lived signed links to show them.
--
-- `share_token` is set only while the person shares the note with a
-- read-only link; clearing it turns the link off.

create table if not exists sermon_notes (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    title        text not null default '',
    speaker      text,
    church       text,
    preached_on  date,
    series       text,
    passage_ref  text,                          -- the main passage, e.g. 'Philippians 4:4-9'
    blocks       jsonb not null default '[]'::jsonb,
    passages     text[] not null default '{}',  -- every reference in the note, canonical form
    share_token  text unique,
    shared_at    timestamptz,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists sermon_notes_user_idx on sermon_notes (user_id, preached_on desc nulls last, created_at desc);

-- The server reads and writes with the service role, which bypasses RLS, and
-- filters by user in code (app/sermons.py). These policies are for a future
-- client that talks to Supabase directly. A shared note is read through the
-- server's /shared/sermons route, never through a public policy, so nothing
-- here opens a note to anyone else.
alter table sermon_notes enable row level security;
drop policy if exists "users manage their own sermon notes" on sermon_notes;
create policy "users manage their own sermon notes" on sermon_notes
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Private bucket for photos in sermon notes. 5 MB is a ceiling, not the
-- usual size: the browser shrinks a photo to about 1600 pixels before
-- uploading, which comes to a few hundred KB.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('sermon-images', 'sermon-images', false, 5242880, array['image/jpeg', 'image/png', 'image/webp'])
on conflict (id) do nothing;
