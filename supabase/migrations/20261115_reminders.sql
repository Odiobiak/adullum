-- Reminders and push notifications (app/reminders.py, app/push.py,
-- web/notify.js, web/sw.js).
--
-- Run once in the Supabase SQL editor, after 20261114_churches.sql. Safe to
-- run again.
--
-- `push_subscriptions` is one row per device that has said yes to
-- notifications: the browser's push endpoint and its two keys. A device that
-- signs out, or that the push service says is gone, is deleted.
--
-- `reminders` is one row per thing the person asked to be reminded of, keyed
-- by what it's about (`key`, e.g. 'event:<church id>:2026-11-21:youth-conference'),
-- so pressing the bell again changes the same reminder instead of adding
-- another. `repeat` is set for a weekly gathering ({day, time, zone, before}):
-- once sent, the reminder moves to the next week instead of being done.
-- `url` is a place inside Adullum ('#church/c/<id>'), opened when the
-- notification is tapped.

create table if not exists push_subscriptions (
    endpoint    text primary key,
    user_id     uuid not null references auth.users(id) on delete cascade,
    p256dh      text not null,
    auth        text not null,
    created_at  timestamptz not null default now()
);
create index if not exists push_subscriptions_user_idx on push_subscriptions (user_id);

create table if not exists reminders (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid not null references auth.users(id) on delete cascade,
    key         text not null,
    title       text not null,
    body        text,
    url         text,
    remind_at   timestamptz not null,
    repeat      jsonb,
    sent_at     timestamptz,
    created_at  timestamptz not null default now(),
    unique (user_id, key)
);
create index if not exists reminders_due_idx on reminders (remind_at) where sent_at is null;

-- "Tell me when it's live": the last live video a person was told about, so
-- one service is announced once.
alter table churches add column if not exists last_live_video text;

alter table push_subscriptions enable row level security;
drop policy if exists "users manage their own devices" on push_subscriptions;
create policy "users manage their own devices" on push_subscriptions
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

alter table reminders enable row level security;
drop policy if exists "users manage their own reminders" on reminders;
create policy "users manage their own reminders" on reminders
    for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
