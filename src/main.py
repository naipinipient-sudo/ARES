"""Entrypoint: validates config, wires APScheduler jobs + the Telegram bot
into one asyncio event loop, runs forever. `python -m src.main` / Docker CMD."""
from __future__ import annotations

import asyncio
import logging

from apscheduler.events import EVENT_JOB_ERROR
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src import db, jobs, signal_engine, telegram_bot
from src.config import load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def health_check_tick(app, cfg, client) -> None:
    stale = jobs.run_health_check(client)
    if stale:
        await telegram_bot.send_to_owner(app, cfg, "⚠ Data basi, saran berhenti untuk: " + ", ".join(stale))
    jobs.ping_heartbeat(cfg)


async def daily_brief_tick(app, cfg, client) -> None:
    content = jobs.compose_daily_brief(cfg, client)
    await telegram_bot.send_to_owner(app, cfg, content)


# Core jobs the signal engine refuses to run on top of if they've gone stale
# (PRD "nol saran dari data basi" applied specifically to card generation).
SIGNAL_BLOCKING_JOBS = {"job1_market_snapshot", "job2_derivatives_pulse"}


async def generate_signals_tick(app, cfg, client) -> None:
    stale = set(jobs.run_health_check(client))
    if stale & SIGNAL_BLOCKING_JOBS:
        logger.warning("skipping signal generation: stale jobs %s", stale & SIGNAL_BLOCKING_JOBS)
        return
    for card in signal_engine.generate_signals_job(cfg, client):
        await telegram_bot.send_to_owner(app, cfg, signal_engine.format_signal_card(card))


def build_scheduler(app, cfg, client) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(jobs.job0_select_universe, "cron", args=[cfg, client], hour=23, minute=0, id="job0_universe")
    scheduler.add_job(jobs.job1_market_snapshot, "cron", args=[cfg, client], minute=1, id="job1_market_snapshot")
    scheduler.add_job(jobs.job2_derivatives_pulse, "interval", args=[cfg, client], minutes=15, id="job2_derivatives_pulse")
    scheduler.add_job(jobs.job5_news_scanner, "interval", args=[cfg, client], minutes=15, id="job5_news")
    scheduler.add_job(jobs.job7_macro_sentiment, "cron", args=[cfg, client], hour=23, minute=50, id="job7_macro")
    scheduler.add_job(jobs.job11_account_snapshot, "interval", args=[cfg, client], seconds=30, id="job11_account")
    scheduler.add_job(jobs.job12_track_signal_outcomes, "interval", args=[cfg, client], hours=1, id="job12_signal_outcomes")
    scheduler.add_job(
        lambda: asyncio.ensure_future(generate_signals_tick(app, cfg, client)),
        "cron",
        minute=2,
        id="generate_signals",
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(health_check_tick(app, cfg, client)),
        "interval",
        minutes=5,
        id="health_check",
    )
    scheduler.add_job(
        lambda: asyncio.ensure_future(daily_brief_tick(app, cfg, client)),
        "cron",
        hour=0,
        minute=0,
        id="daily_brief",
    )

    def on_job_error(event) -> None:
        logger.error("job %s raised: %s", event.job_id, event.exception)
        asyncio.ensure_future(telegram_bot.send_to_owner(app, cfg, f"❌ Job {event.job_id} gagal: {event.exception}"))

    scheduler.add_listener(on_job_error, EVENT_JOB_ERROR)
    return scheduler


async def main() -> None:
    cfg = load_config()
    client = db.get_client(cfg)
    app = telegram_bot.build_application(cfg, client)
    scheduler = build_scheduler(app, cfg, client)
    scheduler.start()

    async with app:
        await app.start()
        await app.updater.start_polling()
        logger.info("bot running")
        try:
            await asyncio.Event().wait()
        finally:
            scheduler.shutdown(wait=False)
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__":
    asyncio.run(main())
