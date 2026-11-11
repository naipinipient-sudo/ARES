"""Telegram command handlers: /watch, /unwatch, /mode, /list. Owner-chat-only
(PRD: 'Bot hanya merespons chat ID pemilik'). Built and polled from src/main.py."""
from __future__ import annotations

import logging
from functools import wraps
from typing import Any, Callable

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src import binance_client as bx
from src import db
from src.config import Config

logger = logging.getLogger(__name__)


def find_market_symbol(markets: dict[str, Any], base: str) -> str | None:
    """Pure function: resolves a short ticker like 'WLD' to ccxt's unified
    USDT-margined perpetual symbol, e.g. 'WLD/USDT:USDT'."""
    base = base.upper()
    for symbol, market in markets.items():
        if market.get("base") == base and market.get("quote") == "USDT" and market.get("swap") and market.get("linear"):
            return symbol
    return None


def validate_and_add_symbol(cfg: Config, client, base: str, requested_tier: str | None) -> tuple[bool, str]:
    """Shared by /watch. Returns (ok, message-to-send). Always logs audit on
    success. Validation rules per PRD 'Watchlist pilihan pemilik'."""
    exchange = bx.get_exchange(cfg)
    symbol = find_market_symbol(exchange.markets, base)
    if not symbol:
        return False, f"{base} tidak ditemukan di Binance futures USDⓈ-M."

    tickers = bx.fetch_usdm_tickers(exchange)
    volume = tickers.get(symbol, {}).get("volume_24h_usd", 0.0)
    onboard = bx.get_onboard_date_ms(exchange, symbol)
    old_enough = bx.is_listing_old_enough(onboard)
    auto_tier = bx.classify_tier(volume)

    warnings = []
    tier = requested_tier or auto_tier
    if auto_tier is None or not old_enough:
        warnings.append("volume di bawah ambang tier atau listing < 30 hari — otomatis di tier meme kecuali diganti")
        tier = requested_tier or "meme"

    db.upsert_watchlist_entry(client, symbol, tier)
    db.log_audit(client, "telegram_owner", "watch", symbol, new_value={"tier": tier})

    msg = f"{symbol} ditambahkan ke watchlist, tier={tier}, mode=pantau."
    if warnings:
        msg += "\n⚠ " + "; ".join(warnings)
    return True, msg


def owner_only(func: Callable) -> Callable:
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        cfg: Config = context.bot_data["cfg"]
        chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        if chat_id != cfg.telegram_owner_chat_id:
            logger.warning("ignored message from non-owner chat_id=%s", chat_id)
            return
        return await func(update, context)

    return wrapper


@owner_only
async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: Config = context.bot_data["cfg"]
    client = context.bot_data["client"]
    if not context.args:
        await update.message.reply_text("Pakai: /watch SYMBOL [tier]")
        return
    base = context.args[0]
    tier = context.args[1].lower() if len(context.args) > 1 else None
    if tier and tier not in ("inti", "alt", "meme"):
        await update.message.reply_text("Tier harus salah satu: inti, alt, meme.")
        return
    _ok, msg = validate_and_add_symbol(cfg, client, base, tier)
    await update.message.reply_text(msg)


@owner_only
async def cmd_unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = context.bot_data["client"]
    if not context.args:
        await update.message.reply_text("Pakai: /unwatch SYMBOL")
        return
    base = context.args[0].upper()
    cfg: Config = context.bot_data["cfg"]
    exchange = bx.get_exchange(cfg)
    symbol = find_market_symbol(exchange.markets, base) or base
    if symbol in db.get_open_position_symbols(client):
        await update.message.reply_text(f"{symbol} masih punya posisi terbuka, tidak bisa di-unwatch.")
        return
    db.remove_watchlist_entry(client, symbol)
    db.log_audit(client, "telegram_owner", "unwatch", symbol)
    await update.message.reply_text(f"{symbol} dikeluarkan dari watchlist.")


@owner_only
async def cmd_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = context.bot_data["client"]
    if len(context.args) < 2 or context.args[1].lower() not in ("saran", "pantau"):
        await update.message.reply_text("Pakai: /mode SYMBOL saran|pantau")
        return
    cfg: Config = context.bot_data["cfg"]
    exchange = bx.get_exchange(cfg)
    base = context.args[0].upper()
    symbol = find_market_symbol(exchange.markets, base) or base
    mode = context.args[1].lower()
    rows = [row for row in db.get_watchlist(client) if row["symbol"] == symbol]
    if not rows:
        await update.message.reply_text(f"{symbol} belum ada di watchlist.")
        return
    db.upsert_watchlist_entry(client, symbol, rows[0]["tier"], mode)
    db.log_audit(client, "telegram_owner", "mode_change", symbol, old_value=rows[0]["mode"], new_value=mode)
    await update.message.reply_text(f"{symbol} diubah ke mode {mode}.")


@owner_only
async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    client = context.bot_data["client"]
    rows = db.get_watchlist(client)
    if not rows:
        await update.message.reply_text("Watchlist kosong.")
        return
    lines = [f"{r['symbol']} — tier={r['tier']} mode={r['mode']}" for r in sorted(rows, key=lambda r: r["symbol"])]
    await update.message.reply_text("\n".join(lines))


def build_application(cfg: Config, client) -> Application:
    app = Application.builder().token(cfg.telegram_bot_token).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["client"] = client
    app.add_handler(CommandHandler("watch", cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("mode", cmd_mode))
    app.add_handler(CommandHandler("list", cmd_list))
    return app


async def send_to_owner(app: Application, cfg: Config, text: str) -> None:
    await app.bot.send_message(chat_id=cfg.telegram_owner_chat_id, text=text)
