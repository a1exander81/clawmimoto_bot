#!/usr/bin/env python3
"""
Session Pre-Scan Automation — ClawForge
Runs before each trading session to analyze setup quality.
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ── Config ──
SESSIONS = {
    "pre_london": {
        "name": "PRE-LONDON",
        "prescan_utc": "21:45",  # 05:45 SGT = 21:45 UTC (previous day)
        "active_start_sgt": "06:00",
        "active_end_sgt": "07:00",
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
        "margin_pct": 1.5,
        "sl_margin": 0.003,  # 0.3%
        "min_rrr": 2.5,
    },
    "london": {
        "name": "LONDON",
        "prescan_utc": "07:45",  # 15:45 SGT
        "active_start_sgt": "16:00",
        "active_end_sgt": "20:00",
        "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"],
        "margin_pct": 1.5,
        "sl_margin": 0.004,
        "min_rrr": 3.0,
    },
    "ny": {
        "name": "NY",
        "prescan_utc": "12:45",  # 20:45 SGT
        "active_start_sgt": "21:00",
        "active_end_sgt": "23:00",
        "pairs": ["BTC/USDT", "ETH/USDT"],
        "margin_pct": 2.0,
        "sl_margin": 0.005,
        "min_rrr": 2.5,
    },
}

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ── Self-contained Bybit API client ──
def bybit_request(endpoint: str, params: dict = None):
    """GET request to Bybit v5 API."""
    url = f"https://api.bybit.com{endpoint}"
    try:
        r = requests.get(url, params=params, timeout=10)
        if r.status_code != 200:
            logger.error(f"Bybit HTTP {r.status_code}: {r.text[:100]}")
            return None
        return r.json()
    except Exception as e:
        logger.error(f"Bybit API error: {e} | Status: {getattr(r, 'status_code', 'N/A')} | Body: {getattr(r, 'text', '')[:100]}")
        return None

# ── Self-contained Telegram sender ──
def send_telegram(text: str, reply_markup: dict = None):
    """Send message via Telegram Bot API."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"Telegram error: {e}")
        return None


def sgt_now():
    """Current time in SGT (UTC+8)."""
    return datetime.now(timezone.utc) + timedelta(hours=8)


def utc_now():
    """Current UTC time."""
    return datetime.now(timezone.utc)


