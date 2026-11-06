-- Churches: the Church tab (app/churches.py, web/church.js).
--
-- Run once in the Supabase SQL editor, after the earlier migrations. Safe to
-- run again.
--
-- A church here belongs to one person: it's a church they've put in their own
-- list, not a shared directory entry. Two people who both go to the same
-- church each have their own row, so nothing here is ever public, nobody can
-- see who else has a church, and a church is never shown to anyone who
-- didn't add it. That is deliberate: Adullum is personal first.
--
-- `gatherings` is [{label, day (0 = Sunday), time "HH:MM"}] in the church's
-- own time zone; the browser shows each in the person's time too.
-- `notices` is [{text, date?}] and `events` is [{title, date "YYYY-MM-DD",
-- time?}], both read from the church's site when it was added from a link,
-- and refreshed when the page is opened a week or more after the last check.
-- `notices_seen_at` clears the count on the info icon once they're read.

create table if not exists churches (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid not null references auth.users(id) on delete cascade,
    name                text not null,
    city                text,
    time_zone           text,                          -- IANA name, e.g. 'Africa/Lagos'
    address             text,
    pastors             text,
    website             text,
    youtube_url         text,
    youtube_channel_id  text,                          -- found from the channel page, for its feed
    podcast_url         text,
    facebook_url        text,
    gatherings          jsonb not null default '[]'::jsonb,
    notices             jsonb not null default '[]'::jsonb,
    events              jsonb not null default '[]'::jsonb,
    source_url          text,                          -- the link it was read from, if any
    checked_at          timestamptz,
    notices_seen_at     timestamptz,
    live_alerts         boolean not null default true,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists churches_user_idx on churches (user_id, created_at);

-- Same rule as every /me table: the server uses the service role and filters
-- by user in code. These policies are for a future client that talks to
-- Supabase directly.
alter table churches enable row level security;
drop policy if exists "users manage their own churches" on churches;
create policy "users manage their own churches" on churches
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- A sermon note can say which of the person's churches it's from, where it
-- was watched (a YouTube or podcast link), and how the week after it is going
-- (`week`: {done: {step: true}, answer: "..."}; see app/churches.py).
alter table sermon_notes add column if not exists church_id uuid references churches(id) on delete set null;
alter table sermon_notes add column if not exists source_url text;
alter table sermon_notes add column if not exists week jsonb;

-- Listen: which seasons a public sermon speaks to (weary, anxious, ...),
-- worked out once from its title and description and kept, so a sermon is
-- never tagged twice. It holds nothing about any person, only the public
-- video or episode, keyed like 'yt:<video id>' or 'pod:<hash of its link>'.
create table if not exists sermon_moods (
    item_id     text primary key,
    moods       text[] not null default '{}',
    tagged_at   timestamptz not null default now()
);
alter table sermon_moods enable row level security;
