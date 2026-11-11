"use client";

import { useState, useTransition } from "react";
import {
  changeWatchlistMode,
  changeWatchlistTier,
  removeWatchlistSymbol,
  type ActionResult,
} from "./actions";
import type { Mode, Tier } from "@/lib/types";

export function WatchlistRowControls({
  symbol,
  tier,
  mode,
  hasOpenPosition,
}: {
  symbol: string;
  tier: Tier;
  mode: Mode;
  hasOpenPosition: boolean;
}) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function run(action: () => Promise<ActionResult>) {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result.error) setError(result.error);
    });
  }

  return (
    <div className="watchlist-controls">
      <select
        value={tier}
        disabled={pending}
        onChange={(e) => run(() => changeWatchlistTier(symbol, e.target.value))}
      >
        <option value="inti">inti</option>
        <option value="alt">alt</option>
        <option value="meme">meme</option>
      </select>
      <select
        value={mode}
        disabled={pending}
        onChange={(e) => run(() => changeWatchlistMode(symbol, e.target.value))}
      >
        <option value="saran">saran</option>
        <option value="pantau">pantau</option>
      </select>
      <button
        type="button"
        disabled={pending || hasOpenPosition}
        title={hasOpenPosition ? "Masih punya posisi terbuka" : undefined}
        onClick={() => {
          if (confirm(`Hapus ${symbol} dari watchlist?`)) {
            run(() => removeWatchlistSymbol(symbol));
          }
        }}
      >
        Hapus
      </button>
      {error && <span className="inline-error">{error}</span>}
    </div>
  );
}
