-- How long an Amens post stays on the wall (app/one_another.py, web/refuge.js).
--
-- Paste into the Supabase SQL editor once, after 20261116_amens_at_scale.sql.
-- Safe to re-run.
--
--   A prayer request stays two weeks from when it goes up, and its writer can
--     keep it up two weeks more at a time, up to two months in all.
--   Good news stays a week.
--   A prayer request marked answered stays five more days, shown as good news
--     with a line on how, so the people who prayed get to see it.
-- After that it leaves the wall for everyone else. The writer's own copy, with
-- every amen and kind word, never goes.
--
-- `expires_at` is when a post leaves the wall, set when it goes up and moved
-- by keeping it up or marking it answered. The wall's functions read it, so
-- they're replaced here (amens_wall's answer gains two columns, so it's
-- dropped and made again).

alter table refuge_posts add column if not exists expires_at   timestamptz;
alter table refuge_posts add column if not exists kept_up      smallint not null default 0;  -- times kept up two weeks more
alter table refuge_posts add column if not exists answered_at  timestamptz;
alter table refuge_posts add column if not exists answer_note  text check (answer_note is null or char_length(answer_note) <= 280);

update refuge_posts
    set expires_at = approved_at + case when kind = 'rejoice' then interval '7 days' else interval '14 days' end
    where approved_at is not null and expires_at is null;

create index if not exists refuge_posts_live_idx on refuge_posts (expires_at desc) where status = 'approved';

drop function if exists amens_wall(uuid, timestamptz, integer, integer);
create function amens_wall(viewer uuid, since timestamptz, max_posts integer, skip integer default 0)
returns table (id uuid, kind text, body text, created_at timestamptz, amen_count integer, reacted boolean, sent_kind_word boolean,
               answered_at timestamptz, answer_note text)
language sql stable as $$
    select p.id, p.kind, p.body, p.created_at, p.amen_count,
           exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer) as reacted,
           exists (select 1 from refuge_kind_words w where w.post_id = p.id and w.user_id = viewer) as sent_kind_word,
           p.answered_at, p.answer_note
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
    order by reacted,
             case when p.amen_count = 0 then 0 when p.amen_count < 3 then 1 when p.amen_count < 10 then 2
                  when p.amen_count < 30 then 3 else 4 end,
             md5(viewer::text || p.id::text)
    limit max_posts offset skip
$$;

create or replace function amens_waiting(viewer uuid, since timestamptz)
returns integer
language sql stable as $$
    select count(*)::integer
    from refuge_posts p
    where p.status = 'approved' and p.user_id <> viewer and p.approved_at >= since and p.expires_at > now()
      and not exists (select 1 from refuge_reactions r where r.post_id = p.id and r.user_id = viewer)
$$;

revoke all on function amens_wall(uuid, timestamptz, integer, integer) from public, anon, authenticated;
revoke all on function amens_waiting(uuid, timestamptz) from public, anon, authenticated;
grant execute on function amens_wall(uuid, timestamptz, integer, integer) to service_role;
grant execute on function amens_waiting(uuid, timestamptz) to service_role;
