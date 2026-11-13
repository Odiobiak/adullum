-- The Amens wall in three views (app/one_another.py::wall, web/refuge.js::amensRoom).
--
-- Paste into the Supabase SQL editor once, after 20261121_usage_limits.sql.
-- Safe to re-run.
--
--   To pray for: posts by others still on the wall that the viewer hasn't
--     said amen to, in the same fair order as amens_wall (fewest amens first,
--     shuffled per viewer), a page at a time.
--   Prayed: posts the viewer has said amen to that are still on the wall,
--     the most recent amen first. Saying amen moves a post here, so it leaves
--     the wall without being lost.
--   Counts of both, for the tabs and the "carried" line.
--
-- amens_wall stays as it was; nothing reads it after this.

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
$$;

revoke all on function amens_to_carry(uuid, timestamptz, integer, integer) from public, anon, authenticated;
revoke all on function amens_carried(uuid, timestamptz, integer) from public, anon, authenticated;
revoke all on function amens_wall_counts(uuid, timestamptz) from public, anon, authenticated;
grant execute on function amens_to_carry(uuid, timestamptz, integer, integer) to service_role;
grant execute on function amens_carried(uuid, timestamptz, integer) to service_role;
grant execute on function amens_wall_counts(uuid, timestamptz) to service_role;
