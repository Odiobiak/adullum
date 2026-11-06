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
    -- Only the search translation (BSB, app/config.py::search_translation)
    -- carries an embedding; every other translation's rows leave this null and
    -- borrow BSB's through match_verses below. 512 dimensions at half
    -- precision is about 1 KB a verse. See
    -- supabase/migrations/20261108_compact_embeddings.sql for why.
    embedding     halfvec(512),
    tsv           tsvector generated always as (to_tsvector('english', text)) stored,
    unique (translation, book, chapter, verse)
);

-- Reference lookups use the index behind the unique constraint above.
create index if not exists verses_tsv_idx on verses using gin (tsv);

-- HNSW keeps itself current as rows arrive, so it can be created before the
-- corpus is loaded. Rows without an embedding aren't indexed.
create index if not exists verses_embedding_idx on verses
    using hnsw (embedding halfvec_cosine_ops);

-- Cosine-similarity search, callable from supabase-py as an RPC. Searches the
-- verses that carry an embedding and returns the same verses from
-- `match_translation`, so every translation gets semantic search.
create or replace function match_verses(
    query_embedding halfvec(512),
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
-- The index returns at most ef_search rows, and the knowledge graph asks for
-- up to 24 neighbours, doubled below. 40 (the default) would cut that short.
set hnsw.ef_search = 100
as $$
    -- A verse the requested translation doesn't have (some modern
    -- translations omit a few verses KJV keeps) drops out of the join, so
    -- over-fetch to cover it.
    with nearest as (
        select e.book, e.chapter, e.verse, e.embedding <=> query_embedding as distance
        from verses e
        where e.embedding is not null
        order by e.embedding <=> query_embedding
        limit match_count * 2
    )
    select v.id, v.book, v.chapter, v.verse, v.text, 1 - n.distance as similarity
    from nearest n
    join verses v
      on v.translation = match_translation
     and v.book = n.book and v.chapter = n.chapter and v.verse = n.verse
    order by n.distance
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

-- Reading plans (Cognigy xApp year-plan builder, see docs/cognigy-xapp-features.md).
-- No user_id/RLS yet, same as the verses table: nothing ties a plan to an
-- identity until Aquila has one (see the doc's Identity and SSO entry), so
-- every plan is only reachable by its own id, generated server-side and
-- never listed. Add user_id + RLS once a stable identity exists.
create table if not exists reading_plans (
    id            uuid primary key default gen_random_uuid(),
    start_date    date not null,
    days          smallint not null,
    translation   text not null,
    overview      text not null,
    schedule      jsonb not null,              -- [{day, date, references: [...]}, ...]
    created_at    timestamptz not null default now()
);

-- My Cave (profiles, journal, memory, reading_plans.user_id) lives in
-- supabase/migrations/20261104_my_cave.sql. Run it after this file.
