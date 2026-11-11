// Row shapes, trimmed to the columns the dashboard actually reads. Keep in
// sync by hand with supabase/migrations/0001_init.sql and 0002_signals.sql.

export type Tier = "inti" | "alt" | "meme";
export type Mode = "saran" | "pantau";

export type WatchlistRow = {
  symbol: string;
  tier: Tier;
  mode: Mode;
  added_at: string;
  updated_at: string;
};

export type AccountPosition = {
  symbol: string;
  side: string | null;
  contracts: number | null;
  entryPrice: number | null;
  unrealizedPnl: number | null;
  liquidationPrice: number | null;
};

export type AccountSnapshotRow = {
  ts: string;
  total_balance: number | null;
  available_balance: number | null;
  used_margin: number | null;
  unrealized_pnl: number | null;
  positions: AccountPosition[] | null;
};

export type MarketSnapshotRow = {
  symbol: string;
  timeframe: "1h" | "4h";
  ts: string;
  close: number | null;
  ema200: number | null;
};

export type DerivativesPulseRow = {
  symbol: string;
  ts: string;
  funding_rate: number | null;
  oi_change_pct: number | null;
};

export type SignalStatus =
  | "sent"
  | "hit_tp1"
  | "hit_tp2"
  | "hit_sl"
  | "invalidated"
  | "expired";

export type SignalRow = {
  id: number;
  symbol: string;
  tier: string;
  direction: "long" | "short";
  setup: string;
  score: number;
  sl: number;
  tp1: number;
  tp2: number;
  status: SignalStatus;
  created_at: string;
};

// Latest-first rows (ordered by ts/created_at desc) -> one row per symbol.
export function latestBySymbol<T extends { symbol: string }>(
  rows: T[] | null | undefined,
): Map<string, T> {
  const map = new Map<string, T>();
  for (const row of rows ?? []) {
    if (!map.has(row.symbol)) map.set(row.symbol, row);
  }
  return map;
}
