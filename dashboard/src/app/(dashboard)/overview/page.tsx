import { createClient } from "@/lib/supabase/server";
import { computeJobHealth, type JobRunRow } from "@/lib/jobs";
import { wibDayStartUtc, wibWeekStartUtc, dailyLossPct } from "@/lib/risk";
import { formatUsdt, formatPct, formatPrice } from "@/lib/format";
import {
  latestBySymbol,
  type AccountPosition,
  type AccountSnapshotRow,
  type MarketSnapshotRow,
  type SignalRow,
  type WatchlistRow,
} from "@/lib/types";

// Display-only comparison — the dashboard never enforces risk limits, the
// bot's src/risk.py (validated against src/config.py's MAX_DAILY_LOSS_PCT
// ceiling) is the only thing that gates a trade.
const DAILY_LOSS_LIMIT_PCT = Number(process.env.NEXT_PUBLIC_DAILY_LOSS_LIMIT_PCT ?? "3");

function regimeLabel(ema200: number | null | undefined, close: number | null | undefined): string {
  if (ema200 == null || close == null) return "?";
  return close > ema200 ? "bullish" : "bearish";
}

function pctDistance(current: number | null | undefined, target: number | null | undefined): number | null {
  if (current == null || target == null || current === 0) return null;
  return (Math.abs(current - target) / current) * 100;
}

export default async function OverviewPage() {
  const supabase = await createClient();
  const now = new Date();
  const dayStartIso = wibDayStartUtc(now).toISOString();
  const weekStartIso = wibWeekStartUtc(now).toISOString();

  const [
    latest,
    dayStart,
    weekStart,
    watchlistRes,
    jobRunsRes,
    snaps4hRes,
    snaps1hRes,
    activeSignalsRes,
  ] = await Promise.all([
    supabase.from("account_snapshots").select("*").order("ts", { ascending: false }).limit(1).maybeSingle(),
    supabase
      .from("account_snapshots")
      .select("ts,total_balance")
      .gte("ts", dayStartIso)
      .order("ts", { ascending: true })
      .limit(1)
      .maybeSingle(),
    supabase
      .from("account_snapshots")
      .select("ts,total_balance")
      .gte("ts", weekStartIso)
      .order("ts", { ascending: true })
      .limit(1)
      .maybeSingle(),
    supabase.from("watchlist").select("*").order("symbol"),
    supabase.from("job_runs").select("*"),
    supabase
      .from("market_snapshots")
      .select("symbol,timeframe,ts,close,ema200")
      .eq("timeframe", "4h")
      .order("ts", { ascending: false })
      .limit(200),
    supabase
      .from("market_snapshots")
      .select("symbol,timeframe,ts,close")
      .eq("timeframe", "1h")
      .order("ts", { ascending: false })
      .limit(200),
    supabase
      .from("signals")
      .select("*")
      .in("status", ["sent", "hit_tp1"])
      .order("created_at", { ascending: false })
      .limit(200),
  ]);

  const latestSnap = latest.data as AccountSnapshotRow | null;
  const balanceNow = latestSnap?.total_balance ?? null;
  const balanceDayStart = (dayStart.data as { total_balance: number | null } | null)?.total_balance ?? null;
  const balanceWeekStart = (weekStart.data as { total_balance: number | null } | null)?.total_balance ?? null;

  const pnlToday = balanceNow != null && balanceDayStart != null ? balanceNow - balanceDayStart : null;
  const pnlWeek = balanceNow != null && balanceWeekStart != null ? balanceNow - balanceWeekStart : null;
  const riskUsedPct =
    balanceNow != null && balanceDayStart != null ? dailyLossPct(balanceDayStart, balanceNow) : null;

  const watchlist = (watchlistRes.data as WatchlistRow[] | null) ?? [];
  const health = computeJobHealth((jobRunsRes.data as JobRunRow[]) ?? []);
  const anyStale = health.some((h) => h.stale);
  const anyError = health.some((h) => h.status === "error");
  const systemLight = anyStale ? "merah" : anyError ? "kuning" : "hijau";

  const regimeBySymbol = latestBySymbol(snaps4hRes.data as MarketSnapshotRow[] | null);
  const priceBySymbol = latestBySymbol(snaps1hRes.data as MarketSnapshotRow[] | null);
  const signalBySymbol = latestBySymbol(activeSignalsRes.data as SignalRow[] | null);

  const positions = ((latestSnap?.positions as AccountPosition[] | null) ?? []).filter(
    (p) => Number(p.contracts ?? 0) !== 0,
  );

  return (
    <>
      <section className="panel">
        <h2>Saldo &amp; PnL</h2>
        <div className="stat-grid">
          <div className="stat">
            <span className="label">Saldo total</span>
            <span className="value">{formatUsdt(balanceNow)}</span>
          </div>
          <div className="stat">
            <span className="label">Tersedia</span>
            <span className="value">{formatUsdt(latestSnap?.available_balance)}</span>
          </div>
          <div className="stat">
            <span className="label">Margin terpakai</span>
            <span className="value">{formatUsdt(latestSnap?.used_margin)}</span>
          </div>
          <div className="stat">
            <span className="label">PnL belum terealisasi</span>
            <span className="value">{formatUsdt(latestSnap?.unrealized_pnl)}</span>
          </div>
          <div className="stat">
            <span className="label">PnL hari ini</span>
            <span className="value">{formatUsdt(pnlToday)}</span>
          </div>
          <div className="stat">
            <span className="label">PnL minggu ini</span>
            <span className="value">{formatUsdt(pnlWeek)}</span>
          </div>
          <div className="stat">
            <span className="label">Risiko harian terpakai</span>
            <span className="value">
              {formatPct(riskUsedPct)} / {formatPct(DAILY_LOSS_LIMIT_PCT, 0)}
            </span>
          </div>
          <div className="stat">
            <span className="label">Status sistem</span>
            <span className={`value light ${systemLight}`}>{systemLight}</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Posisi terbuka</h2>
        {positions.length === 0 ? (
          <p>Tidak ada posisi terbuka.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Sisi</th>
                <th>Entry</th>
                <th>Harga sekarang</th>
                <th>PnL</th>
                <th>Jarak ke SL</th>
                <th>Jarak ke TP1</th>
                <th>Jarak ke TP2</th>
                <th>Jarak ke likuidasi</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const currentPrice = priceBySymbol.get(p.symbol)?.close ?? p.entryPrice ?? null;
                const signal = signalBySymbol.get(p.symbol);
                return (
                  <tr key={p.symbol}>
                    <td>{p.symbol}</td>
                    <td>{p.side ?? "–"}</td>
                    <td>{formatPrice(p.entryPrice)}</td>
                    <td>{formatPrice(currentPrice)}</td>
                    <td>{formatUsdt(p.unrealizedPnl)}</td>
                    <td>{formatPct(pctDistance(currentPrice, signal?.sl))}</td>
                    <td>{formatPct(pctDistance(currentPrice, signal?.tp1))}</td>
                    <td>{formatPct(pctDistance(currentPrice, signal?.tp2))}</td>
                    <td>{formatPct(pctDistance(currentPrice, p.liquidationPrice))}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Rezim pasar (4H, harga vs EMA200)</h2>
        {watchlist.length === 0 ? (
          <p>Watchlist kosong.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th>Rezim</th>
              </tr>
            </thead>
            <tbody>
              {watchlist.map((w) => {
                const snap = regimeBySymbol.get(w.symbol);
                return (
                  <tr key={w.symbol}>
                    <td>{w.symbol}</td>
                    <td>{regimeLabel(snap?.ema200, snap?.close)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}
