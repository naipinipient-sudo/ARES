-- Phase 1 foundation schema: watchlist, data jobs 0/1/2/5/7/10/11, health, daily brief.

create table if not exists watchlist (
  symbol text primary key,
  tier text not null check (tier in ('inti', 'alt', 'meme')),
  mode text not null default 'pantau' check (mode in ('saran', 'pantau')),
  added_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists audit_log (
  id bigint generated always as identity primary key,
  actor text not null,
  action text not null,
  target text,
  old_value jsonb,
  new_value jsonb,
  created_at timestamptz not null default now()
);

create table if not exists job_runs (
  job_name text primary key,
  status text not null check (status in ('ok', 'error')),
  last_success_at timestamptz,
  last_error text,
  updated_at timestamptz not null default now()
);

create table if not exists universe_proposals (
  symbol text primary key,
  suggested_tier text not null,
  volume_24h_usd numeric not null,
  proposed_at timestamptz not null default now(),
  status text not null default 'pending' check (status in ('pending', 'accepted', 'dismissed'))
);

create table if not exists market_snapshots (
  symbol text not null,
  timeframe text not null check (timeframe in ('1h', '4h')),
  ts timestamptz not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  volume numeric,
  ema50 numeric,
  ema200 numeric,
  rsi numeric,
  atr numeric,
  structure text,
  primary key (symbol, timeframe, ts)
);

create table if not exists derivatives_pulse (
  symbol text not null,
  ts timestamptz not null,
  funding_rate numeric,
  open_interest numeric,
  oi_change_pct numeric,
  long_short_account_ratio numeric,
  taker_long_short_ratio numeric,
  funding_extreme boolean not null default false,
  primary key (symbol, ts)
);

create table if not exists news_items (
  id bigint generated always as identity primary key,
  source text not null,
  title text not null,
  link text not null unique,
  summary text,
  published_at timestamptz,
  label_asset text,
  label_direction text,
  label_surprise text,
  fetched_at timestamptz not null default now()
);

create table if not exists macro_snapshots (
  ts timestamptz primary key default now(),
  dgs10 numeric,
  dtwexbgs numeric,
  fear_greed int,
  stablecoin_supply_usd numeric
);

create table if not exists events_calendar (
  id bigint generated always as identity primary key,
  name text not null,
  category text not null,
  event_time timestamptz not null,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists account_snapshots (
  ts timestamptz primary key default now(),
  total_balance numeric,
  available_balance numeric,
  used_margin numeric,
  unrealized_pnl numeric,
  positions jsonb
);

create table if not exists daily_briefs (
  brief_date date primary key,
  content text not null,
  sent_at timestamptz
);

create index if not exists idx_market_snapshots_symbol_ts on market_snapshots (symbol, ts desc);
create index if not exists idx_derivatives_pulse_symbol_ts on derivatives_pulse (symbol, ts desc);
create index if not exists idx_news_items_published_at on news_items (published_at desc);
create index if not exists idx_events_calendar_event_time on events_calendar (event_time);
