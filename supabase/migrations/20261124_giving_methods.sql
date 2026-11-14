-- Ways to give (app/support.py): PayPal, Venmo, Cash App, Zelle or anything
-- else, set from the Giving tab on the admin desk (#desk) and shown to
-- everyone on the Support page (#support). Stripe's links stay in .env.
--
-- Everything in a row is public, since the Support page shows it to anyone:
-- a link, a handle, a short note. Never a password, an API key or anything
-- that lets someone take money out.
--
-- Run once, after the others, in the Supabase SQL editor. Until it runs, the
-- Support page shows Stripe's links (or "giving opens soon") and the Giving
-- tab says what to run.

create table if not exists giving_methods (
    id          uuid primary key default gen_random_uuid(),
    kind        text not null check (kind in ('paypal', 'venmo', 'cashapp', 'zelle', 'other')),
    label       text check (char_length(label) <= 40),     -- the name shown; "other" needs one
    handle      text check (char_length(handle) <= 80),    -- @name, $cashtag, or Zelle's email or phone
    url         text check (char_length(url) <= 500),      -- a link to give through, http(s) only
    note        text check (char_length(note) <= 200),     -- one line under it ("Put 'Adullam' in the memo")
    monthly     boolean not null default false,            -- the link sets up a monthly gift
    enabled     boolean not null default true,
    position    integer not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists giving_methods_order_idx on giving_methods (position, created_at);

-- No policies: only the server's service role reads or writes this table.
alter table giving_methods enable row level security;
