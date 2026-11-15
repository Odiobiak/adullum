-- What came back since someone last looked (app/one_another.py::amens_news,
-- the home's Amens line and the "new" marks on the wall).
--
-- Paste into the Supabase SQL editor once, after 20261126_amens_remove.sql.
-- Safe to re-run.
--
-- Two small counts, both measured from `since`, the last time the person
-- opened the wall (refuge_wall_visits):
--   amens_news            the amens and kind words on their own posts, a row
--                         per post with anything new. Never who sent them.
--   amens_answered_since  how many prayers they prayed for were marked
--                         answered by their writers.

-- Finding the new amens on a post reads its reactions by time.
create index if not exists refuge_reactions_post_time_idx on refuge_reactions (post_id, created_at);
create index if not exists refuge_kind_words_post_time_idx on refuge_kind_words (post_id, created_at);

create or replace function amens_news(writer uuid, since timestamptz)
returns table (post_id uuid, kind text, answered boolean, amens integer, kind_words integer)
language sql stable as $$
    select * from (
        select p.id, p.kind, p.answered_at is not null,
               (select count(*) from refuge_reactions r where r.post_id = p.id and r.created_at > since)::integer,
               (select count(*) from refuge_kind_words w where w.post_id = p.id and w.created_at > since)::integer
        from refuge_posts p
        where p.user_id = writer and p.approved_at is not null and p.created_at > now() - interval '90 days'
    ) news (post_id, kind, answered, amens, kind_words)
    where amens > 0 or kind_words > 0
$$;

create or replace function amens_answered_since(viewer uuid, since timestamptz)
returns integer
language sql stable as $$
    select count(*)::integer
    from refuge_posts p
    join refuge_reactions r on r.post_id = p.id and r.user_id = viewer
    where p.user_id <> viewer and p.answered_at > since and p.status = 'approved' and p.expires_at > now()
      and not exists (select 1 from refuge_wall_removals x where x.post_id = p.id and x.user_id = viewer)
$$;

-- Only the server may call these: amens_news reads a writer's posts.
revoke all on function amens_news(uuid, timestamptz) from public, anon, authenticated;
revoke all on function amens_answered_since(uuid, timestamptz) from public, anon, authenticated;
