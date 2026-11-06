-- Compact embeddings: one translation, 512 dimensions, half precision.
--
-- Run once in the Supabase SQL editor, after the earlier migrations. Safe to
-- run again: every step checks whether it has already happened.
--
-- Why: every verse of every translation used to carry a vector(1536), about
-- 6 KB, and the ivfflat index held a second copy at a full 8 KB page each.
-- Four translations came to roughly 1.8 GB, enough to fill a 2 GB disk and put
-- the project into read-only mode. After this migration:
--   1. Only the search translation (BSB, app/config.py::search_translation)
--      carries an embedding. match_verses searches those and returns the same
--      verses from whichever translation was asked for, so every translation
--      still gets semantic search.
--   2. Each embedding is 512 numbers instead of 1536.
--   3. Each number is stored at half precision (halfvec), 2 bytes instead of 4.
-- A verse's embedding goes from about 6 KB to about 1 KB, on a quarter of the
-- rows, and the whole thing lands near 60 MB including the index.
--
-- No re-embedding is needed. text-embedding-3 models are trained so that the
-- first N numbers of an embedding, rescaled to length 1, are a valid N-number
-- embedding (OpenAI documents this as equivalent to asking for `dimensions=N`).
-- So the existing vectors are shortened here in SQL, and app/retrieval.py
-- asks OpenAI for 512 dimensions from now on, which produces the same shape.
--
-- The whole file is one transaction, so a failure part way leaves nothing
-- half done. If the project is in read-only mode, `set transaction read write`
-- lifts it for this transaction only. Dropping the old index and rewriting the
-- table frees about 1.7 GB, which brings the disk back under Supabase's
-- read-only threshold.

begin;
set transaction read write;

-- A table rewrite plus an index build takes longer than the editor's default
-- statement timeout on a small instance.
set local statement_timeout = '15min';

do $$
declare
    pgvector_version text := (select extversion from pg_extension where extname = 'vector');
    verses_type text := (
        select format_type(atttypid, atttypmod) from pg_attribute
        where attrelid = to_regclass('public.verses') and attname = 'embedding' and not attisdropped
    );
    memories_type text := (
        select format_type(atttypid, atttypmod) from pg_attribute
        where attrelid = to_regclass('public.user_memories') and attname = 'embedding' and not attisdropped
    );
begin
    -- halfvec, subvector() and l2_normalize() all arrived in pgvector 0.7.
    if string_to_array(pgvector_version, '.')::int[] < array[0, 7] then
        raise exception 'pgvector % is too old, this needs 0.7 or later. Run: alter extension vector update;', pgvector_version;
    end if;

    if verses_type = 'vector(1536)' then
        -- Refuse to run if the search translation has nothing to keep, rather
        -- than leaving the app with no embeddings at all.
        if not exists (select 1 from verses where translation = 'BSB' and embedding is not null) then
            raise exception 'No BSB verses have embeddings. Ingest BSB first, or change the translation named in this file and in app/config.py::search_translation.';
        end if;

        -- The old index can't survive the type change (its operator class is
        -- for vector, not halfvec), and dropping it frees the most space.
        drop index if exists verses_embedding_idx;

        -- One statement rewrites the table: BSB rows keep a shortened,
        -- rescaled, half-precision copy, every other row drops its embedding,
        -- and the old files are released when the transaction commits.
        alter table verses
            alter column embedding type halfvec(512)
            using case
                when translation = 'BSB' and embedding is not null
                    then l2_normalize(subvector(embedding, 1, 512))::halfvec(512)
            end;
    end if;

    -- Memories share embed_query() with verse search, so they move to the same
    -- shape. Every memory keeps its embedding; only the size changes.
    if memories_type = 'vector(1536)' then
        alter table user_memories
            alter column embedding type halfvec(512)
            using l2_normalize(subvector(embedding, 1, 512))::halfvec(512);
    end if;
end $$;

-- The unique (translation, book, chapter, verse) constraint already has an
-- index on exactly these columns, so this one was a duplicate.
drop index if exists verses_ref_idx;

-- HNSW keeps itself up to date as rows are added, unlike ivfflat, which had to
-- be rebuilt after every ingest. Rows without an embedding aren't indexed.
create index if not exists verses_embedding_idx on verses
    using hnsw (embedding halfvec_cosine_ops);

-- ---------------------------------------------------------------------------
-- match_verses: search the embedded translation, return the requested one
-- ---------------------------------------------------------------------------
drop function if exists match_verses(vector, text, int);

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
    -- Find the nearest verses among the ones that carry an embedding. A verse
    -- the requested translation doesn't have (some modern translations omit a
    -- few verses KJV keeps) drops out of the join, so over-fetch to cover it.
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
-- match_user_memories: same function, new embedding type
-- ---------------------------------------------------------------------------
drop function if exists match_user_memories(uuid, vector, int, float);

create or replace function match_user_memories(
    p_user_id uuid,
    query_embedding halfvec(512),
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

-- Server only, as before: the function takes a user id as a plain argument.
revoke execute on function match_user_memories(uuid, halfvec, int, float) from public, anon, authenticated;
grant execute on function match_user_memories(uuid, halfvec, int, float) to service_role;

commit;
