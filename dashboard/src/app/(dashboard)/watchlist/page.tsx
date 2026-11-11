import { createClient } from "@/lib/supabase/server";
import { formatDateTime, formatPct, formatPrice } from "@/lib/format";
import {
  latestBySymbol,
  type AccountPosition,
  type AccountSnapshotRow,
  type DerivativesPulseRow,
  type MarketSnapshotRow,
  type SignalRow,
  type WatchlistRow,
} from "@/lib/types";
import { AddSymbolForm } from "./AddSymbolForm";
import { WatchlistRowControls } from "./WatchlistRowControls";

export default async function WatchlistPage() {
  const supabase = await createClient();

  const [watchlistRes, pricesRes, pulseRes, signalsRes, snapRes] = await Promise.all([
    supabase.from("watchlist").select("*").order("symbol"),
    supabase
      .from("market_snapshots")
      .select("symbol,timeframe,ts,close")
      .eq("timeframe", "1h")
      .order("ts", { ascending: false })
      .limit(200),
    supabase
      .from("derivatives_pulse")
      .select("symbol,ts,funding_rate,oi_change_pct")
      .order("ts", { ascending: false })
      .limit(200),
    supabase.from("signals").select("*").order("created_at", { ascending: false }).limit(200),
    supabase.from("account_snapshots").select("positions").order("ts", { ascending: false }).limit(1).maybeSingle(),
  ]);

  const watchlist = (watchlistRes.data as WatchlistRow[] | null) ?? [];
  const priceBySymbol = latestBySymbol(pricesRes.data as MarketSnapshotRow[] | null);
  const pulseBySymbol = latestBySymbol(pulseRes.data as DerivativesPulseRow[] | null);
  const signalBySymbol = latestBySymbol(signalsRes.data as SignalRow[] | null);

  const positions = ((snapRes.data as Pick<AccountSnapshotRow, "positions"> | null)?.positions ??
    []) as AccountPosition[];
  const openSymbols = new Set(
    positions.filter((p) => Number(p.contracts ?? 0) !== 0).map((p) => p.symbol),
  );

  return (
    <section className="panel">
      <h2>Watchlist</h2>
      <AddSymbolForm />
      <table>
        <thead>
          <tr>
            <th>Pair</th>
            <th>Tier</th>
            <th>Mode</th>
            <th>Harga</th>
            <th>Funding</th>
            <th>Perubahan OI</th>
            <th>Sinyal terakhir</th>
            <th>Kontrol</th>
          </tr>
        </thead>
        <tbody>
          {watchlist.map((w) => {
            const price = priceBySymbol.get(w.symbol);
            const pulse = pulseBySymbol.get(w.symbol);
            const signal = signalBySymbol.get(w.symbol);
            return (
              <tr key={w.symbol}>
                <td>{w.symbol}</td>
                <td>{w.tier}</td>
                <td>{w.mode}</td>
                <td>{formatPrice(price?.close)}</td>
                <td>{formatPct(pulse?.funding_rate != null ? pulse.funding_rate * 100 : null)}</td>
                <td>{formatPct(pulse?.oi_change_pct)}</td>
                <td>
                  {signal
                    ? `${signal.direction} skor ${signal.score}/3 (${signal.status}) · ${formatDateTime(signal.created_at)}`
                    : "–"}
                </td>
                <td>
                  <WatchlistRowControls
                    symbol={w.symbol}
                    tier={w.tier}
                    mode={w.mode}
                    hasOpenPosition={openSymbols.has(w.symbol)}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
