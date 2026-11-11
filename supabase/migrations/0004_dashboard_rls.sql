-- Fase 2 dashboard: row level security for the tables the dashboard reads/writes.
-- The bot (src/db.py) connects with the service_role key, which bypasses RLS
-- entirely, so none of this affects the bot.
--
-- ponytail: this is a single-user app (Supabase Auth for one owner account),
-- so "scoped to that one user" is enforced by disabling public sign-ups in
-- the Supabase dashboard (Authentication -> Providers -> Email -> disable
-- "Allow new users to sign up") rather than hardcoding the owner's user id
-- here. If a second account is ever added, switch these policies to
-- `auth.uid() = '<owner-uuid>'::uuid` instead.

alter table watchlist enable row level security;
alter table job_runs enable row level security;
alter table market_snapshots enable row level security;
alter table derivatives_pulse enable row level security;
alter table account_snapshots enable row level security;
alter table signals enable row level security;
alter table audit_log enable row level security;

create policy "dashboard owner read watchlist" on watchlist for select to authenticated using (true);
create policy "dashboard owner write watchlist" on watchlist for insert to authenticated with check (true);
create policy "dashboard owner update watchlist" on watchlist for update to authenticated using (true) with check (true);
create policy "dashboard owner delete watchlist" on watchlist for delete to authenticated using (true);

create policy "dashboard owner read job_runs" on job_runs for select to authenticated using (true);
create policy "dashboard owner read market_snapshots" on market_snapshots for select to authenticated using (true);
create policy "dashboard owner read derivatives_pulse" on derivatives_pulse for select to authenticated using (true);
create policy "dashboard owner read account_snapshots" on account_snapshots for select to authenticated using (true);
create policy "dashboard owner read signals" on signals for select to authenticated using (true);

create policy "dashboard owner read audit_log" on audit_log for select to authenticated using (true);
create policy "dashboard owner write audit_log" on audit_log for insert to authenticated with check (true);
