-- Pebbles become goals and habits; praying and fasting move to the prayer list.
-- (app/refuge.py, app/prayers.py, app/fasting.py)
-- Paste into the Supabase SQL editor once, after the earlier migrations.
-- Safe to re-run: every statement is guarded.
--
-- What changes:
--   refuge_seeds    goals gain a number to reach (target, progress, unit) and a
--                   date to reach it by (due_on); habits gain how many days a
--                   week they're meant for (per_week). Hopes become goals.
--   prayer_days     the days someone prayed: for one request on their list, or
--                   just "I prayed today" (prayer_id null). Feeds the Prayers
--                   tab's week of prayer and each request's "Prayed today".
--   fasts           a fast: what kind, how many days, what it's for, and how
--                   it went once it's finished.
--   Prayer pebbles  ("something to keep praying, day by day") move onto the
--                   prayer list as requests, keeping their days prayed, and
--                   leave Pebbles. They keep their ids, so this is idempotent.
--
-- None of it feeds Aquila's memory on its own. A moved prayer only gets a
-- memory note if the person later edits it with memory switched on, the same
-- as any prayer they add.

-- ---------------------------------------------------------------------------
-- Pebbles: goals that can be measured, habits with a weekly target
-- ---------------------------------------------------------------------------
alter table refuge_seeds add column if not exists target   numeric check (target is null or target > 0);
alter table refuge_seeds add column if not exists progress numeric not null default 0 check (progress >= 0);
alter table refuge_seeds add column if not exists unit     text;      -- 'books', 'km', 'pounds saved'
alter table refuge_seeds add column if not exists due_on   date;      -- reach it by, optional
alter table refuge_seeds add column if not exists per_week smallint not null default 7 check (per_week between 1 and 7);

-- ---------------------------------------------------------------------------
-- The days someone prayed
-- ---------------------------------------------------------------------------
create table if not exists prayer_days (
    user_id     uuid not null references auth.users(id) on delete cascade,
    day         date not null,                   -- the person's local day (app/days.py)
    prayer_id   uuid references prayers(id) on delete cascade,  -- null: "I prayed today"
    created_at  timestamptz not null default now()
);
-- One mark per request per day, and one general mark per day. NULLS NOT
-- DISTINCT (Postgres 15+) is what makes the general mark unique too.
create unique index if not exists prayer_days_unique_idx on prayer_days (user_id, day, prayer_id) nulls not distinct;
create index if not exists prayer_days_user_idx on prayer_days (user_id, day desc);
alter table prayer_days enable row level security;
drop policy if exists "users manage their own prayer days" on prayer_days;
create policy "users manage their own prayer days" on prayer_days
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Fasting
-- ---------------------------------------------------------------------------
-- kind:
--   full     water only
--   daniel   a partial fast, vegetables and water (Daniel 1:12)
--   meal     skipping a meal, or meals
--   other    something else given up for a time (detail says what)
create table if not exists fasts (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid not null references auth.users(id) on delete cascade,
    kind         text not null default 'full' check (kind in ('full', 'daniel', 'meal', 'other')),
    detail       text,                          -- 'Lunch', 'Social media'
    intention    text,                          -- what they're fasting and praying for
    passage_ref  text,                          -- a verse to hold onto
    starts_on    date not null,
    days         smallint not null check (days between 1 and 40),
    status       text not null default 'active' check (status in ('active', 'finished')),
    finished_on  date,
    reflection   text,                          -- what they noticed, in their words
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);
create index if not exists fasts_user_idx on fasts (user_id, status, starts_on desc);
alter table fasts enable row level security;
drop policy if exists "users manage their own fasts" on fasts;
create policy "users manage their own fasts" on fasts
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Prayer pebbles move to the prayer list
-- ---------------------------------------------------------------------------
-- Growing and set-aside ones come back open (set aside has no meaning on the
-- list, and nothing should be lost); fulfilled ones arrive answered, with how.
insert into prayers (id, user_id, body, passage_ref, status, answer_note, answered_at, created_at, updated_at)
select
    s.id,
    s.user_id,
    case when coalesce(trim(s.note), '') = '' then s.title else s.title || E'\n\n' || s.note end,
    s.passage_ref,
    case when s.status = 'fulfilled' then 'answered' else 'open' end,
    case when s.status = 'fulfilled' then s.outcome_note end,
    case when s.status = 'fulfilled' then coalesce(s.fulfilled_at, s.updated_at) end,
    s.created_at,
    s.updated_at
from refuge_seeds s
where s.kind = 'prayer'
on conflict (id) do nothing;

insert into prayer_days (user_id, day, prayer_id)
select c.user_id, c.day, c.seed_id
from refuge_checkins c
join refuge_seeds s on s.id = c.seed_id
where s.kind = 'prayer'
on conflict do nothing;

-- Their check-ins go with them (refuge_checkins cascades).
delete from refuge_seeds where kind = 'prayer';

-- Hopes become goals: open until reached, which is what a hope already was.
update refuge_seeds set kind = 'goal' where kind = 'hope';

alter table refuge_seeds drop constraint if exists refuge_seeds_kind_check;
alter table refuge_seeds add constraint refuge_seeds_kind_check check (kind in ('goal', 'habit'));
