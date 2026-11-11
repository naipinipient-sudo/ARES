"use server";

import { revalidatePath } from "next/cache";
import { createClient } from "@/lib/supabase/server";
import type { AccountPosition, AccountSnapshotRow, Mode, Tier } from "@/lib/types";

const TIERS: readonly Tier[] = ["inti", "alt", "meme"];
const MODES: readonly Mode[] = ["saran", "pantau"];

export type ActionResult = { error: string | null };
export type AddState = ActionResult;

// The dashboard never calls Binance (PRD: "tidak pernah memegang API key
// Binance"), so unlike the bot's /watch it can't look up the real ccxt
// market symbol or auto-detect tier from volume. The owner types the base
// ticker and picks a tier explicitly; this just shapes it into the same
// "BASE/USDT:USDT" form the bot and the rest of the schema expect.
function toMarketSymbol(raw: string): string {
  const base = raw.trim().toUpperCase();
  return base.includes("/") ? base : `${base}/USDT:USDT`;
}

async function getOpenPositionSymbols(
  supabase: Awaited<ReturnType<typeof createClient>>,
): Promise<Set<string>> {
  const { data } = await supabase
    .from("account_snapshots")
    .select("positions")
    .order("ts", { ascending: false })
    .limit(1)
    .maybeSingle();
  const positions = ((data as Pick<AccountSnapshotRow, "positions"> | null)?.positions ??
    []) as AccountPosition[];
  return new Set(positions.filter((p) => Number(p.contracts ?? 0) !== 0).map((p) => p.symbol));
}

export async function addWatchlistSymbol(_prev: AddState, formData: FormData): Promise<AddState> {
  const rawSymbol = String(formData.get("symbol") ?? "");
  const tier = String(formData.get("tier") ?? "");
  if (!rawSymbol.trim()) {
    return { error: "Simbol wajib diisi." };
  }
  if (!TIERS.includes(tier as Tier)) {
    return { error: "Tier harus salah satu: inti, alt, meme." };
  }

  const symbol = toMarketSymbol(rawSymbol);
  const supabase = await createClient();

  const { error } = await supabase
    .from("watchlist")
    .upsert(
      { symbol, tier, mode: "pantau", updated_at: new Date().toISOString() },
      { onConflict: "symbol" },
    );
  if (error) return { error: error.message };

  await supabase
    .from("audit_log")
    .insert({ actor: "dashboard_owner", action: "watch", target: symbol, new_value: { tier } });

  revalidatePath("/watchlist");
  return { error: null };
}

export async function removeWatchlistSymbol(symbol: string): Promise<ActionResult> {
  const supabase = await createClient();

  const openSymbols = await getOpenPositionSymbols(supabase);
  if (openSymbols.has(symbol)) {
    return { error: `${symbol} masih punya posisi terbuka, tidak bisa di-unwatch.` };
  }

  const { error } = await supabase.from("watchlist").delete().eq("symbol", symbol);
  if (error) return { error: error.message };

  await supabase.from("audit_log").insert({ actor: "dashboard_owner", action: "unwatch", target: symbol });

  revalidatePath("/watchlist");
  return { error: null };
}

export async function changeWatchlistTier(symbol: string, tier: string): Promise<ActionResult> {
  if (!TIERS.includes(tier as Tier)) {
    return { error: "Tier harus salah satu: inti, alt, meme." };
  }

  const supabase = await createClient();
  const { data: current } = await supabase
    .from("watchlist")
    .select("tier")
    .eq("symbol", symbol)
    .maybeSingle();

  const { error } = await supabase
    .from("watchlist")
    .update({ tier, updated_at: new Date().toISOString() })
    .eq("symbol", symbol);
  if (error) return { error: error.message };

  await supabase.from("audit_log").insert({
    actor: "dashboard_owner",
    action: "tier_change",
    target: symbol,
    old_value: (current as { tier: string } | null)?.tier ?? null,
    new_value: tier,
  });

  revalidatePath("/watchlist");
  return { error: null };
}

export async function changeWatchlistMode(symbol: string, mode: string): Promise<ActionResult> {
  if (!MODES.includes(mode as Mode)) {
    return { error: "Mode harus salah satu: saran, pantau." };
  }

  const supabase = await createClient();
  const { data: current } = await supabase
    .from("watchlist")
    .select("mode")
    .eq("symbol", symbol)
    .maybeSingle();

  const { error } = await supabase
    .from("watchlist")
    .update({ mode, updated_at: new Date().toISOString() })
    .eq("symbol", symbol);
  if (error) return { error: error.message };

  await supabase.from("audit_log").insert({
    actor: "dashboard_owner",
    action: "mode_change",
    target: symbol,
    old_value: (current as { mode: string } | null)?.mode ?? null,
    new_value: mode,
  });

  revalidatePath("/watchlist");
  return { error: null };
}
