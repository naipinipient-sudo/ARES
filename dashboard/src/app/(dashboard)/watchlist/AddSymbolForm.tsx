"use client";

import { useActionState } from "react";
import { addWatchlistSymbol, type AddState } from "./actions";

const initialState: AddState = { error: null };

export function AddSymbolForm() {
  const [state, formAction, pending] = useActionState(addWatchlistSymbol, initialState);

  return (
    <form action={formAction} className="add-form">
      <input name="symbol" placeholder="BTC" disabled={pending} required />
      <select name="tier" defaultValue="" disabled={pending} required>
        <option value="" disabled>
          tier
        </option>
        <option value="inti">inti</option>
        <option value="alt">alt</option>
        <option value="meme">meme</option>
      </select>
      <button type="submit" disabled={pending}>
        {pending ? "Menambah…" : "Tambah"}
      </button>
      {state.error && <span className="inline-error">{state.error}</span>}
    </form>
  );
}
