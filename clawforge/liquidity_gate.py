# clawforge/liquidity_gate.py
"""Crypto-specific liquidity gate using Bybit real-time data.

Provides real-time market condition checks so both Claw (directional)
and Grid (contrarian) layers can adapt to current liquidity, volume,
and spread conditions — with specialized weekend mode.
"""
import os
import logging
from typing import Optional
import ccxt

from config.sessions import get_market_state, TRADING_SESSIONS

logger = logging.getLogger(__name__)

# ── Default thresholds ──
MIN_VOLUME_24H_USDT = 5_000_000   # $5M minimum 24h volume
MAX_SPREAD_PCT = 0.15            # Max 0.15% bid-ask spread
WEEKEND_VOLUME_MULTIPLIER = 0.5  # Accept 50% of normal volume on weekends
COOLDOWN_SECONDS = 15            # Cache validity for market checks


class LiquidityCache:
    """Simple TTL cache to avoid hammering Bybit on every callback click."""
    def __init__(self):
        self._data: dict[str, tuple] = {}  # key -> (result, timestamp)

    def get(self, key: str) -> Optional[tuple]:
        import time
        cached = self._data.get(key)
        if cached and (time.time() - cached[1]) < COOLDOWN_SECONDS:
            return cached[0]
        return None

    def set(self, key: str, result: tuple):
        import time
        self._data[key] = (result, time.time())


_liquidity_cache = LiquidityCache()


def _get_exchange() -> ccxt.Exchange:
    """Create a rate-limited Bybit exchange instance (perp futures)."""
    exchange = ccxt.bybit({
        "enableRateLimit": True,
        "options": {"defaultType": "swap"},  # Perpetual futures
    })
    # Optional: authenticate for higher rate limits
    api_key = os.getenv("BYBIT_API_KEY", "")
    api_secret = os.getenv("BYBIT_API_SECRET", "")
    if api_key and api_secret:
        exchange.apiKey = api_key
        exchange.secret = api_secret
    return exchange


def is_market_tradable(
    symbol: str = "BTC/USDT",
    layer: str = "claw",
) -> tuple[bool, str]:
    """Check if current market conditions are suitable for trading.

    Uses live Bybit ticker data to assess:
      - 24h volume (adjusted for weekends)
      - Bid-ask spread
      - Weekend warning

    Args:
        symbol: Trading pair (e.g. "BTC/USDT")
        layer: "claw" or "grid" — affects threshold strictness

    Returns:
        (is_tradable: bool, reason: str)
    """
    cache_key = f"{symbol}:{layer}"
    cached = _liquidity_cache.get(cache_key)
    if cached is not None:
        return cached

    state = get_market_state()

    try:
        exchange = _get_exchange()

        # Normalize symbol for Bybit (e.g. BTC/USDT -> BTC/USDT:USDT for perp)
        bybit_symbol = symbol.replace("/", "")
        if not bybit_symbol.endswith("USDT"):
            bybit_symbol = f"{bybit_symbol}USDT"
        # Bybit perp uses format like BTCUSDT
        ticker_symbol = bybit_symbol  # ccxt handles the mapping

        # Fetch ticker
        ticker = exchange.fetch_ticker(ticker_symbol)
        volume_24h = ticker.get("quoteVolume", 0) or 0
        bid = ticker.get("bid")
        ask = ticker.get("ask")
        last_price = ticker.get("last", 0)

        if not bid or not ask or ask <= 0:
            result = (False, f"Cannot fetch valid bid/ask for {symbol}")
            _liquidity_cache.set(cache_key, result)
            return result

        spread_pct = ((ask - bid) / ask) * 100

        # Adjust thresholds for weekend
        effective_min_volume = MIN_VOLUME_24H_USDT
        if state["is_weekend"]:
            effective_min_volume *= WEEKEND_VOLUME_MULTIPLIER

        # Grid layer can tolerate slightly lower thresholds
        if layer == "grid":
            effective_min_volume = int(effective_min_volume * 0.7)

        # ── Volume check ──
        if volume_24h < effective_min_volume:
            reason = (
                f"Low 24h volume: ${volume_24h:,.0f} "
                f"< ${effective_min_volume:,.0f}"
            )
            result = (False, reason)
            _liquidity_cache.set(cache_key, result)
            return result

        # ── Spread check ──
        if spread_pct > MAX_SPREAD_PCT:
            reason = (
                f"Spread too wide: {spread_pct:.2f}% "
                f"> {MAX_SPREAD_PCT}%"
            )
            result = (False, reason)
            _liquidity_cache.set(cache_key, result)
            return result

        # ── Weekend warning (informational, does not block) ──
        if state["is_weekend"]:
            logger.warning(
                "Weekend trading on %s: reduced liquidity, "
                "mean-reversion bias, fakeout risk elevated",
                symbol,
            )

        ok_reason = (
            f"OK (vol: ${volume_24h:,.0f}, "
            f"spread: {spread_pct:.2f}%, "
            f"price: ${last_price:,.2f})"
        )
        result = (True, ok_reason)
        _liquidity_cache.set(cache_key, result)
        return result

    except Exception as exc:
        logger.error("Liquidity gate error for %s: %s", symbol, exc)
        # Fail closed on API errors — safety first
        result = (False, f"Liquidity check unavailable: {exc}")
        _liquidity_cache.set(cache_key, result)
        return result


