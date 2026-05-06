"""DeepSeek AI soul — SMC+ICT scanner."""

import json
import logging

logger = logging.getLogger(__name__)

# ── Constants ──
VALID_SESSIONS = ["LONDON_OPEN_KZ", "LONDON_NY_KZ", "NY_CLOSE_KZ"]
DEFAULT_PAIRS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]

# DeepSeek model configuration
FAST_MODEL = "deepseek-chat"
FAST_TIMEOUT = 10.0
DEEP_MODEL = "deepseek-reasoner"
DEEP_TIMEOUT = 30.0


# ── Helper functions (imported at runtime to avoid circular deps) ──
def get_price(pair: str) -> float:
    """Get current price for a pair. Local import to delay dependency resolution."""
    try:
        from clawforge.telegram_ui import get_bybit_ticker_price
        return get_bybit_ticker_price(pair) or 0.0
    except Exception:
        return 0.0


def _get_bybit_klines(pair: str, interval: str = "240", limit: int = 10) -> list:
    """Fetch Bybit klines. Local import to delay dependency resolution."""
    try:
        from clawforge.telegram_ui import bybit_signed_request
        # Normalize: BTC/USDT, BTC/USDT:USDT, BTCUSDT, BTCUSDT:USDT all → BTCUSDT
        bybit_sym = pair.replace("/", "").replace(":USDT", "").upper()
        if not bybit_sym.endswith("USDT"):
            bybit_sym += "USDT"
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


# ── Fast layer: signal gate ───────────────────────────────────────────────────
def gate_signal(pair: str, session: str, rsi: float,
                macd_hist: float, ema_cross: int,
                direction: str = "LONG") -> dict:
    """Fast DeepSeek gate on every 5M candle. Fallback: CONFIRM."""
    FALLBACK = {"decision": "CONFIRM", "confidence": 0.5,
                "reason": "AI timeout — fallback confirm"}

    if session not in VALID_SESSIONS:
        return {"decision": "REJECT", "confidence": 0.95,
                "reason": f"Outside kill zone: {session}"}

    price = get_price(pair)
    price_str = f"${price:,.4f}" if price else "unavailable"

    prompt = (
        f"You are a conservative ICT/SMC crypto trader. Exchange: Bybit perpetual futures.\n"
        f"Evaluate this {pair} {direction} signal on 5M timeframe.\n\n"
        f"Price: {price_str} | Session: {session}\n"
        f"RSI: {rsi:.1f} | MACD hist: {macd_hist:.4f} | EMA cross: "
        f"{'bullish' if ema_cross == 1 else 'bearish'}\n\n"
        f"CONFIRM only if ALL pass:\n"
        f"1. RSI not overbought >75 (LONG) or oversold <25 (SHORT)\n"
        f"2. MACD histogram aligns with direction\n"
        f"3. EMA cross aligns with direction\n"
        f"4. No obvious liquidity grab at extreme\n\n"
        f"JSON only: {{\"decision\": \"CONFIRM|REJECT|HOLD\", "
        f"\"confidence\": 0.0-1.0, \"reason\": \"one line\"}}"
    )

    content = _call_deepseek(
        [{"role": "user", "content": prompt}],
        model=FAST_MODEL, timeout=FAST_TIMEOUT,
    )
    if not content:
        return FALLBACK
    try:
        result = json.loads(content)
        decision = result.get("decision", "CONFIRM").upper()
        if decision not in ("CONFIRM", "REJECT", "HOLD"):
            decision = "CONFIRM"
        return {"decision": decision,
                "confidence": float(result.get("confidence", 0.5)),
                "reason": str(result.get("reason", ""))[:200]}
    except (json.JSONDecodeError, KeyError, ValueError):
        logger.warning("gate_signal parse error: %s", content[:200])
        return FALLBACK


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
        sym = pair.replace("/", "").replace(":USDT", "USDT")
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

    content = _call_deepseek(
        [{"role": "user", "content": prompt}],
        model=DEEP_MODEL, timeout=DEEP_TIMEOUT,
    )
    if not content:
        logger.warning("analyze_session: no response")
        return {
            p.replace("/", "").replace(":USDT", "USDT"): {
                "bias": "NEUTRAL", "confidence": 0.0,
                "reasoning": "AI unavailable",
            } for p in pairs
        }
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.error("analyze_session parse error: %s", content[:300])
        return {}


# ── Drop-in: ai_scan_pairs ───────────────────────────────────────────────────
def ai_scan_pairs(custom_pairs=None, chat_id=None,
                  session: str = "LONDON_NY_KZ") -> list:
    """Scan pairs and return high-conviction setups via DeepSeek SMC+ICT analysis."""
    from clawforge.integrations.deepseek import get_sentiment_score

    pairs = custom_pairs if custom_pairs else DEFAULT_PAIRS
    playbook = analyze_session(pairs, session)
    results = []

    for pair in pairs:
        sym = pair.replace("/", "").replace(":USDT", "USDT")
        analysis = playbook.get(sym, {})
        bias = analysis.get("bias", "NEUTRAL")
        confidence = float(analysis.get("confidence", 0.0))

        if bias == "NEUTRAL" or confidence < 0.65:
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
    """AI scoring call — routes to DeepSeek (BYOK planned)."""
    logger.debug("call_ai_skill → DeepSeek chat")
    return _call_deepseek(
        [{"role": "user", "content": prompt}],
        model=FAST_MODEL,
        timeout=FAST_TIMEOUT * max(1, retries),
    )
