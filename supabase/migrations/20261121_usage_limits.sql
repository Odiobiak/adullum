-- Daily limits (app/quota.py). Adullam is free and paid for by people who
-- give, so every answer that costs money is counted: per person (a user id,
-- or "guest:<scrambled address>") and, as estimated spend, for the whole app
-- (subject '*', kind 'spend', in tenths of a cent). Rows hold counts only,
-- never what anyone asked, and are pruned after a week.
--
-- Run once, after the others, in the Supabase SQL editor. Until it runs,
-- nothing is limited and the app works as before.

create table if not exists usage_days (
    subject  text    not null,
    kind     text    not null,
    day      date    not null,
    count    integer not null default 0,
    primary key (subject, kind, day)
);

create index if not exists usage_days_day_idx on usage_days (day);

-- No policies: only the server's service role reads or writes this table.
alter table usage_days enable row level security;

-- Counts one use of `p_kind` by `p_subject` on `p_day` and adds `p_cost` to
-- the day's spend, in one call. Returns 'ok', or 'limit' when the person has
-- had `p_limit` today, or 'budget' when the spend would pass `p_budget`.
-- A limit or budget of 0 or less means none. The count only moves when the
-- answer is 'ok', so a refused request costs the person nothing.
create or replace function use_quota(
    p_subject text, p_kind text, p_day date, p_limit integer, p_cost integer, p_budget integer
) returns text
language plpgsql security definer set search_path = public as $$
declare
    used integer;
begin
    if p_budget > 0 and p_cost > 0 then
        select count into used from usage_days where subject = '*' and kind = 'spend' and day = p_day;
        if coalesce(used, 0) + p_cost > p_budget then
            return 'budget';
        end if;
    end if;

    insert into usage_days as u (subject, kind, day, count)
    values (p_subject, p_kind, p_day, 1)
    on conflict (subject, kind, day) do update set count = u.count + 1
        where p_limit <= 0 or u.count < p_limit
    returning count into used;
    if used is null then
        return 'limit';
    end if;

    if p_cost > 0 then
        insert into usage_days as u (subject, kind, day, count)
        values ('*', 'spend', p_day, p_cost)
        on conflict (subject, kind, day) do update set count = u.count + p_cost;
    end if;

    -- Now and then, forget counts older than a week.
    if random() < 0.01 then
        delete from usage_days where day < p_day - 7;
    end if;
    return 'ok';
end;
$$;

revoke all on function use_quota(text, text, date, integer, integer, integer) from public, anon, authenticated;
grant execute on function use_quota(text, text, date, integer, integer, integer) to service_role;
