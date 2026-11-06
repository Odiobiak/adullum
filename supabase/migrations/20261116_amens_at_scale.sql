-- Amens at scale (app/one_another.py, web/refuge.js).
--
-- Paste into the Supabase SQL editor once, after the other migrations
-- (it needs 20261110_refuge.sql and 20261115_reminders.sql). Safe to re-run:
-- every statement is guarded, and the backfills set values rather than add.
--
-- What changes, and why:
--   Counts kept on the post. `amen_count` and `kind_word_count` on
--     refuge_posts are kept up to date by triggers on refuge_reactions and
--     refuge_kind_words. Counting by loading every amen stops at 1,000 rows
--     (Supabase's limit on one answer) and slows down as amens pile up.
--   A daily total. `refuge_amen_days` holds how many amens were said each
--     day (UTC), kept by the same trigger, so "amens this week" is seven
--     small rows instead of a count over every amen ever said.
--   When a post went up. `approved_at` is set when a post reaches the wall
--     (straight away when the automatic check is clear, or when the desk
--     approves it). The wall's month is counted from it.
--   A fair wall. `amens_wall` gives each person posts by others they haven't
--     prayed for first, those with the fewest amens first, in an order of
--     their own (a shuffle seeded by who's looking), so prayer spreads across
--     every request instead of piling onto the newest. It pages, so the whole
--     month can be read.
--   What's new. `refuge_wall_visits` keeps when someone last opened the wall,
--     and `amens_waiting` counts what's gone up since that they haven't said
--     amen to: the home notice's number.
--   A daily digest. `refuge_digests` keeps when each writer was last sent
--     "12 people prayed for you today"; `amens_digest_due` finds who has new
--     amens or kind words, and `claim_amens_digest` makes sure the two
--     senders (the server's loop and the scheduled workflow) never both send.
--     `profiles.amens_digest` lets someone turn it off, and
--     `profiles.time_zone` lets it arrive in their evening.
--
-- The functions are for the server only: callable by the service role and
-- nobody else, since `amens_digest_due` returns who wrote posts. Nothing here
-- ever goes to a browser with an author attached.

-- ---------------------------------------------------------------------------
-- Columns
-- ---------------------------------------------------------------------------
alter table refuge_posts add column if not exists amen_count       integer not null default 0;
alter table refuge_posts add column if not exists kind_word_count  integer not null default 0;
alter table refuge_posts add column if not exists approved_at      timestamptz;

alter table profiles add column if not exists amens_digest boolean not null default true;
alter table profiles add column if not exists time_zone    text;

update refuge_posts set approved_at = coalesce(reviewed_at, created_at)
    where status in ('approved', 'reported') and approved_at is null;
update refuge_posts p set amen_count = (select count(*) from refuge_reactions r where r.post_id = p.id);
update refuge_posts p set kind_word_count = (select count(*) from refuge_kind_words w where w.post_id = p.id);

create index if not exists refuge_posts_approved_idx on refuge_posts (approved_at desc) where status = 'approved';
create index if not exists refuge_reactions_user_idx on refuge_reactions (user_id, post_id);
create index if not exists refuge_kind_words_user_idx on refuge_kind_words (user_id, post_id);

-- ---------------------------------------------------------------------------
-- Amens per day, and the triggers that keep every count
-- ---------------------------------------------------------------------------
create table if not exists refuge_amen_days (
    day    date primary key,                     -- UTC
    amens  integer not null default 0
);
insert into refuge_amen_days (day, amens)
    select (created_at at time zone 'utc')::date, count(*) from refuge_reactions group by 1
    on conflict (day) do update set amens = excluded.amens;

create or replace function refuge_count_reaction() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        update refuge_posts set amen_count = amen_count + 1 where id = new.post_id;
        insert into refuge_amen_days (day, amens) values ((new.created_at at time zone 'utc')::date, 1)
            on conflict (day) do update set amens = refuge_amen_days.amens + 1;
        return new;
    end if;
    update refuge_posts set amen_count = greatest(amen_count - 1, 0) where id = old.post_id;
    update refuge_amen_days set amens = greatest(amens - 1, 0) where day = (old.created_at at time zone 'utc')::date;
    return old;
end $$;
drop trigger if exists refuge_reactions_count on refuge_reactions;
create trigger refuge_reactions_count after insert or delete on refuge_reactions
    for each row execute function refuge_count_reaction();

create or replace function refuge_count_kind_word() returns trigger
language plpgsql as $$
begin
    if tg_op = 'INSERT' then
        update refuge_posts set kind_word_count = kind_word_count + 1 where id = new.post_id;
        return new;
    end if;
    update refuge_posts set kind_word_count = greatest(kind_word_count - 1, 0) where id = old.post_id;
    return old;
end $$;
drop trigger if exists refuge_kind_words_count on refuge_kind_words;
create trigger refuge_kind_words_count after insert or delete on refuge_kind_words
    for each row execute function refuge_count_kind_word();

-- ---------------------------------------------------------------------------
-- The fair wall, and what's new for someone
-- ---------------------------------------------------------------------------
create table if not exists refuge_wall_visits (
    user_id  uuid primary key references auth.users(id) on delete cascade,
    seen_at  timestamptz not null default now()
);

-- Posts by other people that went up since `since`, for `viewer`: the ones
-- they haven't said amen to first, then those with the fewest amens (in bands,
-- so a post with 4 and one with 6 count as alike), then the viewer's own
-- shuffle. Never returns who wrote a post.
create or replace function amens_wall(viewer uuid, since timestamptz, max_posts integer, skip integer default 0)
returns table (id uuid, kind text, body text, created_at timestamptz, amen_count integer, reacted boolean, sent_kind_word boolean)
language sql stable as $$
    select p.id, p.kind, p.body, p.created_at, p.amen_count,
           exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer) as reacted,
           exists (select 1 from refuge_kind_words w where w.post_id = p.id and w.user_id = viewer) as sent_kind_word
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since
    order by reacted,
             case when p.amen_count = 0 then 0 when p.amen_count < 3 then 1 when p.amen_count < 10 then 2
                  when p.amen_count < 30 then 3 else 4 end,
             md5(viewer::text || p.id::text)
    limit max_posts offset skip
$$;

-- How many posts by others went up since `since` that `viewer` hasn't said
-- amen to.
create or replace function amens_waiting(viewer uuid, since timestamptz)
returns integer
language sql stable as $$
    select count(*)::integer
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since
      and not exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer)
