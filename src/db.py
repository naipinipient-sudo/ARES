"""Supabase access: job-run bookkeeping, watchlist CRUD, audit log.
Imported by src/jobs.py, src/telegram_bot.py, src/main.py."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
from typing import Any, Iterable

from supabase import Client, create_client

from src.config import Config


@lru_cache(maxsize=1)
def get_client(cfg: Config) -> Client:
    return create_client(cfg.supabase_url, cfg.supabase_service_role_key)


def record_job_run(client: Client, job_name: str, error: str | None = None) -> None:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    row: dict[str, Any] = {"job_name": job_name, "status": "error" if error else "ok", "updated_at": now}
    if error:
        row["last_error"] = error
    else:
        row["last_success_at"] = now
    client.table("job_runs").upsert(row, on_conflict="job_name").execute()


def get_job_runs(client: Client) -> dict[str, dict[str, Any]]:
    res = client.table("job_runs").select("*").execute()
    return {row["job_name"]: row for row in res.data}


def upsert_rows(client: Client, table: str, rows: Iterable[dict[str, Any]], on_conflict: str) -> None:
    rows = list(rows)
    if rows:
        client.table(table).upsert(rows, on_conflict=on_conflict).execute()


def get_watchlist(client: Client, mode: str | None = None) -> list[dict[str, Any]]:
    query = client.table("watchlist").select("*")
    if mode:
        query = query.eq("mode", mode)
    return query.execute().data


def get_open_position_symbols(client: Client) -> set[str]:
    """Used by job0 to never drop a watchlist symbol that still has an open
    position, read from the latest account snapshot (job11)."""
    res = client.table("account_snapshots").select("positions").order("ts", desc=True).limit(1).execute()
    if not res.data:
        return set()
    positions = res.data[0].get("positions") or []
    return {p["symbol"] for p in positions if float(p.get("contracts") or 0) != 0}


def upsert_watchlist_entry(client: Client, symbol: str, tier: str, mode: str = "pantau") -> dict[str, Any]:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    row = {"symbol": symbol, "tier": tier, "mode": mode, "updated_at": now}
    client.table("watchlist").upsert(row, on_conflict="symbol").execute()
    return row


def remove_watchlist_entry(client: Client, symbol: str) -> None:
    client.table("watchlist").delete().eq("symbol", symbol).execute()


def log_audit(client: Client, actor: str, action: str, target: str, old_value: Any = None, new_value: Any = None) -> None:
    client.table("audit_log").insert(
        {"actor": actor, "action": action, "target": target, "old_value": old_value, "new_value": new_value}
    ).execute()
