"""Env loading + startup validation. Imported by every other src module."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

REQUIRED_VARS = [
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_OWNER_CHAT_ID",
]

# Hard ceilings the owner can never configure above (PRD: "divalidasi risk
# engine terhadap batas atas yang dikunci di config server").
MAX_RISK_PCT = 2.0
MAX_DAILY_LOSS_PCT = 10.0
MAX_LEVERAGE = 5


def _float(name: str, default: str) -> float:
    return float(os.environ.get(name, default))


def _int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


@dataclass
class Config:
    binance_api_key: str = field(default_factory=lambda: os.environ.get("BINANCE_API_KEY", ""))
    binance_api_secret: str = field(default_factory=lambda: os.environ.get("BINANCE_API_SECRET", ""))
    supabase_url: str = field(default_factory=lambda: os.environ.get("SUPABASE_URL", ""))
    supabase_service_role_key: str = field(default_factory=lambda: os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""))
    telegram_bot_token: str = field(default_factory=lambda: os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    telegram_owner_chat_id: str = field(default_factory=lambda: os.environ.get("TELEGRAM_OWNER_CHAT_ID", ""))
    healthchecks_ping_url: str = field(default_factory=lambda: os.environ.get("HEALTHCHECKS_PING_URL", ""))
    fred_api_key: str = field(default_factory=lambda: os.environ.get("FRED_API_KEY", ""))
    llm_api_key: str = field(default_factory=lambda: os.environ.get("LLM_API_KEY", ""))
    llm_model: str = field(default_factory=lambda: os.environ.get("LLM_MODEL", ""))
    risk_pct_inti: float = field(default_factory=lambda: _float("RISK_PCT_INTI", "1.0"))
    risk_pct_alt: float = field(default_factory=lambda: _float("RISK_PCT_ALT", "0.75"))
    risk_pct_meme: float = field(default_factory=lambda: _float("RISK_PCT_MEME", "0.5"))
    daily_loss_limit_pct: float = field(default_factory=lambda: _float("DAILY_LOSS_LIMIT_PCT", "3.0"))
    max_open_positions: int = field(default_factory=lambda: _int("MAX_OPEN_POSITIONS", "2"))
    max_leverage_default: int = field(default_factory=lambda: _int("MAX_LEVERAGE_DEFAULT", "3"))
    max_leverage_meme: int = field(default_factory=lambda: _int("MAX_LEVERAGE_MEME", "2"))
    environment: str = field(default_factory=lambda: os.environ.get("ENVIRONMENT", "local"))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))


def load_config() -> Config:
    """Builds config from env and validates it. Exits the process on failure
    so a bad deploy never silently runs with missing credentials or an
    out-of-bounds risk parameter (PRD: 'aplikasi menolak jalan ... dan
    langsung mengirim notifikasi')."""
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        sys.exit(f"Missing required env vars: {', '.join(missing)}")

    cfg = Config()

    for label, value in (
        ("RISK_PCT_INTI", cfg.risk_pct_inti),
        ("RISK_PCT_ALT", cfg.risk_pct_alt),
        ("RISK_PCT_MEME", cfg.risk_pct_meme),
    ):
        if not (0 < value <= MAX_RISK_PCT):
            sys.exit(f"{label}={value} out of bounds (0, {MAX_RISK_PCT}]")

    if not (0 < cfg.daily_loss_limit_pct <= MAX_DAILY_LOSS_PCT):
        sys.exit(f"DAILY_LOSS_LIMIT_PCT={cfg.daily_loss_limit_pct} out of bounds (0, {MAX_DAILY_LOSS_PCT}]")

    if cfg.max_leverage_default > MAX_LEVERAGE or cfg.max_leverage_meme > MAX_LEVERAGE:
        sys.exit(f"Leverage configured above hard ceiling of {MAX_LEVERAGE}x")

    return cfg
