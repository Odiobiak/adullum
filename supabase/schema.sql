-- Run this once in the Supabase SQL editor (or via `supabase db push`).

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Bible corpus
-- ---------------------------------------------------------------------------
create table if not exists verses (
    id            bigint generated always as identity primary key,
    translation   text not null,              -- e.g. 'KJV', 'WEB', 'BSB'
    book          text not null,               -- e.g. 'John'
    book_order    smallint not null,           -- 1-66, for stable sorting
    testament     text not null check (testament in ('OT', 'NT')),
    genre         text not null,               -- law | history | poetry | prophecy | gospel | epistle | apocalyptic
    chapter       smallint not null,
    verse         smallint not null,
    text          text not null,
    embedding     vector(1536),
    tsv           tsvector generated always as (to_tsvector('english', text)) stored,
    unique (translation, book, chapter, verse)
);

create index if not exists verses_tsv_idx on verses using gin (tsv);
create index if not exists verses_ref_idx on verses (translation, book, chapter, verse);

-- Vector index — build this AFTER the corpus is loaded (needs data to pick good
-- cluster counts). Safe to re-run: drop and recreate once data is in.
create index if not exists verses_embedding_idx on verses
    using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Cosine-similarity search, callable from supabase-py as an RPC.
create or replace function match_verses(
    query_embedding vector(1536),
    match_translation text,
    match_count int default 8
)
returns table (
    id bigint,
    book text,
    chapter smallint,
    verse smallint,
    text text,
    similarity float
)
language sql stable
as $$
    select
        v.id, v.book, v.chapter, v.verse, v.text,
        1 - (v.embedding <=> query_embedding) as similarity
    from verses v
    where v.translation = match_translation
    order by v.embedding <=> query_embedding
    limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- App data (uses Supabase Auth's built-in auth.users — no separate user table)
-- ---------------------------------------------------------------------------
create table if not exists chat_sessions (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid references auth.users(id) on delete cascade,
    title       text,
    created_at  timestamptz not null default now()
);

create table if not exists chat_messages (
    id          bigint generated always as identity primary key,
    session_id  uuid not null references chat_sessions(id) on delete cascade,
    role        text not null check (role in ('user', 'assistant')),
    content     text not null,
    citations   jsonb,                          -- [{book, chapter, verse, translation}, ...]
    created_at  timestamptz not null default now()
);

alter table chat_sessions enable row level security;
alter table chat_messages enable row level security;

create policy "users manage their own sessions" on chat_sessions
    for all using (auth.uid() = user_id);

create policy "users manage messages in their own sessions" on chat_messages
    for all using (
        session_id in (select id from chat_sessions where user_id = auth.uid())
    );
