-- Refuge: the quiet room in the cave (app/refuge.py, app/one_another.py,
-- web/refuge.js).
-- Paste into the Supabase SQL editor once, after the earlier migrations.
-- Safe to re-run: every statement is guarded.
--
-- What lives here:
--   refuge_writings   what someone wrote and chose to keep. Writing they let
--                     go of never reaches the server at all.
--   refuge_talks      a talk with Aquila they chose to keep. Talks vanish by
--                     default; nothing is stored until they press Keep.
--   refuge_seeds      hopes, goals, habits and prayers they're growing into,
--   refuge_checkins   and the days they tended a habit or prayer.
--   refuge_posts      the One another wall: burdens and good news shared
--                     without a name, read by a person before they appear,
--   refuge_reactions  "I prayed" / "Rejoicing with you",
--   refuge_kind_words one of a fixed set of encouragements, never free text,
--   refuge_reports    and reports, which send a post back to the admin desk.
--
-- None of it ever feeds Aquila's memory (user_memories) or the home screen.

-- ---------------------------------------------------------------------------
-- Writing kept, only for the person who wrote it
-- ---------------------------------------------------------------------------
create table if not exists refuge_writings (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    shape       text not null default 'blank' check (shape in ('blank', 'lament', 'thanks', 'dream')),
    body        text not null,
    created_at  timestamptz not null default now()
);
create index if not exists refuge_writings_user_idx on refuge_writings (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Talks with Aquila that were kept. `messages` is the whole exchange as
-- [{role: 'user' | 'aquila', content}], rewritten as the talk goes on.
-- ---------------------------------------------------------------------------
create table if not exists refuge_talks (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    title       text not null,
    messages    jsonb not null default '[]'::jsonb,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists refuge_talks_user_idx on refuge_talks (user_id, updated_at desc);

-- ---------------------------------------------------------------------------
-- Seeds: hopes, goals, habits and prayers to grow into
-- ---------------------------------------------------------------------------
create table if not exists refuge_seeds (
    id            uuid primary key default gen_random_uuid(),
    user_id       uuid not null references auth.users(id) on delete cascade,
    kind          text not null check (kind in ('hope', 'goal', 'habit', 'prayer')),
    title         text not null,
    note          text,                          -- why it matters, or what it would look like
    passage_ref   text,                          -- a verse to hold onto, e.g. 'Jeremiah 29:11'
    steps         jsonb not null default '[]'::jsonb,  -- goals: [{text, done}]
    status        text not null default 'growing' check (status in ('growing', 'fulfilled', 'set_aside')),
    outcome_note  text,                          -- how it came to pass, in their words
    fulfilled_at  timestamptz,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);
create index if not exists refuge_seeds_user_idx on refuge_seeds (user_id, status, created_at desc);

create table if not exists refuge_checkins (
    seed_id     uuid not null references refuge_seeds(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    day         date not null,                   -- the person's local day (app/days.py)
    primary key (seed_id, day)
);
create index if not exists refuge_checkins_user_idx on refuge_checkins (user_id, day desc);

-- ---------------------------------------------------------------------------
-- One another: shared without a name
-- ---------------------------------------------------------------------------
-- status:
--   pending   passed the automatic check, waiting on the admin desk
--   approved  on the wall
--   reported  someone reported it; off the wall until the desk looks again
--   removed   taken off by the desk (the author sees "Not shared")
-- The author's id is kept so they can see and take down their own post, and
-- is never sent to anyone else, the admin desk included.
create table if not exists refuge_posts (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    kind         text not null default 'burden' check (kind in ('burden', 'rejoice')),
    body         text not null check (char_length(body) <= 280),
    status       text not null default 'pending' check (status in ('pending', 'approved', 'reported', 'removed')),
    auto_check   jsonb not null default '{}'::jsonb,  -- what the automatic check noticed, for the desk
    review_note  text,
    reviewed_at  timestamptz,
    created_at   timestamptz not null default now()
);
create index if not exists refuge_posts_wall_idx on refuge_posts (status, created_at desc);
create index if not exists refuge_posts_user_idx on refuge_posts (user_id, created_at desc);

create table if not exists refuge_reactions (
    post_id     uuid not null references refuge_posts(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    created_at  timestamptz not null default now(),
    primary key (post_id, user_id)
);

-- `choice` indexes app/one_another.py::KIND_WORDS, so nobody can write freely
-- to a stranger.
create table if not exists refuge_kind_words (
    post_id     uuid not null references refuge_posts(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    choice      text not null,
    created_at  timestamptz not null default now(),
    primary key (post_id, user_id)
);

create table if not exists refuge_reports (
    post_id     uuid not null references refuge_posts(id) on delete cascade,
    user_id     uuid not null references auth.users(id) on delete cascade,
    reason      text,
    created_at  timestamptz not null default now(),
    primary key (post_id, user_id)
);

-- ---------------------------------------------------------------------------
-- Row level security. The server uses the service-role key and filters by
-- user in code (see app/cave.py); these policies are for any future client
-- that talks to Supabase directly. The wall tables get no policy at all, so
-- only the server can read them: a direct client could otherwise see who
-- wrote a post.
-- ---------------------------------------------------------------------------
alter table refuge_writings enable row level security;
drop policy if exists "users manage their own refuge writing" on refuge_writings;
create policy "users manage their own refuge writing" on refuge_writings
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table refuge_talks enable row level security;
drop policy if exists "users manage their own refuge talks" on refuge_talks;
create policy "users manage their own refuge talks" on refuge_talks
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table refuge_seeds enable row level security;
drop policy if exists "users manage their own seeds" on refuge_seeds;
create policy "users manage their own seeds" on refuge_seeds
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table refuge_checkins enable row level security;
drop policy if exists "users manage their own checkins" on refuge_checkins;
create policy "users manage their own checkins" on refuge_checkins
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table refuge_posts enable row level security;
alter table refuge_reactions enable row level security;
alter table refuge_kind_words enable row level security;
alter table refuge_reports enable row level security;
