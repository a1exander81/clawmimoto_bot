#!/usr/bin/env python3
"""
Session Executor — ClawForge
Handles APPROVE/SKIP callbacks from prescan alerts.
Also runs autoskip via cron for expired sessions.
"""

import os
import sys
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "8780243664:AAG_ITdvPqBAQCMSB5xsrrhUwSTXBON80uQ")
os.environ.setdefault("TELEGRAM_CHAT_ID", "7093901111")

import json
import base64
import logging
import requests
from datetime import datetime, timezone
from pathlib import Path

# ── Freqtrade API config (matches telegram_ui.py) ──
FREQTRADE_API_URL = os.getenv("FREQTRADE_API_URL", "http://127.0.0.1:8080")
FREQTRADE_API_USER = os.getenv("FREQTRADE_API_USER", "clawforge")
FREQTRADE_API_PASS = os.getenv("FREQTRADE_API_PASS", "CiRb7PvcBwsVVs7XnKvw")
AUTH_HEADER = {
    "Authorization": f"Basic {base64.b64encode(f'{FREQTRADE_API_USER}:{FREQTRADE_API_PASS}'.encode()).decode()}"
}

# ── Telegram config ──
TELEGRAM_BOT_TOKEN = os.getenv(
    "CLAWMIMOTO_BOT_TOKEN",
    os.getenv("TELEGRAM_BOT_TOKEN", "")
)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


def api_post(endpoint: str, data: dict):
    """Call Freqtrade API with Basic Auth."""
    url = f"{FREQTRADE_API_URL}{endpoint}"
    try:
        r = requests.post(url, json=data, headers=AUTH_HEADER, timeout=10)
        if r.status_code == 200:
            return True, r.json()
        else:
            error_msg = f"{r.status_code} - {r.text[:200]}"
            logger.error(f"API POST {endpoint} failed: {error_msg}")
            return False, error_msg
    except Exception as e:
        logger.error(f"API POST {endpoint} failed: {e}")
        return False, str(e)


def load_prescan_results(session_key: str) -> dict | None:
    """Load prescan results from cache."""
    cache_path = Path(__file__).parent / "session_cache" / f"{session_key}_prescan.json"
    if not cache_path.exists():
        logger.error(f"Prescan cache not found: {cache_path}")
        return None
    with open(cache_path) as f:
        return json.load(f)


def execute_trade(pair: str, direction: str, entry: float, sl: float, tp: float, margin_pct: float):
    """Execute trade via Freqtrade forcebuy."""
    # Convert to Freqtrade futures pair format: ETH/USDT → ETH/USDT:USDT
    exchange_pair = pair if ":USDT" in pair else f"{pair}:USDT"
    # Calculate stake from margin_pct
    try:
        bal = api_get("/api/v1/balance") or {}
        total = bal.get("total", 1000)
        stake = round(total * (margin_pct / 100), 2)
        stake = max(stake, 10)  # minimum $10
    except Exception:
        stake = 10
    payload = {
        "pair": exchange_pair,
        "price": entry,
        "direction": direction.lower(),
        "stake_amount": stake,
        "leverage": 20,
    }
    success, resp = api_post("/api/v1/forcebuy", payload)
    if success:
        trade_id = resp.get("trade_id")
        logger.info(f"✅ Executed {direction} {pair} @ ${entry}  trade_id={trade_id}")
        send_trade_to_channel(pair, direction, entry, sl, tp, margin_pct, trade_id)
        return True, trade_id
    else:
        logger.error(f"❌ Forcebuy failed: {resp}")
        return False, resp


def send_trade_to_channel(pair, direction, entry, sl, tp, margin_pct, trade_id):
    if not TELEGRAM_BOT_TOKEN:
        return
    channel = os.getenv("RIGHTCLAW_CHANNEL", "@RightclawTrade")
    text = (
        f"🚨 **SESSION TRADE**\n\n"
        f"Pair: {pair} {direction}\n"
        f"Entry: ${entry:,.4f} (limit)\n"
        f"SL: ${sl:,.4f}  |  TP: ${tp:,.4f}\n"
        f"Margin: {margin_pct}%  |  Leverage: 20x\n"
        f"Mode: SESSION-AUTO\n"
        f"Trade ID: {trade_id}"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": channel,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Channel log failed: {e}")