def get_claw_params(state: dict) -> dict:
    """Return Claw-specific trading params adjusted for current market state.

    Args:
        state: Result from config.sessions.get_market_state()

    Returns:
        dict with keys: max_trades, risk_per_trade_pct, min_volume_threshold,
                        mean_reversion_only (bool)
    """
    is_weekend = state.get("is_weekend", False)
    tendency = state.get("tendency", "normal")
    active_session = state.get("active_session")

    if is_weekend:
        return {
            "max_trades": 1,
            "risk_per_trade_pct": 0.5,
            "min_volume_threshold": 0.4,
            "mean_reversion_only": True,
            "label": "Weekend Reduced Mode",
        }

    if active_session and active_session in TRADING_SESSIONS:
        sess = TRADING_SESSIONS[active_session]
        return {
            "max_trades": sess["claw_settings"]["max_trades_per_session"],
            "risk_per_trade_pct": sess["claw_settings"]["risk_per_trade_pct"],
            "min_volume_threshold": sess["claw_settings"]["min_volume_threshold"],
            "mean_reversion_only": False,
            "label": f"{sess['emoji']} {sess['name']}",
        }

    # Fallback: no active session
    return {
        "max_trades": 1,
        "risk_per_trade_pct": 0.5,
        "min_volume_threshold": 0.5,
        "mean_reversion_only": tendency == "mean-reverting",
        "label": "Default",
    }


def get_weekend_grid_params() -> dict:
    """Return conservative grid parameters for weekend mean-reverting chops.

    Returns:
        dict with keys: grid_spacing_factor, tp_markup_pct,
                        max_wallet_exposure_pct, max_trades_per_session
    """
    return {
        "grid_spacing_factor": 0.6,      # Tighter grid for mean-reverting chops
        "tp_markup_pct": 0.06,           # Smaller profit targets
        "max_wallet_exposure_pct": 8,    # Lower overall exposure
        "max_trades_per_session": 2,     # Fewer concurrent trades
        "label": "Weekend (Conservative)",
    }


def get_weekday_grid_params(session_key: str) -> dict:
    """Return aggressive grid parameters for high-liquidity weekday sessions.

    Args:
        session_key: One of "pre_london", "london", "ny_overlap", "ny",
                     or None/unknown for default

    Returns:
        dict with keys: grid_spacing_factor, tp_markup_pct,
                        max_wallet_exposure_pct, max_trades_per_session
    """
    params = {
        "ny_overlap": {
            "grid_spacing_factor": 1.5,
            "tp_markup_pct": 0.20,
            "max_wallet_exposure_pct": 25,
            "max_trades_per_session": 4,
            "label": "💥 EU-US Overlap (Aggressive)",
        },
        "london": {
            "grid_spacing_factor": 1.2,
            "tp_markup_pct": 0.15,
            "max_wallet_exposure_pct": 20,
            "max_trades_per_session": 3,
            "label": "🇪🇺 European (Aggressive)",
        },
        "ny": {
            "grid_spacing_factor": 1.3,
            "tp_markup_pct": 0.18,
            "max_wallet_exposure_pct": 22,
            "max_trades_per_session": 4,
            "label": "🇺🇸 New York (Aggressive)",
        },
        "pre_london": {
            "grid_spacing_factor": 0.8,
            "tp_markup_pct": 0.08,
            "max_wallet_exposure_pct": 10,
            "max_trades_per_session": 1,
            "label": "🌅 Pre-London (Moderate)",
        },
    }
    return params.get(session_key, params["london"])


def get_grid_params(state: dict) -> dict:
    """High-level dispatcher: returns correct grid params for current state.

    Args:
        state: Result from config.sessions.get_market_state()

    Returns:
        dict with grid parameters
    """
    if state.get("is_weekend", False):
        return get_weekend_grid_params()
    active_session = state.get("active_session")
    return get_weekday_grid_params(active_session) if active_session else get_weekend_grid_params()
