"use client";

import { useActionState } from "react";
import { signIn, type LoginState } from "./actions";

const initialState: LoginState = { error: null };

export default function LoginPage() {
  const [state, formAction, pending] = useActionState(signIn, initialState);

  return (
    <main className="login-page">
      <form action={formAction} className="login-form">
        <h1>ARES Dashboard</h1>
        <label>
          Email
          <input type="email" name="email" required disabled={pending} autoFocus />
        </label>
        <label>
          Password
          <input type="password" name="password" required disabled={pending} />
        </label>
        <button type="submit" disabled={pending}>
          {pending ? "Masuk…" : "Masuk"}
        </button>
        {state.error && <p className="form-error">{state.error}</p>}
      </form>
    </main>
  );
}
