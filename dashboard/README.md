# ARES Dashboard

Fase 2 scope of the PRD's web dashboard: Overview, Kesehatan sistem, Watchlist.
Next.js (App Router) + Supabase Auth, deployed to Vercel. Read-only derived
data plus watchlist edits only — this app never holds a Binance API key and
never talks to Binance directly.

## Setup

1. One-time: create the single owner account in Supabase
   (Authentication -> Users -> Add user), and disable public sign-up
   (Authentication -> Providers -> Email -> "Allow new users to sign up" off).
2. Apply `supabase/migrations/0004_dashboard_rls.sql` (same way as the
   existing migrations) so RLS policies exist for the tables this app reads.
3. Local dev: copy `.env.example` to `.env.local` and fill in the anon key.
4. `npm install && npm run dev`.

## Environment variables (Vercel)

Set these in the Vercel project (Settings -> Environment Variables), for all
environments (Production/Preview/Development):

| Variable | Value | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_SUPABASE_URL` | your Supabase project URL | Same project as the bot. Supabase dashboard -> Project Settings -> API -> Project URL. |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | the **anon/publishable** key | Supabase dashboard -> Project Settings -> API. **Never** the `service_role` key — that one stays only in the bot's own `.env`. |
| `NEXT_PUBLIC_DAILY_LOSS_LIMIT_PCT` | e.g. `3` | Optional. Display-only reference line on Overview; matches `src/config.py`'s `DAILY_LOSS_LIMIT_PCT` default. Not enforced here. |

Both `NEXT_PUBLIC_*` keys are safe to ship to the browser — they're subject
to the Postgres RLS policies in `0004_dashboard_rls.sql`, not a substitute
for them.

## Notes

- Add/remove/tier/mode changes on the Watchlist page write to the same
  `watchlist` table the Telegram bot's `/watch /unwatch /mode` commands use,
  and log the same shape of `audit_log` row.
- Unlike the bot's `/watch`, this page can't call Binance to verify the pair
  or auto-detect its tier (the dashboard is read-only w.r.t. Binance), so the
  owner picks the tier explicitly when adding a symbol.
