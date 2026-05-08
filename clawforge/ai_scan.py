"""DeepSeek AI soul — SMC+ICT scanner."""

import json
import logging
import time

logger = logging.getLogger(__name__)


def _log_ai_call(function: str, outcome: str, latency_ms: float,
                 *, pair: str | None = None, error: str | None = None,
                 **extras) -> None:
    """Structured INFO log for AI calls. Format: ai_call k=v k=v ..."""
    parts = [f"function={function}"]
    if pair is not None:
        parts.append(f"pair={pair}")
    parts.append(f"outcome={outcome}")
    parts.append(f"latency_ms={int(latency_ms)}")
    if error is not None:
        parts.append(f"error={error}")
    for k, v in extras.items():
        parts.append(f"{k}={v}")
    logger.info("ai_call %s", " ".join(parts))


# ── Constants ──
DEFAULT_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]


def _env_float(key: str, default: float) -> float:
    """Read a float env var; fall back to default on missing or unparseable."""
    import os
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


# DeepSeek model configuration (env-driven; defaults are post-July-2026 safe).
# deepseek-v4-flash is the documented replacement for legacy deepseek-chat
# and deepseek-reasoner aliases (deprecated 2026-07-24). BYOK overrides
# arrive via these env vars per-tenant when that lands.
import os as _os

FAST_MODEL = _os.getenv("DEEPSEEK_MODEL_FAST", "deepseek-v4-flash")
FAST_TIMEOUT = _env_float("DEEPSEEK_FAST_TIMEOUT", 10.0)
DEEP_MODEL = _os.getenv("DEEPSEEK_MODEL_DEEP", "deepseek-v4-flash")
DEEP_TIMEOUT = _env_float("DEEPSEEK_DEEP_TIMEOUT", 30.0)

# Filter thresholds (0-100 scale in env for human readability,
# converted to 0-1 internally for comparison against model output).
CONFIDENCE_THRESHOLD = _env_float("DEEPSEEK_CONFIDENCE_THRESHOLD", 65.0) / 100.0
MIN_RRR = _env_float("DEEPSEEK_MIN_RRR", 2.0)


# ── Helper functions (imported at runtime to avoid circular deps) ──
def get_price(pair: str) -> float:
    """Get current price for a pair. Local import to delay dependency resolution."""
    try:
        from clawforge.telegram_ui import get_bybit_ticker_price
        return get_bybit_ticker_price(pair) or 0.0
    except Exception:
        return 0.0


def _normalize_bybit_symbol(pair: str) -> str:
    """Normalize pair to Bybit symbol format.

    Handles BTC/USDT, BTC/USDT:USDT, BTCUSDT, BTCUSDT:USDT, btc/usdt → BTCUSDT.
    Case-insensitive: uppercases input first, then strips separators and suffix.
    """
    sym = pair.upper().replace("/", "").replace(":USDT", "")
    if not sym.endswith("USDT"):
        sym += "USDT"
    return sym


def _get_bybit_klines(pair: str, interval: str = "240", limit: int = 10) -> list:
    """
    Fetch  kline (candlestick) data for a given trading pair from Bybit's linear market kline endpoint.
    
    Parameters:
        pair (str): Trading pair in formats like "BTC/USDT", "BTCUSDT", or "BTC/USDT:USDT". The function normalizes these to a Bybit symbol (e.g., "BTCUSDT").
        interval (str): Kline interval string accepted by Bybit (default "240" for 4-hour candles).
        limit (int): Maximum number of kline entries to retrieve (default 10).
    
    Returns:
        list: A list of kline entries as returned by the Bybit API (empty list if the request fails, the response is invalid, or no data is available).
    """
    try:
        from clawforge.telegram_ui import bybit_signed_request
        bybit_sym = _normalize_bybit_symbol(pair)
        data = bybit_signed_request(
            "GET", "/v5/market/kline",
            params={"category": "linear", "symbol": bybit_sym, "interval": interval, "limit": limit},
            timeout=10
        )
        if data and data.get("retCode") == 0:
            return data.get("result", {}).get("list", [])
    except Exception as e:
        logger.warning("_get_bybit_klines error: %s", e)
    return []


