-- The Numbers tab on the admin desk (app/numbers.py): how many people use
-- Adullam and what they use, as counts only. Nothing here returns who anyone
-- is or what they wrote, so the desk never sees a person, only totals.
--
-- Run once, after the others, in the Supabase SQL editor. Until it runs the
-- tab says what to run and still shows the server's memory.

create or replace function admin_numbers(p_today date)
returns jsonb
language plpgsql stable security definer set search_path = public, auth as $$
declare
    -- Each part of the app, by the table that holds what people make there.
    -- A table not made yet (its migration not run) is simply left out.
    parts constant text[][] := array[
        ['conversations', 'chat_sessions'],
        ['journal',       'journal_entries'],
        ['prayers',       'prayers'],
        ['sermons',       'sermon_notes'],
        ['declarations',  'declarations'],
        ['amens_posts',   'refuge_posts'],
        ['amens_prayed',  'refuge_reactions'],
        ['saved',         'saved_items'],
        ['bible_notes',   'verse_notes'],
        ['highlights',    'verse_highlights'],
        ['plans',         'reading_plans'],
        ['reflections',   'reflections'],
        ['churches',      'churches'],
        ['fasts',         'fasts'],
        ['writings',      'refuge_writings'],
        ['talks',         'refuge_talks']
    ];
    features jsonb := '[]'::jsonb;
    n_week int; n_month int; n_people int; n_total int;
    usage jsonb;
    spend jsonb;
begin
    for i in 1 .. array_length(parts, 1) loop
        continue when to_regclass('public.' || parts[i][2]) is null;
        execute format(
            'select count(*) filter (where created_at >= $1 - 6),
                    count(*) filter (where created_at >= $1 - 29),
                    count(distinct user_id) filter (where created_at >= $1 - 29),
                    count(*)
             from %I', parts[i][2])
        into n_week, n_month, n_people, n_total using p_today;
        features := features || jsonb_build_object(
            'key', parts[i][1], 'week', n_week, 'month', n_month, 'people_month', n_people, 'total', n_total);
    end loop;

    -- What costs money, by day, from the daily limits (kept a week).
    if to_regclass('public.usage_days') is not null then
        select coalesce(jsonb_agg(jsonb_build_object(
                   'day', day, 'kind', kind, 'uses', uses, 'people', people_n, 'guests', guests) order by day desc, kind), '[]')
        into usage
        from (
            select day, kind, sum(count) as uses,
                   count(*) filter (where subject not like 'guest:%') as people_n,
                   count(*) filter (where subject like 'guest:%') as guests
            from usage_days
            where subject <> '*' and day > p_today - 7
            group by day, kind
        ) t;
        -- Spend is kept in tenths of a cent.
        select coalesce(jsonb_agg(jsonb_build_object('day', day, 'usd', round(count / 1000.0, 2)) order by day desc), '[]')
        into spend
        from usage_days where subject = '*' and kind = 'spend' and day > p_today - 7;
    end if;

    return jsonb_build_object(
        'accounts',      (select count(*) from auth.users),
        'joined_week',   (select count(*) from auth.users where created_at >= p_today - 6),
        'joined_month',  (select count(*) from auth.users where created_at >= p_today - 29),
        'active_today',  (select count(*) from user_activity where day = p_today),
        'active_week',   (select count(distinct user_id) from user_activity where day > p_today - 7),
        'active_month',  (select count(distinct user_id) from user_activity where day > p_today - 30),
        'days', (
            select jsonb_agg(jsonb_build_object(
                       'day', d::date,
                       'active', (select count(*) from user_activity a where a.day = d::date),
                       'joined', (select count(*) from auth.users u where u.created_at::date = d::date))
                   order by d)
            from generate_series(p_today - 29, p_today, interval '1 day') d
        ),
        'features', features,
        'usage', usage,
        'spend', spend
    );
end;
$$;

-- Counts for the desk only, through the server's service role.
revoke all on function admin_numbers(date) from public, anon, authenticated;
grant execute on function admin_numbers(date) to service_role;

-- Counting a day's visitors reads user_activity by day.
create index if not exists user_activity_day_idx on user_activity (day);