def send_approval_summary(chat_id: int, session_key: str, executed: list):
    if not TELEGRAM_BOT_TOKEN:
        return
    session_name = SESSIONS[session_key]["name"]
    text = f"✅ **{session_name} SESSION APPROVED**\n\nExecuted:\n" + "\n".join(f"• {e}" for e in executed)
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Send summary failed: {e}")


def send_skip_message(chat_id: int, session_key: str):
    if not TELEGRAM_BOT_TOKEN:
        return
    session_name = SESSIONS[session_key]["name"]
    text = f"⏭ **{session_name} SESSION SKIPPED**\nNo trades executed."
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Send skip msg failed: {e}")


# Session config (kept in sync with prescan)
SESSIONS = {
    "pre_london": {"name": "PRE-LONDON", "pairs": ["BTC/USDT","ETH/USDT","SOL/USDT"], "margin_pct": 1.5},
    "london":    {"name": "LONDON",    "pairs": ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT"], "margin_pct": 1.5},
    "ny":        {"name": "NY",        "pairs": ["BTC/USDT","ETH/USDT"], "margin_pct": 2.0},
}

CACHE_DIR = Path(__file__).absolute().parent / "session_cache"
EXPIRE_MINUTES = 30


def approve_session(session_key: str, chat_id: int):
    prescan = load_prescan_results(session_key)
    if not prescan:
        return False, "No prescan data"
    results = prescan["results"]
    executed = []
    for r in results:
        ok, resp = execute_trade(
            r["symbol"], r["direction"], r["entry"], r["sl"], r["tp"], r["margin_pct"]
        )
        if ok:
            executed.append(f"{r['symbol']} {r['direction']}")
        else:
            logger.error(f"Exec failed {r['symbol']}: {resp}")
    send_approval_summary(chat_id, session_key, executed)
    # Clean up cache
    cache_path = CACHE_DIR / f"{session_key}_prescan.json"
    if cache_path.exists():
        cache_path.unlink()
    return True, executed


def skip_session(session_key: str, chat_id: int):
    cache_path = CACHE_DIR / f"{session_key}_prescan.json"
    if cache_path.exists():
        cache_path.unlink()
    send_skip_message(chat_id, session_key)
    return True, "skipped"


def run_autoskip() -> int:
    now = datetime.now(timezone.utc)
    if not CACHE_DIR.exists():
        return 0
    for cache_file in CACHE_DIR.glob("*_prescan.json"):
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime, tz=timezone.utc)
        age = (now - mtime).total_seconds() / 60
        if age > EXPIRE_MINUTES:
            session_key = cache_file.stem.replace("_prescan", "")
            logger.warning(f"Auto-skipping {session_key} (age {age:.1f}min)")
            if TELEGRAM_CHAT_ID:
                try:
                    send_skip_message(int(TELEGRAM_CHAT_ID), session_key)
                except Exception as e:
                    logger.error(f"Autoskip msg failed: {e}")
            try:
                cache_file.unlink()
                logger.info(f"Removed cache {cache_file}")
            except Exception as e:
                logger.error(f"Failed to delete cache: {e}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: session_executor.py <approve|skip|autoskip> [session_key] [chat_id]")
        sys.exit(1)
    action = sys.argv[1]
    if action == "autoskip":
        sys.exit(run_autoskip())
    if len(sys.argv) < 4:
        print(f"Usage: session_executor.py {action} <session_key> <chat_id>")
        sys.exit(1)
    session_key = sys.argv[2]
    chat_id = int(sys.argv[3])
    if action == "approve":
        ok, _ = approve_session(session_key, chat_id)
    elif action == "skip":
        ok, _ = skip_session(session_key, chat_id)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
    sys.exit(0 if ok else 1)