def _call_deepseek(messages: list, model: str = FAST_MODEL, timeout: float = FAST_TIMEOUT) -> str | None:
    """Call DeepSeek API. Local import to delay dependency resolution."""
    try:
        from clawforge.integrations.deepseek import _call_deepseek as deepseek_call
        return deepseek_call(messages, model=model, retries=max(1, int(timeout / 10)))
    except Exception as e:
        logger.warning("_call_deepseek error: %s", e)
        return None


# ── Deep layer: SMC+ICT session analysis ─────────────────────────────────────
def analyze_session(pairs: list, session: str,
                    market_context: dict = None) -> dict:
    """DeepSeek reasoner — runs every 4H or on session open."""
    enriched = {}
    for pair in pairs:
        price = get_price(pair)
        klines_4h = _get_bybit_klines(pair, interval="240", limit=10)
        pct_4h = 0.0
        if len(klines_4h) >= 2:
            try:
                o = float(klines_4h[-1][1])
                c = float(klines_4h[0][4])
                pct_4h = (c - o) / o * 100 if o else 0
            except (IndexError, ValueError, ZeroDivisionError):
                pass
        sym = _normalize_bybit_symbol(pair)
        enriched[sym] = {"price": price, "pct_4h": round(pct_4h, 2)}

    prompt = (
        f"You are an ICT/SMC analyst. Exchange: Bybit perpetual futures.\n"
        f"Analyze these pairs for {session} session. Conservative — "
        f"only flag 4+/5 confluence setups.\n\n"
        f"Live Bybit data:\n{json.dumps(enriched, indent=2)}\n\n"
        f"For each pair:\n"
        f"1. STRUCTURE: Uptrend/downtrend? BOS/ChoCH?\n"
        f"2. LIQUIDITY: Equal highs/lows swept?\n"
        f"3. KILL ZONE: Valid session for entry?\n"
        f"4. OTE: 62-79% fib entry? FVG present?\n"
        f"5. CONFIRMATION: RSI+EMA+volume align?\n\n"
        f"BUY/SELL only if 4+ layers agree. Max confidence 0.88.\n"
        f"If unsure: NEUTRAL. Protect capital first.\n\n"
        f"JSON only:\n"
        f'{{"BTCUSDT": {{"bias": "BUY|SELL|NEUTRAL", "confidence": 0.0-0.88, '
        f'"ob_zone": [low, high], "fvg": [low, high], '
        f'"key_levels": {{"support": 0, "resistance": 0}}, '
        f'"reasoning": "2-3 sentences"}}}}'
    )

    t0 = time.monotonic()
    content = _call_deepseek(
        [{"role": "user", "content": prompt}],
        model=DEEP_MODEL, timeout=DEEP_TIMEOUT,
    )
    latency_ms = (time.monotonic() - t0) * 1000
    pair_count = len(pairs)
    if not content:
        logger.warning("analyze_session: no response")
        _log_ai_call("analyze_session", "fallback_neutral", latency_ms,
                     error="no_response", pairs=pair_count)
        return {
            _normalize_bybit_symbol(p): {
                "bias": "NEUTRAL", "confidence": 0.0,
                "reasoning": "AI unavailable",
            } for p in pairs
        }
    cleaned = content.strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline != -1:
            cleaned = cleaned[first_newline:]
        cleaned = cleaned.replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        _log_ai_call("analyze_session", "success", latency_ms,
                     pairs=pair_count, returned=len(parsed))
        return parsed
    except json.JSONDecodeError:
        logger.error("analyze_session parse error: %s", cleaned[:2000])
        _log_ai_call("analyze_session", "parse_error_empty", latency_ms,
                     error="parse", pairs=pair_count)
        return {}


