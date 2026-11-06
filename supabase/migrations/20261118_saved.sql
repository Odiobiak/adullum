-- Saved: one place for everything a person saves with one tap (app/saved.py).
-- A verse (from the reader, the verse of the day, a sermon's week after) or an
-- answer from Aquila. It replaces Memorize in the Bible tab, so the verses
-- anyone was learning are copied in at the end; memory_verses itself is left
-- in place, untouched.
--
-- Run once, after the others, in the Supabase SQL editor.

create table if not exists saved_items (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    kind         text not null check (kind in ('verse', 'answer')),
    -- A verse: where it is, and its words in the translation it was saved
    -- from, read from the verses table by the server.
    book         text,
    chapter      smallint,
    verse_start  smallint,
    verse_end    smallint,
    translation  text,
    verse_text   text,
    -- An answer: the question asked and what Aquila said, with its citations.
    question     text,
    answer       text,
    citations    jsonb not null default '[]'::jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists saved_items_user_idx on saved_items (user_id, created_at desc);
-- Saving the same passage twice keeps the first.
create unique index if not exists saved_items_one_verse
    on saved_items (user_id, book, chapter, verse_start, verse_end) where kind = 'verse';

alter table saved_items enable row level security;
drop policy if exists "users manage their own saved items" on saved_items;
create policy "users manage their own saved items" on saved_items
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Bring over the verses people were learning, so nothing they kept is lost
-- (only where the Memorize migration ran).
do $$
begin
    if to_regclass('public.memory_verses') is not null then
        insert into saved_items (user_id, kind, book, chapter, verse_start, verse_end, translation, verse_text, created_at)
        select user_id, 'verse', book, chapter, verse_start, verse_end, translation, verse_text, created_at
        from memory_verses
        on conflict do nothing;
    end if;
end $$;
