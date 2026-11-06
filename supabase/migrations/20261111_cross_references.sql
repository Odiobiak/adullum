-- Classic cross-references for Connections (app/connections.py, web/graph.js).
-- Paste into the Supabase SQL editor once, after the earlier migrations, then
-- load the data with `python scripts/ingest_cross_references.py`.
-- Safe to re-run: every statement is guarded.
--
-- The data is OpenBible.info's cross-references (CC BY, credited in the
-- graph's legend): the public-domain Treasury of Scripture Knowledge, with
-- readers' votes on how useful each link is. The ingest keeps links with at
-- least 5 votes, about 118,000 rows and a few MB, so it sits comfortably in
-- the free plan.
--
-- A link points from one verse to a verse or a short run of verses in the
-- same chapter ("Genesis 1:1" -> "Proverbs 8:22-30"). Book names are the
-- app's canonical names, the same as the verses table.

create table if not exists cross_references (
    id              bigserial primary key,
    from_book       text not null,
    from_chapter    smallint not null,
    from_verse      smallint not null,
    to_book         text not null,
    to_chapter      smallint not null,
    to_verse_start  smallint not null,
    to_verse_end    smallint not null,
    votes           integer not null default 0,
    check (to_verse_end >= to_verse_start),
    -- Lets the ingest be re-run without doubling anything.
    unique (from_book, from_chapter, from_verse, to_book, to_chapter, to_verse_start)
);

-- The one question asked of this table: a verse's best-voted links.
create index if not exists cross_references_from_idx
    on cross_references (from_book, from_chapter, from_verse, votes desc);

-- Public reference data. Only the server reads it (with the service-role
-- key); RLS with no policy keeps any direct client out.
alter table cross_references enable row level security;
