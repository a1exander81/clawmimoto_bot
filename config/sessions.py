# config/sessions.py
"""Trading session definitions + day-of-week volatility profiles."""
from datetime import time, datetime, timezone

# ── Session Definitions ──
TRADING_SESSIONS = {
    "pre_london": {
        "name": "Pre-London",
        "emoji": "🌅",
        "gmt_start": time(6, 0),
        "gmt_end": time(8, 0),
        "volatility_level": "rising",
        "tendency": "trending",
        "claw_settings": {
            "max_trades_per_session": 1,
            "risk_per_trade_pct": 0.5,
            "min_volume_threshold": 0.5,
        },
        "grid_settings": {
            "grid_spacing_factor": 0.8,
            "tp_markup_pct": 0.08,
            "max_wallet_exposure_pct": 10,
        },
    },
    "london": {
        "name": "European",
        "emoji": "🇪🇺",
        "gmt_start": time(8, 0),
        "gmt_end": time(16, 0),
        "volatility_level": "very_high",
        "tendency": "trending",
        "claw_settings": {
            "max_trades_per_session": 3,
            "risk_per_trade_pct": 1.0,
            "min_volume_threshold": 0.7,
        },
        "grid_settings": {
            "grid_spacing_factor": 1.2,
            "tp_markup_pct": 0.15,
            "max_wallet_exposure_pct": 20,
        },
    },
    "ny_overlap": {
        "name": "EU-US Overlap",
        "emoji": "💥",
        "gmt_start": time(13, 0),
        "gmt_end": time(16, 0),
        "volatility_level": "extreme",
        "tendency": "trending",
        "claw_settings": {
            "max_trades_per_session": 4,
            "risk_per_trade_pct": 1.5,
            "min_volume_threshold": 0.8,
        },
        "grid_settings": {
            "grid_spacing_factor": 1.5,
            "tp_markup_pct": 0.20,
            "max_wallet_exposure_pct": 25,
        },
    },
    "ny": {
        "name": "New York",
        "emoji": "🇺🇸",
        "gmt_start": time(13, 0),
        "gmt_end": time(22, 0),
        "volatility_level": "high",
        "tendency": "trending",
        "claw_settings": {
            "max_trades_per_session": 4,
            "risk_per_trade_pct": 1.0,
            "min_volume_threshold": 0.8,
        },
        "grid_settings": {
            "grid_spacing_factor": 1.3,
            "tp_markup_pct": 0.18,
            "max_wallet_exposure_pct": 22,
        },
    },
}

# ── Day-of-Week Volatility Profiles ──
WEEKDAY_PROFILES = {
    "Monday":    {"tendency": "trending",       "avg_return_pct": 1.55,  "volatility_rank": "high"},
    "Tuesday":   {"tendency": "volatile",       "avg_return_pct": 0.80,  "volatility_rank": "high"},
    "Wednesday": {"tendency": "normal",         "avg_return_pct": 0.50,  "volatility_rank": "moderate"},
    "Thursday":  {"tendency": "normal",         "avg_return_pct": 0.40,  "volatility_rank": "moderate"},
    "Friday":    {"tendency": "trending",       "avg_return_pct": 0.90,  "volatility_rank": "high"},
    "Saturday":  {"tendency": "mean-reverting", "avg_return_pct": 0.30,  "volatility_rank": "low"},
    "Sunday":    {"tendency": "mean-reverting", "avg_return_pct": 0.25,  "volatility_rank": "low"},
}


def get_market_state() -> dict:
    """Return the current market state based on UTC day and time.

    Returns:
        weekday: str (e.g. "Monday")
        is_weekend: bool
        active_session: str | None (session key or None)
        tendency: str ("trending"|"volatile"|"normal"|"mean-reverting")
        volatility_rank: str ("high"|"moderate"|"low")
    """
    now = datetime.now(timezone.utc)
    weekday = now.strftime("%A")
    is_weekend = weekday in ("Saturday", "Sunday")
    profile = WEEKDAY_PROFILES.get(weekday, {})

    # Determine active session
    active_session = None
    current_time = now.time()
    for key, sess in TRADING_SESSIONS.items():
        if sess["gmt_start"] <= current_time < sess["gmt_end"]:
            active_session = key
            break

    return {
        "weekday": weekday,
        "is_weekend": is_weekend,
        "active_session": active_session,
        "tendency": profile.get("tendency", "normal"),
        "volatility_rank": profile.get("volatility_rank", "unknown"),
    }


def is_overlap() -> bool:
    """Check if EU-US overlap session is active (13:00–16:00 UTC)."""
    now = datetime.now(timezone.utc).time()
    return time(13, 0) <= now < time(16, 0)


def get_active_sessions() -> list[str]:
    """Return list of active session keys at current UTC time."""
    now = datetime.now(timezone.utc).time()
    active = []
    for key, sess in TRADING_SESSIONS.items():
        if sess["gmt_start"] <= now < sess["gmt_end"]:
            active.append(key)
    return active
