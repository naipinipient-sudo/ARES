-- Fase 2: mesin saran output + rapor sinyal tracking (PRD job 12).

create table if not exists signals (
  id bigint generated always as identity primary key,
  symbol text not null,
  tier text not null,
  direction text not null check (direction in ('long', 'short')),
  setup text not null,
  score int not null default 0,
  entry numeric not null,
  sl numeric not null,
  tp1 numeric not null,
  tp2 numeric not null,
  rrr numeric not null,
  qty numeric not null,
  leverage int not null,
  margin numeric not null,
  risk_usdt numeric not null,
  risk_pct numeric not null,
  liquidation_price numeric not null,
  reasons text,
  status text not null default 'sent' check (status in ('sent', 'hit_tp1', 'hit_tp2', 'hit_sl', 'invalidated', 'expired')),
  rule_version int not null default 1,
  account_open_positions int,
  account_daily_loss_pct numeric,
  price_1h numeric,
  price_4h numeric,
  price_24h numeric,
  created_at timestamptz not null default now()
);

create index if not exists idx_signals_created_at on signals (created_at desc);
create index if not exists idx_signals_symbol on signals (symbol);