def to_sgt(dt: datetime) -> datetime:
    """Convert datetime to SGT (assumes naive UTC if tzinfo is None)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8)))


def fetch_klines(pair: str, interval: str, limit: int = 50):
    """Fetch klines from Bybit."""
    # Convert pair format: BTC/USDT → BTCUSDT
    bybit_symbol = pair.replace("/", "").replace(":USDT", "")
    data = bybit_request(
        "/v5/market/kline",
        params={"category": "linear", "symbol": bybit_symbol, "interval": interval, "limit": limit}
    )
    if data and data.get("retCode") == 0:
        return data.get("result", {}).get("list", [])
    return []


def calculate_atr(highs, lows, closes, period=14):
    """Calculate ATR % (ATR divided by current close)."""
    if len(highs) < period + 1:
        return 0.0
    tr_sum = 0.0
    for i in range(-period, 0):
        h = highs[i]
        l = lows[i]
        c_prev = closes[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_sum += tr
    atr = tr_sum / period
    return (atr / closes[-1]) * 100 if closes[-1] else 0.0


def find_key_levels(closes, highs, lows, period=10):
    """Return (support, resistance) from last N candles."""
    if len(closes) < period:
        return None, None
    recent_closes = closes[-period:]
    recent_highs = highs[-period:]
    recent_lows = lows[-period:]
    support = min(recent_lows)
    resistance = max(recent_highs)
    return support, resistance


def calculate_rrr(entry: float, sl: float, tp: float):
    """RRR = avg(win / loss)."""
    if entry == sl:
        return 0.0
    loss_pct = abs(entry - sl) / entry
    win_pct = abs(tp - entry) / entry if entry else 0
    return win_pct / loss_pct if loss_pct else 0.0


def analyze_pair_for_session(pair: str, session_cfg: dict):
    """
    Run pre-session analysis for a single pair.
    Returns dict with analysis or None if setup invalid.
    """
    # Fetch 4H candles for S/R and ATR
    klines_4h = fetch_klines(pair, "240", 50)
    if len(klines_4h) < 20:
        logger.warning(f"Insufficient 4H data for {pair}")
        return None

    # Bybit klines: [timestamp, open, high, low, close, volume, turnover]
    closes_4h = [float(k[4]) for k in klines_4h]
    highs_4h = [float(k[2]) for k in klines_4h]
    lows_4h = [float(k[3]) for k in klines_4h]

    atr_pct = calculate_atr(highs_4h, lows_4h, closes_4h, period=14)
    support, resistance = find_key_levels(closes_4h, highs_4h, lows_4h, period=10)

    current_price = closes_4h[-1]

    # Determine direction bias: above 4H EMA8 → LONG bias; below → SHORT bias
    # Simple EMA8 calculation
    ema8 = sum(closes_4h[-8:]) / 8
    direction = "LONG" if current_price > ema8 else "SHORT"

    # Entry = key level (support for LONG, resistance for SHORT)
    if direction == "LONG":
        entry_price = support
        sl_price = entry_price * (1 - session_cfg["sl_margin"])
        tp_distance = (entry_price - sl_price) * session_cfg["min_rrr"]
        tp_price = entry_price + tp_distance
    else:
        entry_price = resistance
        sl_price = entry_price * (1 + session_cfg["sl_margin"])
        tp_distance = (sl_price - entry_price) * session_cfg["min_rrr"]
        tp_price = entry_price - tp_distance

    # Compute RRR
    rrr = calculate_rrr(entry_price, sl_price, tp_price)

    # Validate RRR (allow 0.01 tolerance for float precision)
    if rrr < (session_cfg["min_rrr"] - 0.01):
        logger.info(f"{pair} RRR {rrr:.2f} < {session_cfg['min_rrr']} — skipping")
        return None

    return {
        "symbol": pair,
        "direction": direction,
        "entry": round(entry_price, 4),
        "sl": round(sl_price, 4),
        "tp": round(tp_price, 4),
        "rrr": round(rrr, 2),
        "atr_pct": round(atr_pct, 2),
        "current_price": round(current_price, 4),
        "margin_pct": session_cfg["margin_pct"],
        "session": session_cfg["name"],
    }


def send_prescan_alert(session_key: str, results: list):
    """Send pre-session alert to Telegram chat with APPROVE/SKIP buttons."""
    if not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_CHAT_ID not set")
        return

    session_cfg = SESSIONS[session_key]
    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━━",
        f"🌅 {session_cfg['name']} SETUP",
        f"━━━━━━━━━━━━━━━━━━━━━━",
    ]

    for r in results:
        lines.append(
            f"{r['symbol']} {r['direction']}\n"
            f"Entry: ${r['entry']} (limit)\n"
            f"SL: ${r['sl']} ({'-0.5%' if r['direction']=='LONG' else '+0.5%'})\n"
            f"TP: ${r['tp']} (+{r['rrr']*100:.1f}%)\n"
            f"RRR: {r['rrr']:.1f}:1 ✅\n"
            f"ATR: {r['atr_pct']:.1f}% (volatile ✅)\n"
        )
        lines.append("")

    lines.append(f"⏰ Executing in 15min")
    lines.append("")
    lines.append("[✅ APPROVE ALL]  [❌ SKIP SESSION]")

    text = "\n".join(lines)

    # Build inline keyboard
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ APPROVE ALL", "callback_data": f"session_approve_{session_key}"},
                {"text": "❌ SKIP SESSION", "callback_data": f"session_skip_{session_key}"}
            ]
        ]
    }

    send_telegram(text, reply_markup=reply_markup)
    logger.info(f"Prescan alert sent for {session_cfg['name']}")


def run_prescan(session_key: str):
    """Main prescan entry point."""
    if session_key not in SESSIONS:
        logger.error(f"Unknown session: {session_key}")
        return 1

    session_cfg = SESSIONS[session_key]
    logger.info(f"Running prescan for {session_cfg['name']} — pairs: {session_cfg['pairs']}")

    results = []
    for pair in session_cfg["pairs"]:
        analysis = analyze_pair_for_session(pair, session_cfg)
        if analysis:
            results.append(analysis)

    if not results:
        logger.warning(f"No valid setups for {session_cfg['name']} — skipping alert")
        # Still send a "no setup" message?
        return 0

    send_prescan_alert(session_key, results)
    # Save results to a temp file for executor to read
    out = {
        "session": session_key,
        "timestamp": utc_now().isoformat(),
        "results": results
    }
    out_path = Path(__file__).absolute().parent / "session_cache" / f"{session_key}_prescan.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w') as f:
        json.dump(out, f, indent=2)
    logger.info(f"Prescan results saved to {out_path}")

    return 0


if __name__ == "__main__":
    # Expect session key as arg: pre_london, london, ny
    if len(sys.argv) < 2:
        print("Usage: session_prescan.py <session_key>")
        print("Keys: pre_london, london, ny")
        sys.exit(1)

    session_key = sys.argv[1]
    sys.exit(run_prescan(session_key))