# ── Drop-in: ai_scan_pairs ───────────────────────────────────────────────────
def ai_scan_pairs(custom_pairs=None, chat_id=None,
                  session: str = "LONDON_NY_KZ") -> list:
    """
                  Scan trading pairs with DeepSeek SMC+ICT analysis and return the top high-conviction setups.
                  
                  This function analyzes each pair using the deep session analyzer, applies sentiment and confidence filters, computes suggested stop-loss/take-profit and risk-reward, and returns the highest-confidence trade candidates (up to four), sorted by confidence.
                  
                  Parameters:
                      custom_pairs (list | None): Optional list of symbol strings to analyze (e.g., ["BTC/USDT"]). If omitted, DEFAULT_PAIRS is used.
                      chat_id (Any | None): Optional compatibility parameter (not used by the scanner).
                      session (str): Session identifier to analyze (e.g., "LONDON_NY_KZ"). Defaults to "LONDON_NY_KZ".
                  
                  Returns:
                      list: A list (up to 4 items) of result dictionaries for each high-conviction setup. Each dictionary includes keys such as:
                          - symbol: original pair string
                          - direction: "LONG" or "SHORT"
                          - confidence: integer percent confidence (0-100)
                          - score / ai_score: scaled score derived from confidence
                          - bias: "BUY" / "SELL" / "NEUTRAL"
                          - reasoning / reasons: AI-provided reasoning text
                          - ob_zone, fvg, key_levels: liquidity and level information from analysis
                          - session, price, exchange
                          - current_price, sl, tp, rrr, change: legacy/UI fields including computed stop-loss, take-profit, and risk-reward ratio
                  """
    from clawforge.integrations.deepseek import get_sentiment_score

    pairs = custom_pairs if custom_pairs else DEFAULT_PAIRS
    playbook = analyze_session(pairs, session)
    results = []

    for pair in pairs:
        sym = _normalize_bybit_symbol(pair)
        analysis = playbook.get(sym, {})
        bias = analysis.get("bias", "NEUTRAL")
        confidence = float(analysis.get("confidence", 0.0))

        if bias == "NEUTRAL" or confidence < CONFIDENCE_THRESHOLD:
            logger.info("Skip %s — %s %.0f%%", pair, bias, confidence * 100)
            continue

        sentiment = get_sentiment_score(pair)
        if bias == "BUY" and sentiment < 0.55:
            logger.info("Skip %s — weak LONG sentiment %.2f", pair, sentiment)
            continue
        if bias == "SELL" and sentiment > 0.45:
            logger.info("Skip %s — weak SHORT sentiment %.2f", pair, sentiment)
            continue

        price = get_price(pair)
        key_levels = analysis.get("key_levels", {})
        ob_zone = analysis.get("ob_zone", [])

        # Calculate SL/TP based on direction and key levels
        sl_price = 0.0
        tp_price = 0.0
        if price > 0:
            if bias == "BUY":
                sl_price = key_levels.get("support", price * 0.99)
                tp_price = key_levels.get("resistance", price * 1.02)
            else:  # SELL
                sl_price = key_levels.get("resistance", price * 1.01)
                tp_price = key_levels.get("support", price * 0.98)

        rrr = abs((tp_price - price) / (price - sl_price)) if (price - sl_price) != 0 else 0.0

        if rrr < MIN_RRR:
            logger.info("Skip %s — RRR %.2f below min %.2f", pair, rrr, MIN_RRR)
            continue

        results.append({
            # New schema fields
            "symbol":     pair,
            "direction":  "LONG" if bias == "BUY" else "SHORT",
            "confidence": int(confidence * 100),
            "score":      round(confidence * 10, 1),
            "bias":       bias,
            "reasoning":  analysis.get("reasoning", ""),
            "ob_zone":    ob_zone,
            "fvg":        analysis.get("fvg", []),
            "key_levels": key_levels,
            "session":    session,
            "price":      price,
            "exchange":   "bybit",
            # Legacy fields for UI compatibility
            "current_price": price,
            "ai_score":      round(confidence * 10, 1),
            "reasons":       analysis.get("reasoning", ""),
            "change":        0.0,  # Not computed in this version
            "sl":            sl_price,
            "tp":            tp_price,
            "rrr":           round(rrr, 2),
        })

    results.sort(key=lambda x: x["confidence"], reverse=True)
    logger.info("ai_scan_pairs: %d high-conviction setups", len(results))
    return results[:4]


# ── AI scoring helper (provider-agnostic name for future BYOK) ───────────────
def call_ai_skill(prompt: str, retries: int = 1) -> str | None:
    """
    Send a text prompt to the AI scoring service and return its raw response.
    
    Parameters:
    	prompt (str): The user-facing prompt to send to the AI.
    	retries (int): Number of retry attempts; increases the request timeout by multiplying the base timeout by max(1, retries).
    
    Returns:
    	str | None: The AI's response text, or `None` if the call failed or timed out.
    """
    logger.debug("call_ai_skill → DeepSeek chat")
    return _call_deepseek(
        [{"role": "user", "content": prompt}],
        model=FAST_MODEL,
        timeout=FAST_TIMEOUT * max(1, retries),
    )
