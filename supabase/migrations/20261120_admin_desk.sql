-- The admin desk as a moderation dashboard (app/desk.py, web/refuge.js).
--
-- Paste into the Supabase SQL editor once, after 20261119_declarations.sql.
-- Safe to re-run.
--
--   status 'held'           a post taken off the wall by the desk while it's
--                           looked into, apart from one taken off by a report.
--   refuge_reports.category why it was reported, so "someone may be in
--                           danger" can go to the top of the desk.
--   refuge_moderation_log   the audit trail: every decision on the desk, who
--                           made it and why, and every report as it comes in.
--                           A post deleted by its writer leaves its entries
--                           behind with no post, so nothing they wrote stays.
--
-- Like the rest of the wall, none of it carries who wrote a post.

alter table refuge_posts drop constraint if exists refuge_posts_status_check;
alter table refuge_posts add constraint refuge_posts_status_check
    check (status in ('pending', 'approved', 'reported', 'held', 'removed'));

alter table refuge_reports add column if not exists category text not null default 'other'
    check (category in ('danger', 'identifies', 'unkind', 'spam', 'other'));

create table if not exists refuge_moderation_log (
    id           bigint generated always as identity primary key,
    post_id      uuid references refuge_posts(id) on delete set null,
    action       text not null check (action in ('approve', 'remove', 'hold', 'report')),
    from_status  text,
    to_status    text,
    actor_id     uuid references auth.users(id) on delete set null,  -- null for a report: reporters stay unnamed
    actor_email  text,
    note         text check (note is null or char_length(note) <= 300),
    created_at   timestamptz not null default now()
);
create index if not exists refuge_moderation_log_time_idx on refuge_moderation_log (created_at desc);
create index if not exists refuge_moderation_log_post_idx on refuge_moderation_log (post_id, created_at);

-- No policy: only the server reads or writes the trail.
alter table refuge_moderation_log enable row level security;

-- ---------------------------------------------------------------------------
-- One decision, made and recorded together, so the trail never disagrees
-- with the wall. A post going up for the first time starts its time on the
-- wall at `went_up` (app/one_another.py works out `ends`); one coming back
-- keeps the time it had. Returns the status it had before, or null when the
-- post isn't there.
-- ---------------------------------------------------------------------------
create or replace function desk_decide(
    target uuid, new_status text, actor uuid, actor_email text, note text,
    went_up timestamptz default null, ends timestamptz default null
) returns text
language plpgsql security definer set search_path = public as $$
declare
    old_status text;
begin
    select status into old_status from refuge_posts where id = target for update;
    if not found then
        return null;
    end if;
    update refuge_posts set
        status      = new_status,
        review_note = note,
        reviewed_at = now(),
        expires_at  = case when approved_at is null then coalesce(ends, expires_at) else expires_at end,
        approved_at = coalesce(approved_at, went_up)
    where id = target;
    insert into refuge_moderation_log (post_id, action, from_status, to_status, actor_id, actor_email, note)
    values (
        target,
        case new_status when 'approved' then 'approve' when 'held' then 'hold' else 'remove' end,
        old_status, new_status, actor, actor_email, note
    );
    return old_status;
end;
$$;

-- The accounts behind ADMIN_EMAILS, so an urgent report can reach them as a
-- notification. Reads auth.users, so it's for the server only.
create or replace function desk_admin_ids(emails text[]) returns setof uuid
language sql stable security definer set search_path = public, auth as $$
    select id from auth.users where lower(email) = any(emails);
$$;

revoke all on function desk_decide(uuid, text, uuid, text, text, timestamptz, timestamptz) from public, anon, authenticated;
revoke all on function desk_admin_ids(text[]) from public, anon, authenticated;
grant execute on function desk_decide(uuid, text, uuid, text, text, timestamptz, timestamptz) to service_role;
grant execute on function desk_admin_ids(text[]) to service_role;