$$;

-- Kind words sent to some posts, counted by which word: what a writer sees.
create or replace function kind_word_tally(post_ids uuid[])
returns table (post_id uuid, choice text, n integer)
language sql stable as $$
    select w.post_id, w.choice, count(*)::integer
    from refuge_kind_words w
    where w.post_id = any(post_ids)
    group by w.post_id, w.choice
$$;

-- ---------------------------------------------------------------------------
-- The daily digest
-- ---------------------------------------------------------------------------
create table if not exists refuge_digests (
    user_id       uuid primary key references auth.users(id) on delete cascade,
    last_sent_at  timestamptz not null
);

-- Writers with a post on the wall this month, a device that takes
-- notifications, the digest left on, and no digest within `min_gap`, with
-- how many prayed, rejoiced and sent kind words since their last one (or
-- within `look_back`, whichever is shorter).
create or replace function amens_digest_due(min_gap interval, look_back interval)
returns table (user_id uuid, time_zone text, prayed integer, rejoiced integer, kind_words integer)
language sql stable as $$
    with writers as (
        select distinct p.user_id, pr.time_zone,
               greatest(coalesce(d.last_sent_at, '-infinity'::timestamptz), now() - look_back) as since
        from refuge_posts p
        left join profiles pr on pr.id = p.user_id
        left join refuge_digests d on d.user_id = p.user_id
        where p.status = 'approved' and p.approved_at >= now() - interval '30 days'
          and coalesce(pr.amens_digest, true)
          and (d.last_sent_at is null or d.last_sent_at <= now() - min_gap)
          and exists (select 1 from push_subscriptions s where s.user_id = p.user_id)
    )
    select w.user_id, w.time_zone,
        (select count(*) from refuge_reactions r join refuge_posts p on p.id = r.post_id
          where p.user_id = w.user_id and p.kind = 'burden' and r.created_at > w.since)::integer,
        (select count(*) from refuge_reactions r join refuge_posts p on p.id = r.post_id
          where p.user_id = w.user_id and p.kind = 'rejoice' and r.created_at > w.since)::integer,
        (select count(*) from refuge_kind_words k join refuge_posts p on p.id = k.post_id
          where p.user_id = w.user_id and k.created_at > w.since)::integer
    from writers w
$$;

-- Marks a writer's digest as sent now, unless one went within `min_gap`.
-- True only for the caller that claimed it, so a digest is never sent twice.
create or replace function claim_amens_digest(writer uuid, min_gap interval)
returns boolean
language plpgsql as $$
begin
    insert into refuge_digests (user_id, last_sent_at) values (writer, now())
        on conflict (user_id) do update set last_sent_at = excluded.last_sent_at
        where refuge_digests.last_sent_at <= now() - min_gap;
    return found;
end $$;

-- ---------------------------------------------------------------------------
-- Only the server may call these, or read the new tables
-- ---------------------------------------------------------------------------
revoke all on function amens_wall(uuid, timestamptz, integer, integer) from public, anon, authenticated;
revoke all on function amens_waiting(uuid, timestamptz) from public, anon, authenticated;
revoke all on function kind_word_tally(uuid[]) from public, anon, authenticated;
revoke all on function amens_digest_due(interval, interval) from public, anon, authenticated;
revoke all on function claim_amens_digest(uuid, interval) from public, anon, authenticated;
grant execute on function amens_wall(uuid, timestamptz, integer, integer) to service_role;
grant execute on function amens_waiting(uuid, timestamptz) to service_role;
grant execute on function kind_word_tally(uuid[]) to service_role;
grant execute on function amens_digest_due(interval, interval) to service_role;
grant execute on function claim_amens_digest(uuid, interval) to service_role;

alter table refuge_amen_days enable row level security;
alter table refuge_wall_visits enable row level security;
alter table refuge_digests enable row level security;
