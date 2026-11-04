-- My Cave: accounts, journal, and Aquila's memory of each person.
-- Paste into the Supabase SQL editor once. Safe to re-run: every statement
-- is guarded, so running it twice changes nothing.
--
-- The FastAPI server talks to these tables with the service-role key and
-- filters every query by the signed-in user's id itself (see app/cave.py).
-- RLS is still switched on with per-user policies so that a future client
-- talking to Supabase directly with the anon key (a mobile app) can only ever
-- see its own rows.

-- ---------------------------------------------------------------------------
-- Profiles: one row per auth.users row, created lazily on first sign-in
-- ---------------------------------------------------------------------------
create table if not exists profiles (
    id                     uuid primary key references auth.users(id) on delete cascade,
    display_name           text,
    preferred_translation  text,
    memory_enabled         boolean not null default true,
    created_at             timestamptz not null default now(),
    updated_at             timestamptz not null default now()
);
alter table profiles enable row level security;
drop policy if exists "users manage their own profile" on profiles;
create policy "users manage their own profile" on profiles
    for all using (auth.uid() = id) with check (auth.uid() = id);

-- ---------------------------------------------------------------------------
-- Conversations: chat_sessions/chat_messages already exist in schema.sql,
-- this adds what the history list needs.
-- ---------------------------------------------------------------------------
alter table chat_sessions add column if not exists updated_at timestamptz not null default now();
alter table chat_messages add column if not exists followups jsonb;
create index if not exists chat_sessions_user_idx on chat_sessions (user_id, updated_at desc);
create index if not exists chat_messages_session_idx on chat_messages (session_id, id);

-- ---------------------------------------------------------------------------
-- Reading plans: optionally owned. Anonymous plans stay reachable by id only.
-- Created here too (same shape as schema.sql) for databases set up before
-- the table was added there.
-- ---------------------------------------------------------------------------
create table if not exists reading_plans (
    id            uuid primary key default gen_random_uuid(),
    start_date    date not null,
    days          smallint not null,
    translation   text not null,
    overview      text not null,
    schedule      jsonb not null,              -- [{day, date, references: [...]}, ...]
    created_at    timestamptz not null default now()
);
alter table reading_plans add column if not exists user_id uuid references auth.users(id) on delete set null;
create index if not exists reading_plans_user_idx on reading_plans (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Journal: a saved answer or verse plus the person's own reflection
-- ---------------------------------------------------------------------------
create table if not exists journal_entries (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    session_id   uuid references chat_sessions(id) on delete set null,
    question     text,
    answer       text,
    passage_ref  text,                          -- e.g. 'Psalms 42:5'
    verse_text   text,
    citations    jsonb not null default '[]'::jsonb,
    reflection   text not null default '',
    mood         text check (mood is null or mood in
                   ('grief', 'joy', 'waiting', 'decision', 'gratitude', 'doubt', 'peace', 'longing')),
    tags         text[] not null default '{}',
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists journal_entries_user_idx on journal_entries (user_id, created_at desc);
alter table journal_entries enable row level security;
drop policy if exists "users manage their own journal" on journal_entries;
create policy "users manage their own journal" on journal_entries
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Memory: short notes Aquila keeps about a person, recalled by similarity
-- ---------------------------------------------------------------------------
create table if not exists user_memories (
    id           bigint generated always as identity primary key,
    user_id      uuid not null references auth.users(id) on delete cascade,
    content      text not null,
    kind         text not null default 'note' check (kind in ('note', 'journal')),
    session_id   uuid,
    journal_id   uuid references journal_entries(id) on delete cascade,
    embedding    vector(1536) not null,
    created_at   timestamptz not null default now()
);
create index if not exists user_memories_user_idx on user_memories (user_id, created_at desc);
alter table user_memories enable row level security;
drop policy if exists "users manage their own memories" on user_memories;
create policy "users manage their own memories" on user_memories
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Per-person tables stay small (tens to hundreds of rows), so an exact scan
-- filtered by user_id beats an approximate vector index here.
create or replace function match_user_memories(
    p_user_id uuid,
    query_embedding vector(1536),
    match_count int default 4,
    min_similarity float default 0.25
)
returns table (id bigint, content text, kind text, created_at timestamptz, similarity float)
language sql stable
as $$
    select m.id, m.content, m.kind, m.created_at,
           1 - (m.embedding <=> query_embedding) as similarity
    from user_memories m
    where m.user_id = p_user_id
      and 1 - (m.embedding <=> query_embedding) >= min_similarity
    order by m.embedding <=> query_embedding
    limit match_count;
$$;

-- The function takes a user id as a plain argument, so only the server may
-- call it. (RLS would already hide other people's rows from anon callers,
-- this just closes the door outright.)
revoke execute on function match_user_memories(uuid, vector, int, float) from public, anon, authenticated;
grant execute on function match_user_memories(uuid, vector, int, float) to service_role;
