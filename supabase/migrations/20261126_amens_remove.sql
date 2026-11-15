-- Remove from my wall (app/one_another.py::remove_from_wall, web/refuge.js::carryCard).
--
-- Paste into the Supabase SQL editor once, after 20261125_welcome_tour.sql.
-- Safe to re-run.
--
-- Someone who doesn't want to pray for or rejoice with a post can take it off
-- their own wall. It leaves only their view: the post stays up for everyone
-- else, its writer is never told, and it isn't counted as a report. The
-- wall's views below leave out whatever the viewer removed.

create table if not exists refuge_wall_removals (
    user_id     uuid not null references auth.users(id) on delete cascade,
    post_id     uuid not null references refuge_posts(id) on delete cascade,
    created_at  timestamptz not null default now(),
    primary key (user_id, post_id)
);
alter table refuge_wall_removals enable row level security;

create or replace function amens_to_carry(viewer uuid, since timestamptz, max_posts integer, skip integer default 0)
returns table (id uuid, kind text, body text, created_at timestamptz, amen_count integer, sent_kind_word boolean,
               answered_at timestamptz, answer_note text)
language sql stable as $$
    select p.id, p.kind, p.body, p.created_at, p.amen_count,
           exists (select 1 from refuge_kind_words w where w.post_id = p.id and w.user_id = viewer) as sent_kind_word,
           p.answered_at, p.answer_note
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
      and not exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer)
      and not exists (select 1 from refuge_wall_removals x where x.post_id = p.id and x.user_id = viewer)
    order by case when p.amen_count = 0 then 0 when p.amen_count < 3 then 1 when p.amen_count < 10 then 2
                  when p.amen_count < 30 then 3 else 4 end,
             md5(viewer::text || p.id::text)
    limit max_posts offset skip
$$;

create or replace function amens_carried(viewer uuid, since timestamptz, max_posts integer)
returns table (id uuid, kind text, body text, created_at timestamptz, amen_count integer, sent_kind_word boolean,
               answered_at timestamptz, answer_note text, amened_at timestamptz)
language sql stable as $$
    select p.id, p.kind, p.body, p.created_at, p.amen_count,
           exists (select 1 from refuge_kind_words w where w.post_id = p.id and w.user_id = viewer) as sent_kind_word,
           p.answered_at, p.answer_note, r.created_at as amened_at
    from refuge_posts p
    join refuge_reactions r on r.post_id = p.id and r.user_id = viewer
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
      and not exists (select 1 from refuge_wall_removals x where x.post_id = p.id and x.user_id = viewer)
    order by r.created_at desc
    limit max_posts
$$;

create or replace function amens_wall_counts(viewer uuid, since timestamptz)
returns table (to_carry integer, carried integer)
language sql stable as $$
    select count(*) filter (where r.post_id is null)::integer,
           count(*) filter (where r.post_id is not null)::integer
    from refuge_posts p
    left join refuge_reactions r on r.post_id = p.id and r.user_id = viewer
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
      and not exists (select 1 from refuge_wall_removals x where x.post_id = p.id and x.user_id = viewer)
$$;

-- The home screen's count of posts waiting for this person's amen.
create or replace function amens_waiting(viewer uuid, since timestamptz)
returns integer
language sql stable as $$
    select count(*)::integer
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
      and not exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer)
      and not exists (select 1 from refuge_wall_removals x where x.post_id = p.id and x.user_id = viewer)
$$;
