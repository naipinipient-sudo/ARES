-- Fase 3: backtest results, versioned per rule set (PRD "tersimpan dengan versi aturan").

create table if not exists backtests (
  id bigint generated always as identity primary key,
  symbol text not null,
  tier text not null,
  rule_version int not null,
  "start" timestamptz not null,
  "end" timestamptz not null,
  n_signals int not null,
  win_rate numeric not null,
  expectancy_r numeric not null,
  max_drawdown_r numeric not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_backtests_symbol_version on backtests (symbol, rule_version);
