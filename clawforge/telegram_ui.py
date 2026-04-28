#!/usr/bin/env python3
"""
Clawmimoto Telegram UI - Revised per user specs
Main Menu with news, BalRealMoc, ModeReal, wins, Gains
SESSION: 2x2 grid with leverage/margin controls, AI scan, pair details
POSITIONS: list with share PNL
"""

import os
import logging
import base64
import hashlib
import hmac
import requests
import asyncio
import time
import threading
import json
import re
import concurrent.futures
from datetime import datetime, timezone, timedelta
from pathlib import Path
import feedparser
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error, BotCommand
from telegram.error import BadRequest, TelegramError
import psutil
import subprocess
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

# ── Utility: async message deletion ──
async def delete_after_delay(bot, chat_id: int, msg_id: int, delay: int = 300):
    """Delete a Telegram message after `delay` seconds (default 5 minutes)."""
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=msg_id)
    except Exception:
        pass

# ── Trading Trivia Facts ──
TRADING_FACTS = [
    "📜 **Fact:** The first recorded stock exchange was in Amsterdam, 1602 - the Dutch East India Company.",
    "🔥 **Fact:** On Black Monday (1987), the Dow dropped 22% in a single day - still the biggest one-day % drop.",
    "🐋 **Fact:** About 90% of retail traders lose money. The 10% who win treat it like a business, not a casino.",
    "⏰ **Fact:** The NYSE opens at 9:30 AM ET - that's when the smart money moves. The last 30 mins are often the wildest.",
    "💡 **Fact:** Most pros use 1-2% risk per trade. If you risk more, you're gambling, not trading.",
    "🌊 **Fact:** Crypto never sleeps - 24/7/365. That's why sleep management is a real edge for degens.",
    "🎯 **Fact:** The '2% rule' (never risk more than 2% per trade) has saved more accounts than any indicator.",
    "📈 **Fact:** The 'Greater Fool Theory' describes most crypto pumps: someone's always the greater fool.",
    "⚡ **Fact:** The average lifespan of a crypto token is 9 months. 99% of altcoins go to zero.",
    "🏦 **Fact:** In 2023, Binance processed $14 trillion in trading volume - more than the GDP of China.",
    "🧠 **Fact:** Trading is 80% psychology. Your brain is your biggest enemy - FOMO, FUD, revenge trading.",
    "📊 **Fact:** The 'Golden Cross' (50 MA > 200 MA) is a classic bull signal - but it's often a late indicator.",
    "💸 **Fact:** The 'Fed Put' isn't real - but markets believe in it. When the Fed steps in, everything rallies.",
    "🔢 **Fact:** The '80-20 rule' applies: 80% of your gains come from 20% of your trades. Quality > quantity.",
    "🛡️ **Fact:** 'Not your keys, not your coins' - but also, 'Not your keys, no trading.' Exchanges are banks now."
]

# ── Trading Trivia Facts ──
TRADING_FACTS = [
    "📜 **Fact:** The first recorded stock exchange was in Amsterdam, 1602 - the Dutch East India Company.",
    "🔥 **Fact:** On Black Monday (1987), the Dow dropped 22% in a single day - still the biggest one-day % drop.",
    "🐋 **Fact:** About 90% of retail traders lose money. The 10% who win treat it like a business, not a casino.",
    "⏰ **Fact:** The NYSE opens at 9:30 AM ET - that's when the smart money moves. The last 30 mins are often the wildest.",
    "💡 **Fact:** Most pros use 1-2% risk per trade. If you risk more, you're gambling, not trading.",
    "🌊 **Fact:** Crypto never sleeps - 24/7/365. That's why sleep management is a real edge for degens.",
    "🎯 **Fact:** The '2% rule' (never risk more than 2% per trade) has saved more accounts than any indicator.",
    "📈 **Fact:** The 'Greater Fool Theory' describes most crypto pumps: someone's always the greater fool.",
    "⚡ **Fact:** The average lifespan of a crypto token is 9 months. 99% of altcoins go to zero.",
    "🏦 **Fact:** In 2023, Binance processed $14 trillion in trading volume - more than the GDP of China.",
    "🧠 **Fact:** Trading is 80% psychology. Your brain is your biggest enemy - FOMO, FUD, revenge trading.",
    "📊 **Fact:** The 'Golden Cross' (50 MA > 200 MA) is a classic bull signal - but it's often a late indicator.",
    "💸 **Fact:** The 'Fed Put' isn't real - but markets believe in it. When the Fed steps in, everything rallies.",
    "🔢 **Fact:** The '80-20 rule' applies: 80% of your gains come from 20% of your trades. Quality > quantity.",
    "🛡️ **Fact:** 'Not your keys, not your coins' - but also, 'Not your keys, no trading.' Exchanges are banks now."
]

async def cycle_facts_on_message(msg, title: str, interval: int = 4):
    """Edit `msg` with a new trading fact every `interval` seconds until cancelled."""
    facts = TRADING_FACTS.copy()
    random.shuffle(facts)
    idx = 0
    try:
        while True:
            fact = facts[idx % len(facts)]
            idx += 1
            try:
                await msg.edit_text(
                    f"{title}\n\n{fact}\n\n_Still working..._",
                    parse_mode="Markdown"
                )
            except:
                pass  # Message deleted or unavailable
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        pass

# ── Auto-refresh for position details ──
position_refresh_tasks = {}  # chat_id -> asyncio.Task

async def auto_refresh_position(chat_id: int, trade_id: str, context: ContextTypes.DEFAULT_TYPE, interval: int = 6):
    """Periodically update position detail message every `interval` seconds until cancelled."""
    try:
        while True:
            await asyncio.sleep(interval)
            # Abort if this task is no longer the active one for the chat
            if chat_id not in position_refresh_tasks or position_refresh_tasks[chat_id].get("trade_id") != trade_id:
                logger.debug(f"Auto-refresh task obsolete for chat={chat_id}, trade_id={trade_id}. Exiting.")
                break
            # Fetch fresh trade data from /api/v1/status
            trades_list = api_get("/api/v1/status") or []
            t = next((trade for trade in trades_list if str(trade.get('trade_id')) == trade_id), None)
            if not t:
                continue  # trade gone, will be cleaned up by cancel
            # Rebuild the detail view text & buttons (similar to pos_detail_cb)
            state = get_state(chat_id)
            real, mock = get_balance()
            bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
            is_open = t.get("is_open", True)
            if is_open:
                pnl_line = f"Unrealized: {t.get('profit_pct',0):+.1f}%"
                if t.get('profit_abs') is not None:
                    pnl_line += f" (${t['profit_abs']:,.2f})"
            else:
                pnl_line = f"Realized PnL: {t.get('profit_pct',0):+.1f}%"
                if t.get('profit_abs') is not None:
                    pnl_line += f" (${t['profit_abs']:,.2f})"
            status_btn = InlineKeyboardButton("🔴 CLOSE POSITION", callback_data=f"close_{trade_id}") if is_open else InlineKeyboardButton("✅ CLOSED", callback_data="dummy")
            text = (f"📊 {t['pair']} {t.get('direction','LONG')} {'OPEN' if is_open else 'CLOSED'}\n\n"
                    f"Balance: {bal}\n"
                    f"Time: {t.get('open_date','')}\n"
                    f"Margin: ${t.get('stake_amount',0):,.2f}  |  {pnl_line}\n"
                    f"Entry: {t.get('open_rate',0):,.2f}  |  SL: {t.get('stop_loss_pct',0):.1f}%  |  TP: {t.get('take_profit',0):,.2f}\n")
            kb = [
                [status_btn],
                [InlineKeyboardButton("📤 Share PNL", callback_data=f"share_{trade_id}")],
                [InlineKeyboardButton("🔄 Refresh", callback_data=f"pos_{trade_id}")],
                [InlineKeyboardButton("⬅️ BACK", callback_data="positions")]
            ]
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=position_refresh_tasks[chat_id]["msg_id"], text=text, reply_markup=InlineKeyboardMarkup(kb))
            except Exception as e:
                # Message probably deleted or inaccessible; cancel task
                logger.debug(f"Auto-refresh for {chat_id} stopped: {e}")
                break
    except asyncio.CancelledError:
        pass
    finally:
        if chat_id in position_refresh_tasks:
            del position_refresh_tasks[chat_id]

# ── Load config ──
ENV_PATH = Path(__file__).parent.parent / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=True)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "7093901111")
API_URL = os.getenv("FREQTRADE_API_URL", "http://172.19.0.2:8080")
API_USER = os.getenv("FREQTRADE_API_USER", "clawforge")
API_PASS = os.getenv("FREQTRADE_API_PASS", "CiRb7PvcBwsVVs7XnKvw")
BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
BYBIT_API_KEY = os.getenv("BYBIT_API_KEY")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://aauypnqsmyxzacchbiya.supabase.co")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFhdXlwbnFzbXl4emFjY2hiaXlhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY5Nzg2MDUsImV4cCI6MjA5MjU1NDYwNX0.H8RbnYbUb55jr0RnOVpca2wkYgv_jKs8NuUHjruqWls")

AUTH_HEADER = {"Authorization": f"Basic {base64.b64encode(f'{API_USER}:{API_PASS}'.encode()).decode()}"}

# ── Access Control ──
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "7093901111"))
REQUIRED_CHANNEL = os.getenv("REQUIRED_CHANNEL", "@RightclawTrade")
# Whitelist: comma-separated Telegram user IDs (strings or ints)
WHITELIST_RAW = os.getenv("WHITELISTED_USER_IDS", "")
WHITELIST_IDS = set()
for uid in WHITELIST_RAW.split(","):
    uid = uid.strip()
    if uid:
        try:
            WHITELIST_IDS.add(int(uid))
        except ValueError:
            pass  # ignore invalid

async def check_channel_membership(user_id: int, bot_token: str, channel: str) -> bool:
    """Check if user is a member of the required channel."""
    if not bot_token or not channel:
        return True  # no config → allow
    url = f"https://api.telegram.org/bot{bot_token}/getChatMember"
    payload = {"chat_id": channel, "user_id": user_id}
    try:
        r = requests.post(url, json=payload, timeout=5)
        if r.status_code == 200:
            data = r.json()
            status = data.get("result", {}).get("status", "")
            # member, administrator, creator are valid
            return status in ("member", "administrator", "creator")
    except Exception as e:
        logger.debug(f"Channel membership check failed: {e}")
    return False

def get_user_tier(user_id: int) -> str:
    """Return 'admin', 'whitelisted', or 'public'."""
    if user_id == ADMIN_ID:
        return "admin"
    if user_id in WHITELIST_IDS:
        return "whitelisted"
    return "public"

def is_admin(user_id: int) -> bool:
    """Check if user_id is the admin."""
    return user_id == ADMIN_ID

async def enforce_access(update: Update, context: ContextTypes.DEFAULT_TYPE, allow_admin: bool = True,
                         allow_whitelisted: bool = True, require_channel: bool = True) -> bool:
    """
    Check if the user is allowed to execute this command/callback.
    Returns True if allowed, False if denied (and sends denial message).
    """
    user = update.effective_user
    if not user:
        return False
    user_id = user.id
    tier = get_user_tier(user_id)
    # Admin always allowed (if allow_admin=True)
    if tier == "admin":
        return True
    # Whitelisted checks
    if tier == "whitelisted":
        if not allow_whitelisted:
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 **Access Denied**\n\nYou are whitelisted but this command is admin-only.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
            )
            return False
        if require_channel:
            member = await check_channel_membership(user_id, TOKEN, REQUIRED_CHANNEL)
            if not member:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🚫 **Channel Membership Required**\n\nYou must join {REQUIRED_CHANNEL} to use this bot.\n\n🔗 {REQUIRED_CHANNEL}",
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
                )
                return False
        return True
    # Public: denied
    await context.bot.send_message(
        chat_id=user_id,
        text=f"🚫 **Access Denied**\n\nThis bot is private.\n\n• Admin: full access\n• Whitelisted: trading only (must join {REQUIRED_CHANNEL})\n• Public: not allowed",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 MAIN", callback_data="main")]])
    )
    return False
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── State ──
STATE_FILE = "/app/data/user_state.json"

def _load_state():
    try:
        import json as _json
        from pathlib import Path as _Path
        p = _Path(STATE_FILE)
        if p.exists():
            raw = _json.loads(p.read_text())
            return {int(k): v for k, v in raw.items()}
    except Exception:
        pass
    return {}

def _save_state():
    try:
        import json as _json
        from pathlib import Path as _Path
        _Path(STATE_FILE).parent.mkdir(parents=True, exist_ok=True)
        _Path(STATE_FILE).write_text(_json.dumps({str(k): v for k, v in user_state.items()}))
    except Exception as e:
        pass

user_state = _load_state()

def get_state(chat_id):
    """Get or initialize user state with all required keys."""
    if chat_id not in user_state:
        user_state[chat_id] = {}
    # Ensure all required keys exist (migrate old/incomplete state)
    defaults = {"leverage": 50, "margin": 1, "trade_mode": "MOCK", "selected_pair": None}
    for key, val in defaults.items():
        user_state[chat_id].setdefault(key, val)
    return user_state[chat_id]

# ── API helpers ──
def api_get(endpoint):
    try:
        r = requests.get(f"{API_URL}{endpoint}", headers=AUTH_HEADER, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"API GET {endpoint} failed: {e}")
        return None

def api_post(endpoint, payload=None):
    """POST to Freqtrade API. Returns (success: bool, error_msg: str)."""
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=payload or {}, headers=AUTH_HEADER, timeout=10)
        if r.status_code == 200:
            return True, ""
        else:
            error_msg = f"{r.status_code} - {r.text[:200]}"
            logger.error(f"API POST {endpoint} failed: {error_msg}")
            return False, error_msg
    except Exception as e:
        logger.error(f"API POST {endpoint} failed: {e}")
        return False, str(e)

# ── Leverage Calculator ──
def calculate_leverage(confidence: float, trend_strength: float) -> int:
    """Dynamic leverage based on AI confidence and trend strength.
    Base 50× modulated by multipliers. Clamped 5–100.
    """
    ai_mult = (
        1.0 if confidence >= 90 else
        0.8 if confidence >= 85 else
        0.6 if confidence >= 80 else 0.4
    )
    trend_mult = (
        1.0 if trend_strength >= 0.8 else
        0.7 if trend_strength >= 0.6 else
        0.5 if trend_strength >= 0.4 else 0.3
    )
    lev = 50 * ai_mult * trend_mult
    return max(5, min(100, int(lev)))

# ── Bybit API (v5) ──
def bybit_signed_request(method: str, endpoint: str, params: dict = None, body: dict = None, **kwargs):
    if not BYBIT_API_KEY or not BYBIT_API_SECRET:
        return None
    import time
    timestamp = str(int(time.time() * 1000))
    recv_window = "5000"
    base_url = "https://api.bybit.com"
    url = f"{base_url}{endpoint}"
    if params:
        sorted_params = sorted(params.items())
        query = '&'.join([f"{k}={v}" for k, v in sorted_params])
        url += f"?{query}"
    body_str = ""
    if body and method.upper() == "POST":
        import json
        body_str = json.dumps(body, separators=(',', ':'), sort_keys=True)
    sign_str = f"{timestamp}{method.upper()}{recv_window}{body_str}"
    signature = hmac.new(BYBIT_API_SECRET.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    headers = {
        "X-BAPI-API-KEY": BYBIT_API_KEY,
        "X-BAPI-SIGN": signature,
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": recv_window,
        "Content-Type": "application/json"
    }
    try:
        r = requests.request(method, url, headers=headers, data=body_str if method.upper() == "POST" else None, **kwargs)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"Bybit API error: {e}")
        return None


def get_bybit_ticker_price(symbol: str) -> float | None:
    """Fetch latest price from Bybit ticker. symbol format: BTC/USDT."""
    try:
        bybit_symbol = symbol.replace("/", "").upper()
        data = bybit_signed_request(
            "GET", "/v5/market/tickers",
            params={"category": "linear", "symbol": bybit_symbol},
            timeout=5
        )
        if data and data.get("retCode") == 0:
            item = data.get("result", {}).get("list", [{}])[0]
            price = float(item.get("lastPrice", 0))
            if price > 0:
                return price
    except Exception as e:
        logger.debug(f"Bybit ticker price error for {symbol}: {e}")
    return None


def get_bybit_hot_pairs(limit: int = 5) -> list:
    """Fetch top volatile USDT perpetual pairs from Bybit ticker."""
    try:
        data = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear"}, timeout=5)
        if data and data.get("retCode") == 0:
            items = data.get("result", {}).get("list", [])
            pairs = []
            EXCLUDED = {
                "USDC", "BUSD", "DAI", "TUSD", "FDUSD",  # stables
                "XAUT", "PAXG",  # gold tokens
                "CL", "GC", "SI", "NG", "HG",  # commodity symbols
                "GOLD", "SILVER", "OIL", "COPPER",  # commodity names
            }
            for item in items:
                symbol = item.get("symbol", "")
                if symbol.endswith("USDT"):
                    base = symbol[:-4]
                    if base in EXCLUDED:
                        logger.info(f"Filtered out {base} — commodity/stable")
                        continue
                    pairs.append(f"{base}/USDT")
                if len(pairs) >= limit:
                    break
            logger.info(f"Bybit hot USDT pairs: {pairs}")
            if pairs:
                return pairs
    except Exception as e:
        logger.debug(f"Bybit hot pairs error: {e}")
    fallback = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"][:limit]
    logger.warning("Bybit hot pairs fetch failed, using fallback USDT list")
    return fallback

def get_bybit_ticker_price(symbol: str) -> float | None:
    """Fetch latest price from Bybit ticker. symbol format: BTC/USDT."""
    try:
        bybit_symbol = symbol.replace("/", "").upper()
        data = bybit_signed_request(
            "GET", "/v5/market/tickers",
            params={"category": "linear", "symbol": bybit_symbol},
            timeout=5
        )
        if data and data.get("retCode") == 0:
            item = data.get("result", {}).get("list", [{}])[0]
            price = float(item.get("lastPrice", 0))
            if price > 0:
                return price
    except Exception as e:
        logger.debug(f"Bybit ticker price error for {symbol}: {e}")
    return None

def get_bybit_klines(symbol: str, interval: str = "5", limit: int = 50):
    """Fetch klines from Bybit. symbol format: BTC/USDT (converted to BTCUSDT)."""
    try:
        bybit_symbol = symbol.replace("/", "").upper()
        data = bybit_signed_request(
            "GET",
            "/v5/market/kline",
            params={"category": "linear", "symbol": bybit_symbol, "interval": interval, "limit": str(limit)},
            timeout=5
        )
        if data and data.get("retCode") == 0:
            klines = data.get("result", {}).get("list", [])
            if klines:
                logger.info(f"Bybit klines for {symbol}: {len(klines)} candles")
                candles = []
                for k in klines:
                    candles.append({"open": k[1], "high": k[2], "low": k[3], "close": k[4], "volume": k[5]})
                return {"data": candles}
    except Exception as e:
        logger.debug(f"Bybit klines error for {symbol}: {e}")
    return None

# ── Single Pair Analyzer ──
def analyze_pair(pair):
    """Analyze a single pair (format 'BTC/USDT') and return result dict."""
    print(f"[DEBUG] analyze_pair called with: {pair}")
    symbol = pair.replace("/", "")
    klines_data = get_bybit_klines(symbol, interval="5", limit=50)
    change = 0
    volume = 0
    current_price = 0
    if klines_data and "data" in klines_data and len(klines_data["data"]) >= 2:
        closes = [float(k["close"]) for k in klines_data["data"][-10:]]
        if len(closes) >= 2:
            change = (closes[-1] - closes[-2]) / closes[-2] * 100
        volume = sum(float(k["volume"]) for k in klines_data["data"][-5:])
        current_price = closes[-1] if closes else 0
    # If we don't have price from klines, fetch from ticker
    if current_price <= 0:
        current_price, _ = get_binance_ticker(symbol)
    prompt = f"Scalp analysis for {pair} 5M: change {change:.2f}%, volume {volume:.0f}. Give: direction (LONG/SHORT), confidence 80-90%, RRR 1.5-3.0, 3 reasons."
    ai_text = call_stepfun_skill(prompt)
    direction = "LONG" if change >= 0 else "SHORT"
    confidence = 85 if change >= 0 else 75
    reasons = ["High volume", "Momentum", "AI signal"]
    if ai_text:
        ai_lower = ai_text.lower()
        if "short" in ai_lower:
            direction = "SHORT"
        if "confidence" in ai_lower:
            try:
                confidence = int(''.join(filter(str.isdigit, ai_text.split("confidence")[1].split("%")[0])))
            except: pass
        reasons = [line.strip("- * ") for line in ai_text.split('\n') if line.strip()][:3] or reasons
    return {
        "symbol": pair,
        "direction": direction,
        "change": round(change, 2),
        "volume": volume,
        "confidence": confidence,
        "reasons": reasons,
        "current_price": current_price,
    }

# ── Trade Parameter Enrichment ──
def enrich_trade_params(pair_result, chat_id):
    """Add concrete trade parameters (entry, sl, tp, rrr, sizing) based on user state, balance, and session-aware risk levels."""
    state = get_state(chat_id)
    real, mock = get_balance()
    mode = state.get("trade_mode", "MOCK")
    wallet = mock if mode == "MOCK" else (real or 0)
    leverage = state.get("leverage", 28) or 28  # default 28 if not set
    margin_pct = state.get("margin", 1.0)
    direction = pair_result.get("direction", "LONG")
    current_price = pair_result.get("current_price", 0)
    if current_price <= 0:
        return pair_result

    # Detect active session from current SGT time (UTC+8)
    now_utc = datetime.now(timezone.utc)
    now_sgt = (now_utc + timedelta(hours=8)).time()
    hour_sgt = now_sgt.hour
    # Session windows (SGT): pre_london 06:00-07:00, london 16:00-20:00, ny 21:00-23:00
    if 6 <= hour_sgt < 7:
        session = "pre_london"
        base_sl_pct = 0.005   # 0.5% price move
        base_tp_pct = 0.015   # 1.5% price move → 3:1 RRR
    elif 16 <= hour_sgt < 20:
        session = "london"
        base_sl_pct = 0.005
        base_tp_pct = 0.015
    elif 21 <= hour_sgt < 23:
        session = "ny"
        base_sl_pct = 0.007   # 0.7% price move
        base_tp_pct = 0.021   # 2.1% price move → 3:1 RRR
    else:
        session = "manual"
        base_sl_pct = 0.004   # 0.4% price move
        base_tp_pct = 0.008   # 0.8% price move → 2:1 RRR

    # SL/TP are fixed price-move percentages (already scaled for leverage exposure)
    sl_distance = base_sl_pct
    tp_distance = base_tp_pct
    logger.info(f"enrich_trade_params: session={session} base_sl={base_sl_pct:.4f} base_tp={base_tp_pct:.4f}")

    # Compute entry, SL, TP
    entry = current_price
    if direction == "LONG":
        sl = entry * (1 - sl_distance)
        tp = entry * (1 + tp_distance)
    else:  # SHORT
        sl = entry * (1 + sl_distance)
        tp = entry * (1 - tp_distance)

    rrr = tp_distance / sl_distance if sl_distance > 0 else 0

    # Position sizing (using stake_amount = wallet * margin_pct/100)
    stake_amount = wallet * (margin_pct / 100)
    position_value = stake_amount * leverage
    quantity = position_value / entry

    pair_result.update({
        "entry": round(entry, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "rrr": round(rrr, 2),
        "stake_amount": round(stake_amount, 2),
        "position_value": round(position_value, 2),
        "quantity": round(quantity, 6),
        "margin_pct": margin_pct,
        "leverage": leverage,
        "session": session,
    })
    logger.info(f"enrich_trade_params result: entry={pair_result['entry']} sl={pair_result['sl']} tp={pair_result['tp']}")
    return pair_result

# ── Multi-Exchange Ticker Fetchers ──
def get_binance_ticker(symbol):
    """Fetch ticker from Binance public API (no auth). Symbol format: BTCUSDT."""
    try:
        r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            price = float(d.get("lastPrice", 0))
            change = float(d.get("priceChangePercent", 0))
            return price, change
    except Exception as e:
        logger.debug(f"Binance ticker error for {symbol}: {e}")
    return None, None

def is_pair_valid_on_bybit(pair: str) -> bool:
    """Check if pair exists as a perpetual swap on Bybit (USDT-margined linear)."""
    if not pair.endswith("/USDT"):
        logger.debug(f"Pair {pair} rejected: non-USDT quote (futures mode)")
        return False
    try:
        base = pair.split("/")[0]
        bybit_symbol = f"{base}USDT"
        data = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear", "symbol": bybit_symbol}, timeout=5)
        if data and data.get("retCode") == 0:
            result = data.get("result", {})
            list_data = result.get("list", [])
            if list_data and len(list_data) > 0:
                price = float(list_data[0].get("lastPrice", 0))
                if price > 0:
                    return True
    except Exception as e:
        logger.debug(f"Bybit validation error for {pair}: {e}")
    return False

def is_pair_valid_for_user(pair: str, user_id: int) -> bool:
    """Admin bypass: admins can use any pair without API validation."""
    if is_admin(user_id):
        return True
    return is_pair_valid_on_bybit(pair)

def get_okx_ticker(symbol):
    """Fetch ticker from OKX public API (no auth). Symbol format: BTC-USDT."""
    try:
        r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={symbol}", timeout=5)
        if r.status_code == 200:
            d = r.json()
            if d.get("code") == "0" and d.get("data"):
                data = d["data"][0]
                price = float(data.get("last", 0))
                # OKX returns 24h change as a string percentage
                change = float(data.get("change24h", 0))
                return price, change
    except Exception as e:
        logger.debug(f"OKX ticker error for {symbol}: {e}")
    return None, None

# ── Balance: BalRealMoc ──
def get_balance():
    """Return (real_balance, mock_balance) in USDT-equivalent."""
    # Real: from Bybit
    real = None
    if BYBIT_API_KEY and BYBIT_API_SECRET:
        data = bybit_signed_request("GET", "/v5/account/wallet-balance", params={"accountType": "CONTRACT"})
        if data and data.get("retCode") == 0:
            for asset in data.get("result", {}).get("list", [{}])[0].get("coin", []):
                if asset.get("coin") == "USDT":
                    real = float(asset.get("availableToWithdraw", 0) or 0)
    # Mock: from Freqtrade — sum all currency balances converted to USDT value
    mock_data = api_get("/api/v1/balance") or {}
    mock = 0.0
    currencies = mock_data.get("currencies", [])
    for curr in currencies:
        bal = float(curr.get("balance", 0) or 0)
        # If the currency is USDT, add directly; others have 'est_stake' in USDT
        if curr.get("currency") == "USDT":
            mock += bal
        else:
            mock += float(curr.get("est_stake", 0) or 0)
    if mock == 0.0:
        mock = 10000.0
    return (real, mock)

def format_balance(real, mock, mode):
    """BalRealMoc: display balance based on current mode"""
    if mode == "REAL":
        return f"${real:.3f} USDT" if real is not None else "Real: N/A"
    else:
        return f"{mock:.0f} CLUSDT"

def get_balance_display(chat_id: int) -> str:
    """Return a concise balance line for the current user state."""
    state = get_state(chat_id)
    real, mock = get_balance()
    mode = state.get("trade_mode", "MOCK")
    balance_str = format_balance(real, mock, mode)
    margin_pct = state.get("margin", 2.0)
    return f"💎 Balance: {balance_str} | Margin: {margin_pct:.1f}%"

def get_mode_header(chat_id: int) -> str:
    """Return mode indicator string: '🔵 MOCK | 🤖 SESSION' or '🔴 REAL | 🎯 MANUAL'"""
    state = get_state(chat_id)
    mode = state.get("trade_mode", "MOCK")
    trading_mode = state.get("mode", "manual")
    mode_emoji = "🤖" if trading_mode == "session" else "🎯"
    dry_emoji = "🔵" if mode == "MOCK" else "🔴"
    return f"{dry_emoji} {mode} | {mode_emoji} {trading_mode.upper()}"

def get_open_trades_count() -> int:
    """Return count of currently open trades."""
    try:
        trades = api_get("/api/v1/status") or []
        return len([t for t in trades if t.get('is_open', False)])
    except Exception:
        return 0

    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    realized_pnl = s.get("total_profit_abs", 0)
    return wins, losses, win_rate, realized_pnl


def get_stats():
    """Fetch stats from Supabase for accuracy across all sessions."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/trades",
            params={"is_open": "eq.false", "select": "profit_ratio,profit_abs"},
            headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"},
            timeout=5
        )
        trades = r.json() if r.status_code == 200 else []
        wins = sum(1 for t in trades if (t.get("profit_ratio") or 0) > 0)
        losses = sum(1 for t in trades if (t.get("profit_ratio") or 0) <= 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        pnl_abs = sum((t.get("profit_abs") or 0) for t in trades)
        pnl_pct = sum((t.get("profit_ratio") or 0) for t in trades) * 100
        return wins, losses, win_rate, pnl_abs, pnl_pct
    except Exception:
        s = api_get("/api/v1/profit") or {}
        wins = s.get("winning_trades", 0)
        losses = s.get("losing_trades", 0)
        total = wins + losses
        win_rate = (wins / total * 100) if total > 0 else 0
        return wins, losses, win_rate, s.get("profit_all_coin", 0), s.get("profit_all_percent", 0)

def format_wins():
    w, l, wr, _, __ = get_stats()
    return f"{w}/{w+l} ({wr:.0f}%)"

def format_gains():
    _, __, ___, pnl_abs, pnl_pct = get_stats()
    sign = "+" if pnl_pct >= 0 else ""
    return f"{sign}{pnl_pct:.2f}% (${pnl_abs:+,.2f})"

def get_bybit_ohlcv(symbol, interval="5", limit=100):
    """Fetch OHLCV candles from Bybit."""
    try:
        sym = symbol.replace("/USDT:USDT","USDT").replace("/","")
        r = requests.get(
            "https://api.bybit.com/v5/market/kline",
            params={"category":"linear","symbol":sym,"interval":interval,"limit":limit},
            timeout=10
        )
        if r.status_code != 200:
            return None
        raw = r.json().get("result",{}).get("list",[])
        if not raw:
            return None
        import pandas as pd
        df = pd.DataFrame(raw, columns=["timestamp","open","high","low","close","volume","turnover"])
        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        return df
    except Exception as e:
        logger.warning(f"OHLCV error {symbol}: {e}")
        return None

def get_order_book(symbol):
    """Fetch order book bid/ask ratio from Bybit."""
    try:
        sym = symbol.replace("/USDT:USDT","USDT").replace("/","")
        r = requests.get(
            "https://api.bybit.com/v5/market/orderbook",
            params={"category":"linear","symbol":sym,"limit":25},
            timeout=10
        )
        if r.status_code != 200:
            return 0.5
        data = r.json().get("result",{})
        bids = sum(float(b[1]) for b in data.get("b",[]))
        asks = sum(float(a[1]) for a in data.get("a",[]))
        total = bids + asks
        return bids/total if total > 0 else 0.5
    except Exception as e:
        logger.warning(f"Order book error {symbol}: {e}")
        return 0.5

def get_funding_rate(symbol):
    """Fetch current funding rate from Bybit."""
    try:
        sym = symbol.replace("/USDT:USDT","USDT").replace("/","")
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category":"linear","symbol":sym},
            timeout=10
        )
        if r.status_code != 200:
            return 0.0
        data = r.json().get("result",{}).get("list",[])
        if not data:
            return 0.0
        return float(data[0].get("fundingRate", 0))
    except Exception as e:
        logger.warning(f"Funding rate error {symbol}: {e}")
        return 0.0

def calculate_indicators(symbol):
    """Calculate technical indicators for a pair."""
    try:
        df = get_bybit_ohlcv(symbol, interval="5", limit=100)
        if df is None or len(df) < 20:
            return None
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]

        # EMA
        ema8 = close.ewm(span=8, adjust=False).mean().iloc[-1]
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, 0.0001)
        rsi = (100 - 100/(1+rs)).iloc[-1]

        # ATR
        tr = (high - low).rolling(14).mean()
        atr = tr.iloc[-1]
        atr_pct = (atr / close.iloc[-1]) * 100

        # Volume spike
        avg_vol = volume.rolling(20).mean().iloc[-1]
        vol_ratio = volume.iloc[-1] / avg_vol if avg_vol > 0 else 1.0

        # Current price
        current_price = close.iloc[-1]

        # Direction
        direction = "LONG" if ema8 > ema20 else "SHORT"

        # Support/Resistance
        support = low.rolling(20).min().iloc[-1]
        resistance = high.rolling(20).max().iloc[-1]

        return {
            "pair": symbol,
            "price": current_price,
            "current_price": current_price,
            "ema8": ema8, "ema20": ema20, "ema50": ema50,
            "rsi": rsi, "atr_pct": atr_pct,
            "vol_ratio": vol_ratio,
            "volume_ratio": vol_ratio,
            "trend": "LONG" if ema8 > ema20 else "SHORT",
            "direction": direction,
            "support": support,
            "resistance": resistance,
            "pct_4h": 0,
        }
    except Exception as e:
        logger.warning(f"Indicator error {symbol}: {e}")
        return None

def score_setup(ind, ob_ratio, funding):
    """Score a trading setup 0-10."""
    score = 5.0

    # Trend alignment
    if ind["ema8"] > ind["ema20"] > ind["ema50"]:
        score += 1.5
    elif ind["ema8"] < ind["ema20"] < ind["ema50"]:
        score += 1.5

    # RSI not extreme
    rsi = ind["rsi"]
    if 40 <= rsi <= 60:
        score += 0.5
    elif rsi > 75 or rsi < 25:
        score -= 1.0

    # Volume spike
    if ind["vol_ratio"] > 1.5:
        score += 1.0
    elif ind["vol_ratio"] < 0.7:
        score -= 0.5

    # Order book bias matches direction
    if ind["direction"] == "LONG" and ob_ratio > 0.55:
        score += 0.5
    elif ind["direction"] == "SHORT" and ob_ratio < 0.45:
        score += 0.5

    # Funding rate
    if abs(funding) > 0.001:
        score -= 0.5

    # ATR filter
    if ind["atr_pct"] < 0.3:
        score -= 1.0

    return round(min(max(score, 0), 10), 1)

def format_scan_result(ind, score, ob_ratio, funding):
    """Format scan result for Telegram."""
    pair_clean = ind["pair"].replace("/USDT:USDT","")
    direction = ind["direction"]
    price = ind["price"]
    rsi = ind["rsi"]
    atr = ind["atr_pct"]
    vol = ind["vol_ratio"]

    # SL/TP
    sl_pct = 0.008
    tp_pct = sl_pct * 2.5
    if direction == "LONG":
        sl = price * (1 - sl_pct)
        tp = price * (1 + tp_pct)
    else:
        sl = price * (1 + sl_pct)
        tp = price * (1 - tp_pct)

    emoji = "🟢" if direction == "LONG" else "🔴"
    bar = "█" * int(score) + "░" * (10 - int(score))

    return (
        f"{emoji} *{pair_clean}* {direction}\n"
        f"Score: `{score}/10` {bar}\n"
        f"Price: `${price:,.4f}`\n"
        f"RSI: `{rsi:.1f}` | ATR: `{atr:.1f}%` | Vol: `{vol:.1f}x`\n"
        f"SL: `${sl:,.4f}` | TP: `${tp:,.4f}`\n"
        f"OB Ratio: `{ob_ratio:.2f}` | Funding: `{funding:.4f}`\n"
    )


def get_bybit_top_movers(limit=20):
    """Fetch top movers by volume from Bybit."""
    try:
        r = requests.get(
            "https://api.bybit.com/v5/market/tickers",
            params={"category": "linear"},
            timeout=10
        )
        if r.status_code != 200:
            return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
        data = r.json().get("result", {}).get("list", [])
        # Filter: USDT pairs only, price > $1, sort by 24h volume
        filtered = [
            t for t in data
            if t.get("symbol", "").endswith("USDT")
            and not any(x in t.get("symbol","") for x in ["USDC","DAI","BUSD","TUSD"])
            and float(t.get("lastPrice", 0)) >= 1.0
        ]
        filtered.sort(key=lambda x: float(x.get("turnover24h", 0)), reverse=True)
        # Convert to freqtrade pair format
        pairs = []
        for t in filtered[:limit]:
            sym = t["symbol"]
            pair = sym[:-4] + "/USDT:USDT"
            pairs.append(pair)
        return pairs if pairs else ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
    except Exception as e:
        logger.warning(f"Bybit top movers error: {e}")
        return ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT"]


def call_stepfun_skill(prompt, retries=2):
    """AI scoring via Groq (llama-3.3-70b) — drop-in replacement for StepFun."""
    import os
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        logger.error("GROQ_API_KEY not set")
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 500,
    }
    for attempt in range(retries):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers, timeout=30
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            else:
                logger.warning(f"Groq API error {r.status_code}: {r.text[:200]}")
        except Exception as e:
            logger.warning(f"Groq attempt {attempt+1} failed: {e}")
    return None
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": "You are an expert crypto scalping analyst. Provide concise TA with confidence %% (80-90) and RRR."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    for attempt in range(retries + 1):
        try:
            logger.debug(f"StepFun call attempt {attempt+1}/{retries+1} for: {prompt[:60]}...")
            r = requests.post("https://api.groq.com/openai/v1/chat/completions", json=payload, headers=headers, timeout=30)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            logger.warning(f"StepFun HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            logger.error(f"StepFun error: {e}")
    return None


def ai_scan_pairs(custom_pairs=None, chat_id=None):
    """
    Enhanced Scan Logic:
    1. Get top movers from Bybit (baseline: BTC ETH SOL BNB + top 3 extras)
       Filters: turnover >$100M, price >$0.10, 4H move ±15%, volume spike >2× avg
    2. For each, compute 1H/4H indicators (trend, volume ratio, ATR%, S/R)
    3. Parallel StepFun scoring (top 8 candidates, 10s timeout, 1 retry)
    4. Sort by AI score, take top 4
    5. Enrich trade params (entry/SL/TP/sizing)
    6. Return list of results
    """
    # STEP 1 — Get top movers
    pairs_to_scan = custom_pairs if custom_pairs else get_bybit_top_movers(limit=20)
    logger.info(f"ai_scan_pairs: scanning {len(pairs_to_scan)} top movers")
    # Phase 1: Fetch indicators for all pairs (fast)
    candidates = []
    for pair in pairs_to_scan[:20]:
        if "/" not in pair:
            pair = f"{pair}/USDT"
        ind = calculate_indicators(pair)
        if not ind or ind.get("current_price", 0) <= 0:
            logger.debug(f"Skipping {pair}: no indicator data")
            continue
        # Compute 4H change directly
        pct_4h = ind.get("pct_4h", 0)
        try:
            bybit_sym = pair.replace("/", "").upper()
            k4 = bybit_signed_request(
                "GET", "/v5/market/kline",
                params={"category": "linear", "symbol": bybit_sym, "interval": "240", "limit": 2},
                timeout=5
            )
            if k4 and k4.get("retCode") == 0:
                klist = k4.get("result", {}).get("list", [])
                if len(klist) >= 2:
                    open_4h = float(klist[-1][4])   # oldest close
                    close_4h = float(klist[0][4])    # newest close
                    pct_4h = (close_4h - open_4h) / open_4h * 100 if open_4h else 0
        except Exception:
            pass
        candidates.append({
            "symbol": pair,
            "pct_4h": pct_4h,
            "vol_ratio": ind.get("volume_ratio", 1),
            "trend": ind.get("trend", "UNKNOWN"),
            "atr_pct": ind.get("atr_pct", 0),
            "current_price": ind.get("current_price", 0),
            "support": ind.get("support"),
            "resistance": ind.get("resistance"),
        })
    if not candidates:
        logger.warning("No valid candidates after indicator fetch")
        return []
    # Phase 2: Pre-filter - remove unsafe pairs, rank by win potential
    safe_candidates = []
    for c in candidates:
        # Skip if ATR too low (no movement)
        if c.get("atr_pct", 0) < 0.3:
            continue
        # Skip if volume ratio too low (no interest)
        if c.get("vol_ratio", 1) < 0.5:
            continue
        # Skip if price too low (pump risk)
        if c.get("current_price", 0) < 1.0:
            continue
        # Win potential score: volume + momentum + volatility
        vol_score = min(c.get("vol_ratio", 1) * 2, 4)
        momentum_score = min(abs(c.get("pct_4h", 0)) * 0.5, 3)
        atr_score = min(c.get("atr_pct", 0) * 0.5, 2)
        trend_score = 1 if c.get("trend") in ["LONG","SHORT"] else 0
        c["heuristic"] = vol_score + momentum_score + atr_score + trend_score
        safe_candidates.append(c)
    
    if not safe_candidates:
        safe_candidates = candidates  # fallback
    
    safe_candidates.sort(key=lambda x: x["heuristic"], reverse=True)
    top_candidates = safe_candidates[:8]
    logger.info(f"Selected {len(top_candidates)} candidates for StepFun ranking")
    # Phase 3: Parallel StepFun scoring
    def score_candidate(c):
        prompt = (
            f"Scalp analysis for {c['symbol']}:"
            f" 4H move: {c['pct_4h']:.1f}%, Volume ratio: {c['vol_ratio']:.1f}x,"
            f" Trend: {c['trend']}, ATR: {c['atr_pct']:.1f}%."
            f" Rate 1-10 for scalping opportunity."
            f" Give: score, direction (LONG/SHORT), confidence % (80-90), entry strategy (market/limit), key support/resistance levels."
        )
        ai_text = call_stepfun_skill(prompt, retries=1)
        logger.info(f"StepFun raw: {str(ai_text)[:300]}")
        score = 5
        direction = "LONG" if c["pct_4h"] >= 0 else "SHORT"
        confidence = max(80, min(89, int(85 + abs(c["pct_4h"])*0.5)))
        entry_strategy = "market"
        # Trend strength: normalize 4H move magnitude (5% move = 1.0)
        trend_strength = min(1.0, abs(c["pct_4h"]) / 5)
        reasons = ["Volume spike", "AI signal"]
        if ai_text:
            # Parse score — new multi-pattern for step-3.5-flash
            patterns = [
                r'score[\s:]*([1-9]|10)',
                r'([1-9]|10)[\s]*/[\s]*10',
                r'rating[\s:]*([1-9]|10)',
                r'\b([1-9]|10)\b.*(?:out of|\/)\s*10',
            ]
            for pattern in patterns:
                m = re.search(pattern, ai_text, re.IGNORECASE)
                if m:
                    score = int(m.group(1))
                    break
            # Parse direction
            if 'short' in ai_text.lower(): direction = 'SHORT'
            elif 'long' in ai_text.lower(): direction = 'LONG'
            # Parse confidence
            conf_patterns = [
                r'confidence[\s:]+(\d{2,3})%?',
                r'conf[\s:]+(\d{2,3})',
                r'\b(\d{2,3})%\b',
            ]
            for pat in conf_patterns:
                m = re.search(pat, ai_text, re.IGNORECASE)
                if m:
                    try:
                        c_val = int(m.group(1))
                        if 50 <= c_val <= 99:
                            confidence = c_val
                            break
                    except: pass
            # Parse entry strategy
            if 'limit' in ai_text.lower(): entry_strategy = 'limit'
            # Extract reasons (skip markdown headers, pick first 3 meaningful lines)
            reasons = []
            for line in ai_text.split('\n'):
                line = line.strip('- *•').strip()
                if line and len(line) > 5 and not line.startswith('**') and not line.startswith('_'):
                    reasons.append(line)
                if len(reasons) >= 3:
                    break
            if not reasons:
                reasons = ['AI analysis', c['trend'], f"Vol {c['vol_ratio']:.1f}x"]
        return {
            "symbol": c["symbol"],
            "direction": direction,
            "change": round(c["pct_4h"], 2),
            "volume_ratio": round(c["vol_ratio"], 2),
            "confidence": confidence,
            "reasons": reasons,
            "current_price": c["current_price"],
            "ai_score": score,
            "entry_strategy": entry_strategy,
            "atr_pct": c["atr_pct"],
            "support": c.get("support"),
            "resistance": c.get("resistance"),
            "trend_strength": round(trend_strength, 2),
        }
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_c = {executor.submit(score_candidate, c): c for c in top_candidates}
        for future in concurrent.futures.as_completed(future_to_c):
            c = future_to_c[future]
            try:
                result = future.result(timeout=35)
                if chat_id:
                    result = enrich_trade_params(result, chat_id)
                results.append(result)
                logger.info(f"Scan {c['symbol']}: score={result['ai_score']}, dir={result['direction']}, conf={result['confidence']}")
            except Exception as e:
                logger.error(f"StepFun scoring failed for {c['symbol']}: {e}")
                fallback = {
                    "symbol": c["symbol"], "direction": "LONG" if c["pct_4h"]>=0 else "SHORT",
                    "change": round(c["pct_4h"],2), "volume_ratio": round(c["vol_ratio"],2),
                    "confidence": max(80, min(89, int(85+abs(c["pct_4h"])*0.5))),
                    "reasons": ["Fallback"], "current_price": c["current_price"],
                    "ai_score": 5, "entry_strategy": "market", "atr_pct": c["atr_pct"],
                    "support": c.get("support"), "resistance": c.get("resistance"),
                    "trend_strength": round(min(1.0, abs(c["pct_4h"]) / 5), 2),
                }
                if chat_id: fallback = enrich_trade_params(fallback, chat_id)
                results.append(fallback)
    results.sort(key=lambda x: x.get("ai_score", 0), reverse=True)
    top4 = results[:4]
    logger.info(f"ai_scan_pairs complete: returning {len(top4)} results")
    return top4

# ── Scan Execution & Logging ──
async def log_trade_to_channel(bot, trade_data: dict, trade_id):
    """Send executed trade notification to @RightclawTrade channel."""
    channel = os.getenv("RIGHTCLAW_CHANNEL", "@RightclawTrade")
    p = trade_data
    text = (
        f"🚨 **NEW TRADE**\n\n"
        f"Pair: {p['symbol']} {p['direction']}\n"
        f"Entry: ${p.get('entry',0):,.4f}\n"
        f"SL: ${p.get('sl',0):,.4f}  |  TP: ${p.get('tp',0):,.4f}\n"
        f"Confidence: {p.get('confidence',0)}%  |  AI Score: {p.get('ai_score',0)}/10\n"
        f"Mode: MANUAL (scan)"
    )
    try:
        await bot.send_message(chat_id=channel, text=text, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Channel log failed: {e}")

def save_position(trade_data: dict, trade_id):
    """Append executed trade to user_data/positions.json."""
    path = Path(__file__).parent.parent / "user_data" / "positions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "pair": trade_data.get('symbol'),
        "direction": trade_data.get('direction'),
        "entry_price": trade_data.get('entry'),
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "sl": trade_data.get('sl'),
        "tp": trade_data.get('tp'),
        "confidence": trade_data.get('confidence'),
        "ai_score": trade_data.get('ai_score'),
        "mode": "manual",
        "trade_id": trade_id,
    }
    try:
        if path.exists():
            with open(path, "r+", encoding="utf-8") as f:
                data = json.load(f)
                data.append(entry)
                f.seek(0); f.truncate()
                json.dump(data, f, indent=2)
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump([entry], f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save position: {e}")

async def exec_confirm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Direct execution from scan result: forcebuy and confirm."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("⏳ Executing...")
    chat_id = q.message.chat_id
    symbol = q.data.split("_", 2)[2]  # exec_confirm_BTC/USDT
    scan_results = user_state.get(chat_id, {}).get("scan_results", {})
    p = scan_results.get(symbol)
    if not p:
        await q.edit_message_text("❌ Scan data expired. Run /scan again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        return
    user_id = q.from_user.id
    if not is_pair_valid_for_user(p['symbol'], user_id):
        await q.edit_message_text(
            f"❌ Pair not available on exchange.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]])
        )
        return
    # Block meme coins and commodities
    BLOCKED = {
        "FARTCOIN","BONK","PEPE","SHIB","DOGE","FLOKI","WIF","MEME",
        "DOG","RATS","SATS","PIZZA","CL","GC","SI","NG","XAUT","PAXG"
    }
    base = p["symbol"].replace("/USDT","").replace(":USDT","").upper()
    if base in BLOCKED:
        await q.edit_message_text(
            f"⛔ {p['symbol']} is blocked\n\nMeme coins and commodities are not allowed.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]])
        )
        return

    # Prepare forcebuy
    exchange_pair = p["symbol"]
    if exchange_pair.endswith("/USDT"):
        exchange_pair = exchange_pair + ":USDT"
    payload = {"pair": exchange_pair, "side": p["direction"].lower()}
    try:
        r = requests.post(f"{API_URL}/api/v1/forcebuy", json=payload, auth=(API_USER, API_PASS), timeout=10)
        if r.status_code in (200, 201):
            resp = r.json()
            trade_id = resp.get("trade_id", "unknown")
            # Log to channel and save position
            await log_trade_to_channel(ctx.bot, p, trade_id)
            save_position(p, trade_id)
            await q.edit_message_text(
                f"✅ **Trade Executed**\n\nPair: {p['symbol']} {p['direction']}\nTrade ID: `{trade_id}`\n\nView in /positions",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📊 POSITIONS", callback_data="positions")]])
            )
        else:
            await q.edit_message_text(
                f"❌ Execution failed: {r.status_code} {r.text[:150]}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 RETRY", callback_data=f"exec_confirm_{symbol}")],
                    [InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]
                ])
            )
    except Exception as e:
        await q.edit_message_text(
            f"❌ Error: {str(e)[:100]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 RETRY", callback_data=f"exec_confirm_{symbol}")],
                [InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]
            ])
        )

async def skip_pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Skip (delete) a scan result message and clean up."""
    q = update.callback_query
    await q.answer("⏭ Skipped")
    symbol = q.data.split("_", 1)[1]  # skip_BTC/USDT
    chat_id = q.message.chat_id
    # Remove from scan_results
    if chat_id in user_state and "scan_results" in user_state[chat_id]:
        user_state[chat_id]["scan_results"].pop(symbol, None)
    # Delete message
    try:
        await q.message.delete()
    except Exception as e:
        logger.debug(f"Skip delete failed: {e}")
        await q.edit_message_text("⏭ Skipped", reply_markup=None)

# ── Session Mode Callbacks ──
async def session_approve_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle APPROVE ALL button from prescan alert."""
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    # Extract session key from callback data: session_approve_<session_key>
    session_key = q.data.replace("session_approve_", "")
    # Acknowledge immediately
    await q.edit_message_text(
        f"✅ **Approved** — executing {session_key.replace('_', ' ').title()} setups...",
        reply_markup=None,
        parse_mode="Markdown"
    )
    # Spawn executor as subprocess (non-blocking)
    import asyncio, subprocess, sys
    from pathlib import Path
    script = Path(__file__).parent.parent / "scripts" / "session_executor.py"
    cmd = [sys.executable, str(script), "approve", session_key, str(chat_id)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        # Don't wait — let it run and send its own summary
        asyncio.create_task(proc.wait())
    except Exception as e:
        logger.error(f"Failed to start session executor: {e}")
        await ctx.bot.send_message(chat_id=chat_id, text=f"❌ Executor start failed: {e}")

async def session_skip_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle SKIP SESSION button from prescan alert."""
    q = update.callback_query
    await q.answer()
    session_key = q.data.replace("session_skip_", "")
    await q.edit_message_text(
        f"⏭ **Skipped** — {session_key.replace('_', ' ').title()} session cancelled.",
        reply_markup=None,
        parse_mode="Markdown"
    )
    # Run skip executor
    import asyncio, subprocess, sys
    from pathlib import Path
    script = Path(__file__).parent.parent / "scripts" / "session_executor.py"
    cmd = [sys.executable, str(script), "skip", session_key, str(q.message.chat_id)]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        asyncio.create_task(proc.wait())
    except Exception as e:
        logger.error(f"Failed to start session executor: {e}")

# ── UI Builders ──
def mode_button(mode):
    label = "🔴 REAL" if mode == "REAL" else "🟢 MOCK"
    return InlineKeyboardButton(f"⚙️ {label}", callback_data="toggle_mode")

def balance_button(mode):
    real, mock = get_balance()
    bal = format_balance(real, mock, mode)
    return InlineKeyboardButton(f"💵 {bal}", callback_data="show_balance")

def wins_button():
    return InlineKeyboardButton(f"🏆 {format_wins()}", callback_data="show_stats")

def gains_button():
    return InlineKeyboardButton(f"💰 {format_gains()}", callback_data="show_gains")

def lev_margin_buttons(state):
    lev = state["leverage"]
    mar = state["margin"]
    # Leverage: +10 / -10
    lev_plus = InlineKeyboardButton("➕ Leverage", callback_data="lev_up")
    lev_label = InlineKeyboardButton(f"⚡ {lev}x", callback_data="lev_show")
    lev_minus = InlineKeyboardButton("➖ Leverage", callback_data="lev_down")
    # Margin: +1% / -1%
    mar_plus = InlineKeyboardButton("➕ Margin", callback_data="mar_up")
    mar_label = InlineKeyboardButton(f"🎯 {mar}%", callback_data="mar_show")
    mar_minus = InlineKeyboardButton("➖ Margin", callback_data="mar_down")
    return [ [lev_plus, lev_label, lev_minus], [mar_plus, mar_label, mar_minus] ]

def grid_2x2(pairs):
    """Return 2x2 grid of pair buttons"""
    buttons = []
    for i in range(0, 4, 2):
        row = []
        for p in pairs[i:i+2]:
            row.append(InlineKeyboardButton(p["symbol"], callback_data=f"pair_{p['symbol']}"))
        buttons.append(row)
    return buttons

# ── Handlers ──
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    news = get_market_news()
    bal_line = get_balance_display(chat_id)
    kb = [
        [wins_button(), gains_button()],
        [InlineKeyboardButton("📈 TRADE MENU", callback_data="trade_menu")],
        [InlineKeyboardButton("📊 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("🧠 MACRO INTEL", callback_data="market_now")],
    ]
    await update.message.reply_text(f"🏠 **Clawmimoto Command Center**\n\n{bal_line}\n\n{news}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def main_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    # Cancel any auto-refresh task (user left position detail)
    chat_id = update.effective_chat.id
    if chat_id in position_refresh_tasks:
        position_refresh_tasks[chat_id]["task"].cancel()
        del position_refresh_tasks[chat_id]
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state.get('trade_mode','MOCK'))
    open_count = get_open_trades_count()
    mode_header = get_mode_header(chat_id)
    # Build new main menu
    # Mode labels
    trade_mode = state.get("trade_mode", "MOCK")
    trading_mode = state.get("trading_mode", "manual")
    mock_label = "🟢 MOCK" if trade_mode == "MOCK" else "🔴 REAL"
    session_label = "🤖 SESSION" if trading_mode == "session" else "🎯 MANUAL"
    open_label = f"📊 {open_count} Open Trade{'s' if open_count != 1 else ''}"

    text = (
        "╔══════════════════════╗\n"
        "║  🦞 CLAWMIMOTO       ║\n"
        "║  Trading Terminal    ║\n"
        "╚══════════════════════╝\n\n"
        f"{mock_label}  |  {session_label}\n\n"
        f"💰 {bal}   {open_label}"
    )
    kb = [
        # Toggle switches — clickable
        [InlineKeyboardButton(f"⚙️ {mock_label}", callback_data="toggle_mode"),
         InlineKeyboardButton(f"🔄 {session_label}", callback_data="toggle_trading_mode")],
        # Main actions
        [InlineKeyboardButton("🤖 AI SCAN", callback_data="ai_scan"),
         InlineKeyboardButton("📈 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("📋 HISTORY", callback_data="history"),
         InlineKeyboardButton("💰 BALANCE", callback_data="balance")],
        [InlineKeyboardButton("📡 SOCIALS", callback_data="socials"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def toggle_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["trade_mode"] = "REAL" if state["trade_mode"] == "MOCK" else "MOCK"
    _save_state()
    await trade_menu_cb(update, ctx)


async def set_trade_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    action = q.data
    if action == "set_mock":
        state["trade_mode"] = "MOCK"
        await q.answer("✅ Switched to MOCK mode", show_alert=True)
    elif action == "set_real":
        state["trade_mode"] = "REAL"
        await q.answer("🔴 Switched to REAL mode", show_alert=True)
    elif action == "set_manual":
        state["trading_mode"] = "manual"
        await q.answer("🎯 Manual mode active", show_alert=True)
    elif action == "set_session":
        state["trading_mode"] = "session"
        await q.answer("🤖 Session mode active", show_alert=True)
    await settings_cb(update, ctx)

async def socials_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    text = (
        "📡 *FIND US*\n\n"
        "🐦 *X / Twitter*\n"
        "Coming soon — @ClawTrader\n\n"
        "📬 *Telegram Channel*\n"
        "@RightclawTrade — live signals\n\n"
        "🎵 *TikTok*\n"
        "Coming soon\n\n"
        "📊 *Dashboard*\n"
        "clawmimoto-backtests.vercel.app\n\n"
        "🌐 *Website*\n"
        "clawtrader-landing.vercel.app"
    )
    kb = [[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="MarkdownV2")

async def toggle_trading_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    current = state.get("trading_mode", "manual")
    state["trading_mode"] = "session" if current == "manual" else "manual"
    new_mode = state["trading_mode"]
    await q.answer(f"Switched to {new_mode.upper()} mode", show_alert=True)
    await trade_menu_cb(update, ctx)

async def show_balance_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    mode = state.get("trade_mode", "MOCK")
    currency = "CLUSDT" if mode == "MOCK" else "USDT"

    # Fetch balance data from Freqtrade API
    balance_data = api_get("/api/v1/balance") or {}
    # Parse free and total from balance_data (handle both top-level and currencies list)
    free = 0.0
    total = 0.0
    # Try top-level keys first
    if "free" in balance_data:
        free = float(balance_data.get("free", 0) or 0)
    if "total" in balance_data:
        total = float(balance_data.get("total", 0) or 0)
    # If currencies list present, sum available/est_stake
    currencies = balance_data.get("currencies", [])
    if currencies:
        for curr in currencies:
            # Use 'available' if present, else 'balance'
            curr_free = float(curr.get("available", curr.get("balance", 0) or 0))
            # Use 'est_stake' if present, else 'balance'
            curr_total = float(curr.get("est_stake", curr.get("balance", 0) or 0))
            free += curr_free
            total += curr_total
    starting = float(balance_data.get("starting_capital", 0) or 0)

    # Fetch unrealized PnL from open trades
    trades = api_get("/api/v1/status") or []
    unrealized = sum(float(t.get("profit_abs", 0) or 0) for t in trades if t.get('is_open', False))
    unrealized_pct = (unrealized / starting * 100) if starting else 0.0
    total_with_pnl = free + unrealized
    overall_pnl_pct = ((total_with_pnl - starting) / starting * 100) if starting else 0.0
    open_count = len([t for t in trades if t.get('is_open', False)])

    # Determine sign emoji
    unrealized_sign = "➕" if unrealized >= 0 else "➖"

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 BALANCE\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Available: ${free:.2f} {currency}\n"
        f"Unrealized: {unrealized_sign}${abs(unrealized):.2f} ({unrealized_pct:+.2f}%)\n"
        f"Total w/ PnL: ${total_with_pnl:.2f} {currency}\n"
        f"Started: ${starting:.2f} {currency}\n"
        f"Overall P&L: {overall_pnl_pct:+.2f}%\n"
        f"Open Trades: {open_count}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))

async def show_stats_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    w, l, wr, pnl = get_stats()
    text = f"📊 **Statistics**\n\nWin/Loss: {w}/{l} ({wr:.0f}%)\nRealized PNL: ${pnl:,.2f}"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main")]]))

async def show_gains_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    _, _, _, pnl = get_stats()
    pnl_pct = (pnl / 10000 * 100) if pnl else 0
    text = f"💰 **Realized Gains**\n\n{pnl_pct:+.1f}%\n${pnl:,.2f}"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main")]]))

# ── News & Settings Wrappers ─-


async def cooknow_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """CookNow macro scenario simulator — admin only."""
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    if chat_id != 7093901111:
        await q.answer("Access denied.", show_alert=True)
        return
    await q.edit_message_text("CookNow: Firing up the kitchen... Generating macro scenarios...", parse_mode="Markdown")
    import asyncio, subprocess, sys
    from pathlib import Path
    script = Path("/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/scripts/cooknow.py")
    env = {**__import__("os").environ, "TELEGRAM_CHAT_ID": str(chat_id)}
    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(script), str(chat_id), "admin",
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env
    )
    asyncio.create_task(proc.wait())
    # Return to trade menu
    await trade_menu_cb(update, ctx)

async def toggle_macro_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Toggle MACRO Sentinel mode ON/OFF."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    macro_on = not state.get("macro_on", False)
    state["macro_on"] = macro_on

    if macro_on:
        await q.answer("🧠 MACRO ON — Sentinel running in background", show_alert=True)
        # Run Sentinel in background silently
        import asyncio, subprocess, sys
        from pathlib import Path
        script = Path("/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/scripts/sentinel_agent.py")
        env = {**__import__('os').environ, "TELEGRAM_CHAT_ID": str(chat_id)}
        proc = await asyncio.create_subprocess_exec(
            sys.executable, str(script), "report",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env
        )
        asyncio.create_task(proc.wait())
    else:
        await q.answer("🔴 MACRO OFF — Normal mode active", show_alert=True)

    # Refresh full trade menu
    await trade_menu_cb(update, ctx)

async def show_news_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    news_text = get_market_news()
    await q.edit_message_text(
        news_text,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")]]),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    tab = state.get("settings_tab", "manual")
    await _render_settings(q, chat_id, state, tab)

async def _render_settings(q, chat_id, state, tab="manual"):
    trade_mode = state.get("trade_mode", "MOCK")
    leverage = state.get("leverage", 20)
    margin = state.get("margin", 2.0)
    sutamm = state.get("sutamm", False)
    sl_pct = state.get("sl_pct", 0.8)
    tp_pct = state.get("tp_pct", 2.0)
    session_lev = state.get("session_leverage", 20)
    session_margin = state.get("session_margin", 2.0)
    mock_icon = "✅" if trade_mode == "MOCK" else "⬜"
    real_icon = "✅" if trade_mode == "REAL" else "⬜"
    manual_tab = "🔵 MANUAL" if tab == "manual" else "MANUAL"
    session_tab = "🔵 SESSION" if tab == "session" else "SESSION"
    sutamm_icon = "🟢 ON" if sutamm else "🔴 OFF"

    if tab == "manual":
        text = (
            "⚙️ *SETTINGS - MANUAL TRADE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*Trade Mode*\n"
            f"  {mock_icon} MOCK (dry run)   {real_icon} REAL (live)\n\n"
            "*Risk Controls*\n"
            f"  ⚡ Leverage: `{leverage}x`\n"
            f"  🎯 Margin: `{margin:.1f}%`\n"
            f"  🛑 Stop Loss: `{sl_pct:.1f}%`\n"
            f"  ✅ Take Profit: `{tp_pct:.1f}%`\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ _Changing values above recommended increases risk._"
        )
        kb = [
            [InlineKeyboardButton("📋 " + manual_tab, callback_data="settings_tab_manual"),
             InlineKeyboardButton("🤖 " + session_tab, callback_data="settings_tab_session")],
            [InlineKeyboardButton(mock_icon + " MOCK", callback_data="set_mock"),
             InlineKeyboardButton(real_icon + " REAL", callback_data="set_real")],
            [InlineKeyboardButton("➖", callback_data="lev_down"),
             InlineKeyboardButton("⚡ " + str(leverage) + "x", callback_data="noop"),
             InlineKeyboardButton("➕", callback_data="lev_up")],
            [InlineKeyboardButton("➖", callback_data="mar_down"),
             InlineKeyboardButton("🎯 " + str(margin) + "%", callback_data="noop"),
             InlineKeyboardButton("➕", callback_data="mar_up")],
            [InlineKeyboardButton("➖ SL", callback_data="sl_down"),
             InlineKeyboardButton("🛑 " + str(sl_pct) + "%", callback_data="noop"),
             InlineKeyboardButton("➕ SL", callback_data="sl_up")],
            [InlineKeyboardButton("➖ TP", callback_data="tp_down"),
             InlineKeyboardButton("✅ " + str(tp_pct) + "%", callback_data="noop"),
             InlineKeyboardButton("➕ TP", callback_data="tp_up")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")],
        ]
    else:
        text = (
            "⚙️ *SETTINGS - SESSION TRADE*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "*SUTAMM - Shut Up and Take My Money*\n"
            f"  Auto-execute session trades: *{sutamm_icon}*\n"
            "  _When ON: trades execute automatically_\n"
            "  _without your approval_\n\n"
            "*Session Risk Controls*\n"
            f"  ⚡ Leverage: `{session_lev}x` _(recommended: 20x)_\n"
            f"  🎯 Margin: `{session_margin:.1f}%` _(recommended: 2%)_\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ _SUTAMM executes trades automatically._\n"
            "_Only enable if you trust the strategy._"
        )
        kb = [
            [InlineKeyboardButton("📋 " + manual_tab, callback_data="settings_tab_manual"),
             InlineKeyboardButton("🤖 " + session_tab, callback_data="settings_tab_session")],
            [InlineKeyboardButton("🔄 SUTAMM: " + sutamm_icon, callback_data="toggle_sutamm")],
            [InlineKeyboardButton("➖", callback_data="sess_lev_down"),
             InlineKeyboardButton("⚡ " + str(session_lev) + "x", callback_data="noop"),
             InlineKeyboardButton("➕", callback_data="sess_lev_up")],
            [InlineKeyboardButton("➖", callback_data="sess_mar_down"),
             InlineKeyboardButton("🎯 " + str(session_margin) + "%", callback_data="noop"),
             InlineKeyboardButton("➕", callback_data="sess_mar_up")],
            [InlineKeyboardButton("♻️ Reset to Safe Defaults", callback_data="session_defaults")],
            [InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")],
        ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def settings_tab_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    tab = "session" if "session" in q.data else "manual"
    state["settings_tab"] = tab
    await _render_settings(q, chat_id, state, tab)

async def toggle_sutamm_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    current = state.get("sutamm", False)
    if not current:
        await q.answer("⚠️ SUTAMM enabled! Trades will execute automatically.", show_alert=True)
    else:
        await q.answer("SUTAMM disabled. Manual approval required.", show_alert=False)
    state["sutamm"] = not current
    _save_state()
    await _render_settings(q, chat_id, state, "session")

async def session_defaults_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["session_leverage"] = 20
    state["session_margin"] = 2.0
    state["sutamm"] = False
    await q.answer("✅ Reset to safe defaults", show_alert=False)
    await _render_settings(q, chat_id, state, "session")

async def sl_tp_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    action = q.data
    if action == "sl_up":
        state["sl_pct"] = round(min(state.get("sl_pct", 0.8) + 0.1, 3.0), 1)
    elif action == "sl_down":
        state["sl_pct"] = round(max(state.get("sl_pct", 0.8) - 0.1, 0.3), 1)
    elif action == "tp_up":
        state["tp_pct"] = round(min(state.get("tp_pct", 2.0) + 0.1, 10.0), 1)
    elif action == "tp_down":
        state["tp_pct"] = round(max(state.get("tp_pct", 2.0) - 0.1, 0.5), 1)
    elif action == "sess_lev_up":
        new_lev = state.get("session_leverage", 20) + 5
        if new_lev > 20:
            await q.answer("⚠️ Above 20x increases liquidation risk significantly!", show_alert=True)
        state["session_leverage"] = min(new_lev, 50)
    elif action == "sess_lev_down":
        state["session_leverage"] = max(state.get("session_leverage", 20) - 5, 5)
    elif action == "sess_mar_up":
        new_mar = round(state.get("session_margin", 2.0) + 0.5, 1)
        if new_mar > 5.0:
            await q.answer("⚠️ High margin % means larger position size - higher risk!", show_alert=True)
        state["session_margin"] = min(new_mar, 20.0)
    elif action == "sess_mar_down":
        state["session_margin"] = round(max(state.get("session_margin", 2.0) - 0.5, 0.5), 1)
    tab = state.get("settings_tab", "manual")
    await _render_settings(q, chat_id, state, tab)


# ── Market Now ──

# ── Market Snapshot Builder (used by button & cron job) ──
def fetch_market_data():
    pairs = [
        ("BTC", "BTCUSDT", "BTCUSDT", "BTC-USDT", "bitcoin"),
        ("ETH", "ETHUSDT", "ETHUSDT", "ETH-USDT", "ethereum"),
        ("SOL", "SOLUSDT", "SOLUSDT", "SOL-USDT", "solana"),
        ("BNB", "BNBUSDT", "BNBUSDT", "BNB-USDT", "binancecoin"),
    ]
    lines = []
    sources = []
    for label, bybit_sym, binance_sym, okx_sym, cg_id in pairs:
        price, change, source = None, None, None
        # Bybit
        try:
            ticker = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear", "symbol": bybit_sym})
            if ticker and ticker.get("retCode") == 0:
                d = ticker["result"]["list"][0]
                price, change = float(d["lastPrice"]), float(d.get("price24hPcnt", 0))
                source = "Bybit"
        except Exception:
            pass
        # Binance
        if price is None:
            price, change = get_binance_ticker(binance_sym)
            if price:
                source = "Binance"
        # OKX
        if price is None:
            price, change = get_okx_ticker(okx_sym)
            if price:
                source = "OKX"
        # CoinGecko
        if price is None:
            price, change = get_coingecko_ticker(cg_id)
            if price:
                source = "CoinGecko"
        # Format
        if price is not None:
            lines.append(f"{label}: ${price:,.2f} ({change:+.2f}%)")
            sources.append(source)
        else:
            lines.append(f"{label}: ERROR")
    return "\n".join(lines), ", ".join(set(sources)) if sources else "None"

def get_market_news():
    """Fetch fresh crypto news — random from top 5, max 6hr old."""
    import random
    from datetime import timezone
    feeds = [
        ("https://cointelegraph.com/rss/tag/bitcoin", "CT"),
        ("https://cointelegraph.com/rss/tag/markets", "CT Markets"),
        ("https://feeds.coindesk.com/coindesk/bitcoin", "CoinDesk"),
        ("https://decrypt.co/feed", "Decrypt"),
        ("https://theblock.co/feed", "The Block"),
    ]
    random.shuffle(feeds)
    articles = []
    now = datetime.now(timezone.utc)
    for url, source in feeds:
        try:
            d = feedparser.parse(url)
            if d.entries:
                # Pick random from top 5 entries
                pool = d.entries[:5]
                random.shuffle(pool)
                for entry in pool:
                    title = entry.get('title', '').strip()
                    link = entry.get('link', '').strip()
                    # Freshness check — skip if older than 6 hours
                    published = entry.get('published_parsed')
                    if published:
                        import calendar
                        pub_ts = calendar.timegm(published)
                        age_hrs = (now.timestamp() - pub_ts) / 3600
                        if age_hrs > 6:
                            continue
                    # Strip UTM
                    if '?' in link and 'utm_' in link:
                        link = link.split('?')[0]
                    if title and link:
                        articles.append((title, link, source))
                        break
        except Exception as e:
            logger.debug(f"RSS fetch error from {url}: {e}")
    # Deduplicate by title and limit to 4
    seen = set()
    uniq = []
    for title, link, source in articles:
        key = title.lower()
        if key not in seen:
            seen.add(key)
            uniq.append((title, link))
    uniq = uniq[:4]

    if not uniq:
        # Fallback placeholder if all feeds fail
        return (
            "📢 *Market Pulse - " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*\n\n"
            "• (News feeds temporarily unavailable - RSS error)\n"
        )

    # Format: title + [Source](link) on same line
    lines = [f"• {title} [Source]({link})" for title, link in uniq]
    header = "📢 *Market Pulse - " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*"
    return f"{header}\n\n" + "\n".join(lines)

# ── ClawStrike System ──
def get_user_data_dir() -> Path:
    """Return the user_data directory, works both in container and on host."""
    env_dir = os.getenv("USER_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    container_path = Path("/app/user_data")
    if container_path.exists():
        return container_path
    # Host path (relative to this file)
    return Path(__file__).resolve().parent.parent / "user_data"

def load_clawstrike_log():
    """Load ClawStrike trade log from user_data."""
    path = get_user_data_dir() / "clawstrike_log.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}

def save_clawstrike_log(trade_data: dict):
    """Save ClawStrike trade log to user_data."""
    path = get_user_data_dir() / "clawstrike_log.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trade_data, indent=2))

def check_clawstrike_conditions(pair: str, chat_id: int) -> tuple[bool, str, dict]:
    """
    Check all 8 ClawStrike conditions.
    Returns (eligible: bool, reason: str, score: dict)
    """
    try:
        # Condition 1 — Session: London or NY only (SGT)
        now_utc = datetime.now(timezone.utc)
        now_sgt = (now_utc + timedelta(hours=8)).time()
        hour_sgt = now_sgt.hour
        in_london = 16 <= hour_sgt < 20
        in_ny = 21 <= hour_sgt <= 23
        if not (in_london or in_ny):
            return False, "Not in London/NY session", {}

        # Condition 2 — AI Score >= 8
        # Re-use scan result (fetch fresh if needed)
        result = ai_scan_pairs(custom_pairs=[pair], chat_id=chat_id)
        if not result:
            return False, "No scan data", {}
        p = result[0]
        ai_score = p.get("ai_score", 0)
        if ai_score < 8:
            return False, f"AI score too low: {ai_score}/10", {}

        # Condition 3 — Confidence >= 88%
        confidence = p.get("confidence", 0)
        if confidence < 88:
            return False, f"Confidence too low: {confidence}%", {}

        # Condition 4 — RRR >= 3.0
        rrr = p.get("rrr", 0)
        if rrr < 3.0:
            return False, f"RRR too low: {rrr:.2f}", {}

        # Condition 5 — ATR > 1.5%
        atr_pct = p.get("atr_pct", 0)
        if atr_pct < 1.5:
            return False, f"ATR too low: {atr_pct:.2f}%", {}

        # Condition 6 — Volume > 2x average
        vol_ratio = p.get("volume_ratio", 0)
        if vol_ratio < 2.0:
            return False, f"Volume too low: {vol_ratio:.1f}x", {}

        # Condition 7 — No existing ClawStrike trade today
        today = now_utc.date()
        clawstrike_log = load_clawstrike_log()
        if clawstrike_log.get("last_date") == str(today):
            return False, "ClawStrike already fired today", {}

        # Condition 8 — No open trades on same pair
        open_trades = api_get("/api/v1/status") or []
        for t in open_trades:
            if pair in t.get("pair", ""):
                return False, f"Already have open trade on {pair}", {}

        return True, "ALL CONDITIONS MET", p

    except Exception as e:
        logger.error(f"ClawStrike check error: {e}", exc_info=True)
        return False, f"Error: {e}", {}

# ── ClawStrike Auto-Executor ──
def execute_clawstrike(pair: str, p: dict):
    """
    Auto-execute ClawStrike trade.
    No approval needed — all conditions already met.
    """
    try:
        chat_id = int(os.getenv("TELEGRAM_CHAT_ID"))

        # Calculate leverage (max for ClawStrike)
        confidence = p.get("confidence", 88)
        trend_strength = p.get("trend_strength", 0.8)
        leverage = calculate_leverage(confidence, trend_strength)
        leverage = min(leverage * 1.5, 100)  # boost 1.5x for ClawStrike

        # Execute trade via Freqtrade forcebuy
        exchange_pair = pair
        if not exchange_pair.endswith(":USDT"):
            exchange_pair = pair.replace("/USDT", "") + "/USDT:USDT"

        payload = {
            "pair": exchange_pair,
            "side": p["direction"].lower(),
            "leverage": int(leverage)
        }

        success, result = api_post("/api/v1/forcebuy", payload)

        if success:
            trade_id = result.get("trade_id", "?")

            # Save to log
            save_clawstrike_log({
                "last_date": str(datetime.now(timezone.utc).date()),
                "pair": pair,
                "direction": p["direction"],
                "trade_id": trade_id,
                "leverage": leverage,
                "confidence": confidence,
                "ai_score": p.get("ai_score")
            })

            # Notify Telegram channel
            try:
                direction_emoji = "🔼" if p["direction"].upper() == "LONG" else "🔻"
                alert = (
                    f"🚨 *CLAWSTRIKE FIRED*\n\n"
                    f"{direction_emoji} *{pair}* {p['direction'].upper()}\n"
                    f"💰 Leverage: {leverage:.0f}×\n"
                    f"🎯 AI Score: {p.get('ai_score', '?')}/10\n"
                    f"🦊 Confidence: {confidence:.0f}%\n"
                    f"📊 RRR: {p.get('rrr', 0):.2f}\n"
                    f"🆔 Trade ID: {trade_id}\n"
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                )
                send_telegram(alert)
            except Exception as te:
                logger.error(f"ClawStrike Telegram alert failed: {te}")
        else:
            logger.error(f"ClawStrike forcebuy failed: {result}")

    except Exception as e:
        logger.error(f"ClawStrike execution error: {e}", exc_info=True)

def generate_ta():
    lines = []
    for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]:
        try:
            r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={symbol}", timeout=5)
            if r.status_code == 200:
                d = r.json()
                high = float(d.get("highPrice", 0))
                low = float(d.get("lowPrice", 0))
                lines.append(f"{symbol.replace('USDT','')}: S${low:,.0f} | R${high:,.0f}")
        except Exception:
            pass
    return "\n".join(lines) if lines else "TA unavailable"

def build_market_snapshot():
    market_prices, sources_used = fetch_market_data()
    news = get_market_news()
    ta = generate_ta()
    utc_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"🚨 *BREAKING MARKET SNAPSHOT*\n"
        f"📅 {utc_time}\n"
        f"📊 Powered by: {sources_used}\n\n"
        f"{news}\n\n"
        f"📈 *Live Prices*\n{market_prices}\n\n"
        f"📉 *Technical Levels*\n{ta}\n\n"
        f"_Data sources: Multi-exchange fallback chain (BingX → Binance → OKX → CoinGecko)_"
    )

async def market_now_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    # Define pairs: (display_label, bingx_symbol, binance_symbol, okx_symbol, coingecko_id)
    pairs = [
        ("BTC", "BTC-USDT", "BTCUSDT", "BTC-USDT", "bitcoin"),
        ("ETH", "ETH-USDT", "ETHUSDT", "ETH-USDT", "ethereum"),
        ("SOL", "SOL-USDT", "SOLUSDT", "SOL-USDT", "solana"),
        ("BNB", "BNB-USDT", "BNBUSDT", "BNB-USDT", "binancecoin"),
    ]
    bal_line = get_balance_display(chat_id)
    message = "📈 Market Now\n\n" + bal_line + "\n\n"
    sources = {"Bybit": False, "Binance": False, "OKX": False, "CoinGecko": False}
    for label, bingx_sym, binance_sym, okx_sym, cg_id in pairs:
        price = None
        change = None
        source = None
        # 1. Try Bybit
        try:
            ticker = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear", "symbol": bybit_sym})
            if ticker and ticker.get("retCode") == 0:
                d = ticker["result"]["list"][0]
                price = float(d.get("lastPrice", 0))
                change = float(d.get("price24hPcnt", 0))
                source = "Bybit"
                sources["Bybit"] = True
        except Exception:
            pass
        # 2. Binance fallback
        if price is None:
            try:
                r = requests.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={binance_sym}", timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    price = float(d.get("lastPrice", 0))
                    change = float(d.get("priceChangePercent", 0))
                    source = "Binance"
                    sources["Binance"] = True
            except Exception:
                pass
        # 3. OKX fallback
        if price is None:
            try:
                r = requests.get(f"https://www.okx.com/api/v5/market/ticker?instId={okx_sym}", timeout=5)
                if r.status_code == 200:
                    d = r.json()
                    if d.get("code") == "0" and d.get("data"):
                        d = d["data"][0]
                        price = float(d.get("last", 0))
                        change = float(d.get("change24h", 0))
                        source = "OKX"
                        sources["OKX"] = True
            except Exception:
                pass
        # 4. CoinGecko fallback (shared across all if all fail)
        if price is None:
            try:
                r = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": cg_id, "vs_currencies": "usd", "include_24hr_change": "true"},
                    timeout=10,
                )
                if r.status_code == 200:
                    d = r.json().get(cg_id, {})
                    price = d.get("usd", 0)
                    change = d.get("usd_24h_change", 0)
                    source = "CoinGecko"
                    sources["CoinGecko"] = True
            except Exception:
                pass
        # Append result
        if price is not None:
            message += f"{label}: ${price:,.2f} ({change:+.2f}%) [{source}]\n"
        else:
            message += f"{label}: Error\n"
    message += f"\n_Sources: {', '.join([k for k,v in sources.items() if v]) or 'None'}_"
    await q.edit_message_text(message, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]), parse_mode="Markdown")

# ── Trade Menu ──
async def trade_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    mode = state.get("trade_mode", "MOCK")
    trading_mode = state.get("mode", "manual")
    mode_emoji = "🤖" if trading_mode == "session" else "🎯"
    dry_emoji = "🔵" if mode == "MOCK" else "🔴"
    real, mock = get_balance()
    bal = mock if mode == "MOCK" else (real or 0)
    currency = "CLUSDT" if mode == "MOCK" else "USDT"

    text = (
        f"╔══════════════════════╗\n"
        f"║ 🦅 CLAWMIMOTO ║\n"
        f"║ Trading Terminal ║\n"
        f"╚══════════════════════╝\n\n"
        f"{dry_emoji} {mode} | {mode_emoji} {trading_mode.upper()}\n"
        f"💰 Balance: {bal:.2f} {currency}\n"
    )

    kb = [
        [InlineKeyboardButton("📊 SCAN", callback_data="ai_scan"),
         InlineKeyboardButton("💰 BALANCE", callback_data="show_balance")],
        [InlineKeyboardButton("📈 POSITIONS", callback_data="positions"),
         InlineKeyboardButton("📋 HISTORY", callback_data="history")],
        [InlineKeyboardButton("🟢 MACRO ON" if state.get("macro_on") else "🔴 MACRO OFF", callback_data="toggle_macro"),
         InlineKeyboardButton("🤖 SUTAMM ON" if state.get("sutamm") else "💤 SUTAMM OFF", callback_data="toggle_sutamm")],
        [InlineKeyboardButton("📡 SOCIALS", callback_data="socials"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data="settings")],
        [InlineKeyboardButton("🤖 SESSION MODE", callback_data="session_mode"),
         InlineKeyboardButton("🎯 MANUAL MODE", callback_data="manual_mode")],
        [InlineKeyboardButton("📊 STATS", callback_data="show_stats")],
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def scan_pair_prompt_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show popular pair buttons for custom AI scan."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    # Predefined popular pairs (Binance symbols)
    popular_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT"]
    # 2x2 grid for all 8 (4 rows)
    kb = []
    for i in range(0, len(popular_pairs), 2):
        row = []
        for p in popular_pairs[i:i+2]:
            label = p.replace("/", "")
            row.append(InlineKeyboardButton(label, callback_data=f"custom_scan_{p}"))
        kb.append(row)
    await q.edit_message_text(
        "🔍 **Select Pair to Scan**\n\nChoose a popular pair:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(kb + [[
            InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")
        ]])
    )

# ── Session Mode ──

# ── Session Mode ─-
async def session_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["mode"] = "session"
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    lev = state["leverage"]
    mar = state["margin"]
    margin_val = (10000 if state["trade_mode"] == "MOCK" else (real or 10000)) * (mar / 100)
    kb = lev_margin_buttons(state) + [
        [InlineKeyboardButton("🔍 START AI SCAN", callback_data="ai_scan")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")]
    ]
    text = (f"🤖 **SESSION MODE**\n\nBalance: {bal}\n"
            f"Leverage: {lev}x  |  Margin: {mar}%  (${margin_val:,.0f})")
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def session_adjust_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    data = q.data
    if data == "lev_up":
        state["leverage"] = min(100, state["leverage"] + 10)
    elif data == "lev_down":
        state["leverage"] = max(10, state["leverage"] - 10)
    elif data == "mar_up":
        state["margin"] = min(2, state["margin"] + 1)
    elif data == "mar_down":
        state["margin"] = max(1, state["margin"] - 1)
    # Re-render session mode
    await session_mode_cb(update, ctx)

async def ai_scan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    # Set back-context for pair detail
    user_state.setdefault(chat_id, {})
    user_state[chat_id]['pair_detail_back'] = 'ai_scan'
    await q.edit_message_text("🔍 **AI scanning market...**\n\nFetching BingX hot pairs, analyzing 5M charts, order book, sentiment...")
    pairs = ai_scan_pairs(chat_id=chat_id)
    user_state[chat_id]["selected_pairs"] = pairs
    kb = grid_2x2(pairs) + [[
        InlineKeyboardButton("🔄 REFRESH", callback_data="refresh_scan"),
        InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")
    ]]
    await q.edit_message_text("✅ **Scan Complete - Top 4 Pairs:**\n\nSelect a pair to view details & execute:", reply_markup=InlineKeyboardMarkup(kb))

async def pair_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    symbol = q.data.split("_", 1)[1]
    pairs = user_state.get(chat_id, {}).get("selected_pairs", [])
    p = next((x for x in pairs if x["symbol"] == symbol), None)
    if not p:
        await q.edit_message_text("❌ Pair data not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]]))
        return
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    conf = p["confidence"]
    greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
    cur_price = p.get('current_price', 0)
    if not cur_price:
        try:
            symbol_clean = p['symbol'].replace('/', '')
            cur_price, _ = get_binance_ticker(symbol_clean)
        except: pass
    # Enriched trade params
    entry = p.get('entry', cur_price or 0)
    sl = p.get('sl', 0)
    tp = p.get('tp', 0)
    rrr = p.get('rrr', 2.0)
    stake = p.get('stake_amount', 0)
    qty = p.get('quantity', 0)
    lev = state['leverage']
    # Direction arrow for SL/TP (P&L percentage at those levels)
    if p['direction'] == 'LONG':
        sl_pct = (sl/entry - 1)*100 if entry else 0
        tp_pct = (tp/entry - 1)*100 if entry else 0
    else:
        sl_pct = (entry - sl) / entry * 100 if entry else 0
        tp_pct = (entry - tp) / entry * 100 if entry else 0
    # Projected P&L if TP hit
    proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
    text = (f"📊 {p['symbol']} {p['direction']} {state['trade_mode']}\n\n"
            f"Balance: {bal}\n"
            f"Change: {p['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
            f"Reasons: {' | '.join(p['reasons'])}\n"
            f"Leverage: {lev}x  |  Margin: {state['margin']}%  (${stake:,.0f})\n"
            f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
            f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
            f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
            f"Trailing: activates +50%, offset 2%\n"
            f"Confidence: {conf}% {greens} 🦞")
    kb = []
    user_id = update.effective_user.id
    if is_pair_valid_for_user(p['symbol'], user_id):
        kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
    try:
        symbol_clean = p['symbol'].replace('/', '')
        cur_price, _ = get_binance_ticker(symbol_clean)
        if cur_price and cur_price > 0:
            kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {p['symbol']} {cur_price:.2f}")])
    except Exception as e:
        logger.debug(f"Alert price fetch failed: {e}")
    kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{p['symbol']}")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def select_pair_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle pair selection from Manual Mode or Add Pair menu.
    Runs AI analysis and shows pair detail with context-aware back button."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    symbol = q.data.split("_", 1)[1]  # format: select_BTC/USDT
    
    # Show analyzing message
    await q.edit_message_text(f"🔍 Analyzing {symbol}...", parse_mode="Markdown")
    
    # Run analysis
    try:
        result = analyze_pair(symbol)
        result.setdefault('symbol', symbol)
        result.setdefault('direction', 'LONG')
        result.setdefault('change', 0.0)
        result.setdefault('confidence', 85)
        result.setdefault('reasons', ['Volume spike', 'Momentum'])
        result.setdefault('current_price', 0)
        
        # Enrich with trade parameters (entry, sl, tp, rrr, sizing)
        result = enrich_trade_params(result, chat_id)
        
        # Store in user_state
        user_state.setdefault(chat_id, {"selected_pairs": []})
        user_state[chat_id]['selected_pairs'] = [result]
        
        # Determine back target from context
        back_target = user_state[chat_id].get('pair_detail_back', 'manual_mode')
        
        # Render detail
        state = get_state(chat_id)
        real, mock = get_balance()
        bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
        conf = result['confidence']
        greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
        cur_price = result.get('current_price', 0)
        if not cur_price:
            try:
                symbol_clean = result['symbol'].replace('/', '')
                cur_price, _ = get_binance_ticker(symbol_clean)
            except: pass
        # Build detailed text
        entry = result.get('entry', cur_price or 0)
        sl = result.get('sl', 0)
        tp = result.get('tp', 0)
        rrr = result.get('rrr', 2.0)
        stake = result.get('stake_amount', 0)
        qty = result.get('quantity', 0)
        lev = state['leverage']
        # Direction arrow for SL/TP
        if result['direction'] == 'LONG':
            sl_pct = (sl/entry - 1)*100 if entry else 0
            tp_pct = (tp/entry - 1)*100 if entry else 0
        else:
            sl_pct = (entry - sl) / entry * 100 if entry else 0
            tp_pct = (entry - tp) / entry * 100 if entry else 0
        # Projected P&L if TP hit
        proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
        text = (f"📊 {result['symbol']} {result['direction']} {state['trade_mode']}\n\n"
                f"Balance: {bal}\n"
                f"Change: {result['change']:+.2f}%"
                + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "")
                + "\n"
                f"Reasons: {' | '.join(result['reasons'])}\n"
                f"Leverage: {lev}x  |  Margin: {state['margin']}%  (${stake:,.0f})\n"
                f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
                f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
                f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
                f"Trailing: activates +50%, offset 2%\n"
                f"Confidence: {conf}% {greens} 🦞")
        kb = []
        user_id = update.effective_user.id
        if is_pair_valid_for_user(result['symbol'], user_id):
            kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
        try:
            symbol_clean = result['symbol'].replace('/', '')
            cur_price, _ = get_binance_ticker(symbol_clean)
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
        except Exception as e:
            logger.debug(f"Alert price fetch failed: {e}")
        kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{result['symbol']}")])
        kb.append([InlineKeyboardButton("⬅️ BACK", callback_data=back_target)])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"select_pair_cb error: {e}", exc_info=True)
        await q.edit_message_text(f"❌ Analysis failed: {str(e)[:100]}",
                                  reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")]]))

# ── Manual Mode ──
async def manual_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    # Set back-context for pair detail
    user_state.setdefault(chat_id, {})
    user_state[chat_id]['pair_detail_back'] = 'manual_mode'
    state = get_state(chat_id)
    state["mode"] = "manual"

    # Tier 1: 4 fixed majors
    tier1_pairs = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
    kb = []
    for i in range(0, len(tier1_pairs), 2):
        row = []
        for p in tier1_pairs[i:i+2]:
            row.append(InlineKeyboardButton(p, callback_data=f"select_{p}"))
        kb.append(row)
    # More Opportunities button
    kb.append([InlineKeyboardButton("📊 More Opportunities", callback_data="more_opportunities")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")])
    await q.edit_message_text(
        "👷 **MANUAL MODE**\n\nTier 1 — Major Pairs:\nSelect a liquid pair to trade:",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def add_pair_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    # Set back-context for pair detail
    user_state.setdefault(chat_id, {})
    user_state[chat_id]['pair_detail_back'] = 'add_pair_menu'
    top = get_bybit_hot_pairs(limit=10)
    kb = []
    for i in range(0, len(top), 2):
        row = []
        for p in top[i:i+2]:
            row.append(InlineKeyboardButton(p, callback_data=f"select_{p}"))
        kb.append(row)
    kb.append([InlineKeyboardButton("⌨️ OTHER PAIR", callback_data="other_pair_input")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")])
    await q.edit_message_text("➕ **ADD PAIR**\n\nSelect or enter custom:", reply_markup=InlineKeyboardMarkup(kb))

async def other_pair_input_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("⌨️ **ENTER CUSTOM PAIR**\n\nType ticker (e.g., BTC/USDT) in chat.\nI'll verify on Bybit.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="add_pair_menu")]]))
    user_state[q.message.chat_id]["awaiting_pair_input"] = True

# ── Manual Mode — Tier 2: More Opportunities ──
async def more_opportunities_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id

    # Show loading message
    await q.edit_message_text("📊 **Scanning opportunities...**", parse_mode="Markdown")

    try:
        # Fetch Bybit tickers
        data = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear"}, timeout=5)
        if not data or data.get("retCode") != 0:
            await q.edit_message_text("❌ Failed to fetch Bybit tickers", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")]]))
            return

        items = data.get("result", {}).get("list", [])
        tier1_bases = {"BTC", "ETH", "SOL", "BNB"}
        EXCLUDED = {
            "USDC", "BUSD", "DAI", "TUSD", "FDUSD",
            "XAUT", "PAXG",
            "CL", "GC", "SI", "NG", "HG",
            "GOLD", "SILVER", "OIL", "COPPER",
        }
        candidates = []
        for item in items:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            base = symbol[:-4]
            if base in tier1_bases or base in EXCLUDED:
                continue
            try:
                price = float(item.get("lastPrice", 0))
                turnover = float(item.get("turnover24h", 0))
                if price <= 0.10 or turnover < 50_000_000:
                    continue
            except (TypeError, ValueError):
                continue
            candidates.append({
                "symbol": f"{base}/USDT",
                "bybit_symbol": symbol,
                "price": price,
                "turnover": turnover
            })

        if not candidates:
            await q.edit_message_text("❌ No additional opportunities found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")]]))
            return

        # Fetch 1H move for each candidate (last 2 candles)
        for c in candidates:
            try:
                klines = bybit_signed_request(
                    "GET", "/v5/market/kline",
                    params={
                        "category": "linear",
                        "symbol": c["bybit_symbol"],
                        "interval": "60",
                        "limit": 2
                    },
                    timeout=5
                )
                if klines and klines.get("retCode") == 0:
                    k = klines.get("result", {}).get("list", [])
                    if len(k) >= 2:
                        close_prev = float(k[1][4])
                        close_curr = float(k[0][4])
                        if close_prev > 0:
                            move_pct = (close_curr - close_prev) / close_prev * 100
                            c["move_pct"] = move_pct
                        else:
                            c["move_pct"] = 0.0
                    else:
                        c["move_pct"] = 0.0
                else:
                    c["move_pct"] = 0.0
            except Exception:
                c["move_pct"] = 0.0

        # Score: volume × abs(move) × simple RRR proxy (use 0.5 fixed for now)
        for c in candidates:
            c["score"] = c["turnover"] * abs(c.get("move_pct", 0)) * 0.5

        # Sort and take top 4
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top4 = candidates[:4]

        # Build keyboard 2x2
        kb = []
        for i in range(0, len(top4), 2):
            row = []
            for c in top4[i:i+2]:
                move_str = f"{c.get('move_pct', 0):+.1f}%"
                label = f"{c['symbol'].replace('/USDT','')} {move_str}"
                row.append(InlineKeyboardButton(label, callback_data=f"select_{c['symbol']}"))
            kb.append(row)
        kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")])

        # Build message
        lines = ["📊 **More Opportunities**\n\nTop movers by volume × 1H change:"]
        for c in top4:
            move = c.get("move_pct", 0)
            lines.append(f"• {c['symbol']}: {move:+.1f}% (1H)")
        text = "\n".join(lines)

        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

    except Exception as e:
        logger.error(f"More opportunities error: {e}", exc_info=True)
        await q.edit_message_text(f"❌ Error: {e}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")]]))


def extract_pair_from_link(url: str):
    """Extract trading pair symbol from exchange or TradingView links.
    Supports: Bybit, Binance, BingX, TradingView, Twitter/X cashtags.
    Returns formatted pair like "BTC/USDT" or None.
    """
    import re
    from urllib.parse import urlparse, parse_qs
    url = url.strip()
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        path = parsed.path.upper()

        # Bybit — patterns like /spot/trade/BTCUSDT or /contracts/BTCUSDT
        if "bybit.com" in domain:
            m = re.search(r'/([A-Z]{2,10})(USDT|USDC|BTC|ETH)', path)
            if m:
                base = m.group(1)
                quote = m.group(2)
                # Normalize quote to USDT for consistency
                return f"{base}/USDT"

        # Binance — spot or futures paths
        if "binance.com" in domain:
            m = re.search(r'/([A-Z]{2,10})[_-]?(USDT|BTC|ETH)', path)
            if m:
                return f"{m.group(1)}/USDT"

        # BingX
        if "bingx.com" in domain:
            m = re.search(r'/([A-Z]{2,10})-?(USDT|BTC|ETH)', path)
            if m:
                return f"{m.group(1)}/USDT"

        # TradingView — symbol in query param
        if "tradingview.com" in domain:
            qs = parse_qs(parsed.query)
            symbol = qs.get('symbol', [''])[0].upper()
            m = re.search(r':?([A-Z]{2,10})(USDT|BTC|ETH)', symbol)
            if m:
                return f"{m.group(1)}/USDT"

        # Twitter/X — ask StepFun to identify pair from URL context
        if "twitter.com" in domain or "x.com" in domain:
            prompt = f"This is a crypto Twitter URL: {url}\nWhat trading pair is being discussed? Reply with only the pair symbol like BTC/USDT or UNKNOWN."
            ai_text = call_stepfun_skill(prompt, retries=1)
            if ai_text and "UNKNOWN" not in ai_text.upper():
                m = re.search(r'([A-Z]{2,10})/USDT', ai_text.upper())
                if m:
                    return f"{m.group(1)}/USDT"
            return None
    except Exception:
        pass
    return None

async def text_input_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    text = update.message.text.upper()
    # Ensure user_state entry exists
    if chat_id not in user_state:
        user_state[chat_id] = {"leverage": 50, "margin": 1, "trade_mode": "MOCK", "selected_pairs": []}
    state = user_state.get(chat_id, {})
    logger.info(f"Text handler: chat={chat_id} text={text[:100]}")

    # Handle $BTC $ETH style cashtags
    if text.startswith("$"):
        base = text[1:].split()[0].strip().upper()
        base = ''.join(c for c in base if c.isalpha())
        if 2 <= len(base) <= 10:
            pair = f"{base}/USDT"
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Detected: *{pair}*\nRunning AI scan...",
                parse_mode="Markdown"
            )
            results = ai_scan_pairs(custom_pairs=[pair], chat_id=chat_id)
            if results:
                await send_scan_message(chat_id, results, ctx)
            else:
                await ctx.bot.send_message(chat_id=chat_id,
                    text=f"⚠️ No setup found for {pair}. Try another pair.")
            return

    # Handle BTCUSDT / BTC/USDT / BTCUSDT:USDT typed directly
    import re as _re
    pair_match = _re.match(r'^([A-Z]{2,10})(USDT|/USDT|/USDT:USDT)?$', text.strip())
    if pair_match and not text.startswith("HTTP"):
        base = pair_match.group(1)
        if base not in {"THE", "FOR", "AND", "NOT", "BUT", "NEW", "ALL"}:
            pair = f"{base}/USDT"
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Detected: *{pair}*\nRunning AI scan...",
                parse_mode="Markdown"
            )
            results = ai_scan_pairs(custom_pairs=[pair], chat_id=chat_id)
            if results:
                await send_scan_message(chat_id, results, ctx)
            else:
                await ctx.bot.send_message(chat_id=chat_id,
                    text=f"⚠️ No setup found for {pair}. Try another pair.")
            return

    # NEW — Link scanning: if message starts with http, extract pair and run AI scan
    if text.startswith("HTTP"):
        pair = extract_pair_from_link(text)
        if pair:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text=f"🔍 Detected: *{pair}*\nRunning AI scan...",
                parse_mode="Markdown"
            )
            results = ai_scan_pairs(
                custom_pairs=[pair],
                chat_id=chat_id
            )
            if results:
                await send_scan_message(chat_id, results, ctx)
            else:
                await ctx.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Could not extract pair.\nSend pair directly e.g. BTC/USDT"
                )
            return
        else:
            await ctx.bot.send_message(
                chat_id=chat_id,
                text="❌ Could not extract trading pair from link."
            )
            return

    # Handle BingX URL paste (with or without http prefix)
    text_lower = text.lower()
    if "bybit.com" in text_lower:
        print(f"[DEBUG] BingX URL detected: {text[:80]}")
        logger.info(f"Bybit URL detected: {text[:80]}")
        pair = extract_pair_from_bybit_url(text)
        print(f"[DEBUG] Extracted pair: {pair}")
        logger.info(f"Extracted pair: {pair}")
        if pair:
            # Validate pair exists on BingX (admins bypass)
            user_id = update.effective_user.id
            if not is_pair_valid_for_user(pair, user_id):
                await update.message.reply_text(
                    f"❌ **Pair not available**\n\n{pair} is not listed on Bybit (validation failed).\n\nTry a different pair like BTC/USDT, ETH/USDT, SOL/USDT.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]])
                )
                return
            try:
                result = analyze_pair(pair)
                # Ensure required keys exist
                result.setdefault('symbol', pair)
                result.setdefault('direction', 'LONG')
                result.setdefault('change', 0.0)
                result.setdefault('confidence', 85)
                result.setdefault('reasons', ['High volume', 'Momentum', 'AI signal'])
                result.setdefault('current_price', 0)
                # Enrich with trade parameters (entry, sl, tp, rrr, sizing)
                result = enrich_trade_params(result, chat_id)
                user_state[chat_id]['selected_pairs'] = [result]

                user_state.setdefault(chat_id, {})['pair_detail_back'] = 'main'
            except Exception as e:
                logger.error(f"Analysis failed for {pair}: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ **Analysis failed** for {pair}\n\n"
                    f"Error: {str(e)[:200]}\n\n"
                    f"Try again later or use /scan for hot pairs.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]])
                )
                return
            # Show detail view
            real, mock = get_balance()
            bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
            conf = result["confidence"]
            greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
            # Get real-time price
            symbol_clean = result['symbol'].replace('/', '')
            cur_price = result.get('current_price', 0)
            try:
                ticker_price, _ = get_binance_ticker(symbol_clean)
                if ticker_price and ticker_price > 0:
                    cur_price = ticker_price
            except: pass
            # Enriched trade params (already enriched)
            entry = result.get('entry', cur_price or 0)
            sl = result.get('sl', 0)
            tp = result.get('tp', 0)
            rrr = result.get('rrr', 2.0)
            stake = result.get('stake_amount', 0)
            qty = result.get('quantity', 0)
            lev = state.get('leverage', 50)
            if result['direction'] == 'LONG':
                sl_pct = (sl/entry - 1)*100 if entry else 0
                tp_pct = (tp/entry - 1)*100 if entry else 0
            else:
                sl_pct = (entry - sl) / entry * 100 if entry else 0
                tp_pct = (entry - tp) / entry * 100 if entry else 0
            # Projected P&L if TP hit
            proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
            text_msg = (f"📊 {result['symbol']} {result['direction']} {state.get('trade_mode','MOCK')}\n\n"
                        f"Balance: {bal}\n"
                        f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
                        f"Reasons: {' | '.join(result['reasons'])}\n"
                        f"Leverage: {lev}x  |  Margin: {state.get('margin',1)}%  (${stake:,.0f})\n"
                        f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
                        f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
                        f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
                        f"Trailing: activates +50%, offset 2%\n"
                        f"Confidence: {conf}% {greens} 🦞")
            kb = [[InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")]]
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
            kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{result['symbol']}")])
            await update.message.reply_text(text_msg, reply_markup=InlineKeyboardMarkup(kb))
            return
        else:
            await update.message.reply_text("❌ Could not extract pair from URL.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
            return

    # Binance futures OR spot URL handling
    if "binance.com" in text_lower and ("/futures/" in text_lower or "/trade/" in text_lower):
        pair = extract_pair_from_binance_url(text)
        if pair:
            # Validate pair exists on BingX (admins bypass)
            user_id = update.effective_user.id
            if not is_pair_valid_for_user(pair, user_id):
                await update.message.reply_text(
                    f"❌ **Pair not available**\n\n{pair} is not listed on Bybit (validation failed).\n\nTry a different pair like BTC/USDT, ETH/USDT, SOL/USDT.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]])
                )
                return
            try:
                result = analyze_pair(pair)
                result.setdefault('symbol', pair)
                result.setdefault('direction', 'LONG')
                result.setdefault('change', 0.0)
                result.setdefault('confidence', 85)
                result.setdefault('reasons', ['High volume', 'Momentum', 'AI signal'])
                result.setdefault('current_price', 0)
                # Enrich with trade parameters (entry, sl, tp, rrr, sizing)
                result = enrich_trade_params(result, chat_id)
                user_state[chat_id]['selected_pairs'] = [result]

                user_state.setdefault(chat_id, {})['pair_detail_back'] = 'main'
            except Exception as e:
                logger.error(f"Analysis failed for {pair}: {e}", exc_info=True)
                await update.message.reply_text(
                    f"❌ **Analysis failed** for {pair}\n\nError: {str(e)[:200]}\n\nTry again later or use /scan for hot pairs.",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]])
                )
                return
            # Show detail view
            real, mock = get_balance()
            bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
            conf = result["confidence"]
            greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
            # Get real-time price
            symbol_clean = result['symbol'].replace('/', '')
            cur_price = result.get('current_price', 0)
            try:
                ticker_price, _ = get_binance_ticker(symbol_clean)
                if ticker_price and ticker_price > 0:
                    cur_price = ticker_price
            except: pass
            # Enriched trade params (already enriched)
            entry = result.get('entry', cur_price or 0)
            sl = result.get('sl', 0)
            tp = result.get('tp', 0)
            rrr = result.get('rrr', 2.0)
            stake = result.get('stake_amount', 0)
            qty = result.get('quantity', 0)
            lev = state.get('leverage', 50)
            if result['direction'] == 'LONG':
                sl_pct = (sl/entry - 1)*100 if entry else 0
                tp_pct = (tp/entry - 1)*100 if entry else 0
            else:
                sl_pct = (entry - sl) / entry * 100 if entry else 0
                tp_pct = (entry - tp) / entry * 100 if entry else 0
            # Projected P&L if TP hit
            proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
            text_msg = (f"📊 {result['symbol']} {result['direction']} {state.get('trade_mode','MOCK')}\n\n"
                        f"Balance: {bal}\n"
                        f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
                        f"Reasons: {' | '.join(result['reasons'])}\n"
                        f"Leverage: {lev}x  |  Margin: {state.get('margin',1)}%  (${stake:,.0f})\n"
                        f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
                        f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
                        f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
                        f"Trailing: activates +50%, offset 2%\n"
                        f"Confidence: {conf}% {greens} 🦞")
            kb = [[InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")]]
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
            kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{result['symbol']}")])
            await update.message.reply_text(text_msg, reply_markup=InlineKeyboardMarkup(kb))
            return

    if state.get("awaiting_pair_input"):
        if "/" not in text:
            await update.message.reply_text("❌ Format: BASE/QUOTE (e.g., BTC/USDT)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
            return
        if validate_pair_on_bybit(text):
            user_state[chat_id]["selected_pair"] = {"symbol": text, "direction": "LONG"}
            state["awaiting_pair_input"] = False
            await update.message.reply_text(f"✅ Pair {text} added!\n\nUse /start to continue.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 MAIN", callback_data="main")]]))
        else:
            await update.message.reply_text("❌ Pair not on Bybit. Try again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))

def validate_pair_on_bybit(pair):
    """Validate pair exists on Bybit (USDT-margined linear perpetual)."""
    if not pair.endswith("/USDT"):
        return False
    try:
        base = pair.split("/")[0]
        bybit_symbol = f"{base}USDT"
        data = bybit_signed_request("GET", "/v5/market/tickers", params={"category": "linear", "symbol": bybit_symbol}, timeout=5)
        return data is not None and data.get("retCode") == 0 and len(data.get("result", {}).get("list", [])) > 0
    except Exception:
        return False

def extract_pair_from_bybit_url(url):
    """Extract pair from Bybit perpetual URL.
    Example: https://bybit.com/en/perpetual/GENIUS-USDT -> GENIUS/USDT
    Returns None if pair is not USDT-margined.
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')
        # Look for 'perpetual' segment (case-insensitive) and take next
        for i, part in enumerate(path_parts):
            if part.lower() == 'perpetual' and i + 1 < len(path_parts):
                pair_raw = path_parts[i + 1]
                pair = pair_raw.replace('-', '/').upper()
                # Enforce USDT-margined only
                if pair.endswith('/USDT'):
                    return pair
        # Fallback: last path segment
        if path_parts:
            pair_raw = path_parts[-1]
            pair = pair_raw.replace('-', '/').upper()
            if '/' in pair and pair.endswith('/USDT'):
                return pair
    except Exception as e:
        logger.debug(f"URL parse error: {e}")
    return None

def extract_pair_from_binance_url(url):
    """Extract pair from Binance futures or spot URL.
    Futures: https://www.binance.com/en/futures/BTCUSDT -> BTC/USDT
    Spot:    https://www.binance.com/en/trade/GLMR_USDT?type=spot -> GLMR/USDT
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if 'binance.com' not in parsed.netloc.lower():
            return None
        path_parts = parsed.path.strip('/').split('/')
        # Futures: /futures/SYMBOL
        for i, part in enumerate(path_parts):
            if part.lower() == 'futures' and i + 1 < len(path_parts):
                symbol = path_parts[i + 1].upper()
                if symbol.endswith('USDT'):
                    base = symbol[:-4]
                    return f"{base}/USDT"
        # Spot: /trade/PAIR (e.g. GLMR_USDT)
        for i, part in enumerate(path_parts):
            if part.lower() == 'trade' and i + 1 < len(path_parts):
                pair_raw = path_parts[i + 1].upper()
                # Spot uses underscore: GLMR_USDT
                if '_' in pair_raw and pair_raw.endswith('_USDT'):
                    return pair_raw.replace('_', '/')
        # Fallback: last segment (futures-style)
        if path_parts:
            symbol = path_parts[-1].upper()
            if symbol.endswith('USDT'):
                base = symbol[:-4]
                return f"{base}/USDT"
    except Exception as e:
        logger.debug(f"Binance URL parse error: {e}")
    return None

# ── Positions ──
async def positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    # Cancel any auto-refresh task for this chat (leaving position detail)
    chat_id = update.effective_chat.id
    if chat_id in position_refresh_tasks:
        position_refresh_tasks[chat_id]["task"].cancel()
        del position_refresh_tasks[chat_id]
    q = update.callback_query
    await q.answer()
    trades_list = api_get("/api/v1/status") or []
    bal = get_balance_display(chat_id)
    mode_header = get_mode_header(chat_id)
    if not trades_list:
        await q.edit_message_text(f"{mode_header}\n\n📊 **No open positions**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return

    # Build 2x3 grid for first 6 pairs (newest first)
    buttons = []
    trade_list = trades_list
    # Sort by open_timestamp descending (newest first)
    trade_list_sorted = sorted(trade_list, key=lambda t: t.get("open_timestamp", 0), reverse=True)
    visible_trades = trade_list_sorted[:6]
    extra_trades = trade_list_sorted[6:]

    # Create 2-column rows from visible trades
    for i in range(0, len(visible_trades), 2):
        row = []
        for t in visible_trades[i:i+2]:
            profit = t.get("profit_pct", 0)
            btn_text = f"📌 {t['pair']} {profit:+.1f}%"
            row.append(InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}"))
        buttons.append(row)

    # Add OTHER TRADES button if there are more than 6
    if extra_trades:
        buttons.append([InlineKeyboardButton("📋 OTHER TRADES", callback_data="other_positions")])
    buttons.append([InlineKeyboardButton("✅ CLOSED", callback_data="closed_positions")])
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    await q.edit_message_text(f"{mode_header}\n\n📊 **Open Positions**\n\n{bal}\n\nSelect one:", reply_markup=InlineKeyboardMarkup(buttons))

async def refresh_positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Refresh the positions list (called from Refresh button)."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("🔄 Refreshing...")
    chat_id = q.message.chat_id
    trades_list = api_get("/api/v1/status") or []
    bal = get_balance_display(chat_id)
    if not trades_list:
        await q.edit_message_text(f"📊 **No open positions**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    buttons = []
    # Sort by open_timestamp descending (newest first)
    trade_list = sorted(trades_list, key=lambda t: t.get("open_timestamp", 0), reverse=True)
    for t in trade_list:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} - {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions")])
    buttons.append([InlineKeyboardButton("✅ CLOSED", callback_data="closed_positions")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    mode_header = get_mode_header(chat_id)
    await q.edit_message_text(f"{mode_header}\n\n📊 **Open Positions**\n\n{bal}\n\nSelect one:", reply_markup=InlineKeyboardMarkup(buttons))

async def other_positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show additional positions beyond the first 6 (overflow list)."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trades_list = api_get("/api/v1/status") or []
    chat_id = q.message.chat_id
    if not trades_list:
        await q.edit_message_text("📊 **No open positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return

    # Sort by open_timestamp descending (newest first)
    trade_list = sorted(trades_list, key=lambda t: t.get("open_timestamp", 0), reverse=True)
    # Get trades from index 6 onward (overflow)
    extra_trades = trade_list[6:]
    bal = get_balance_display(chat_id)
    if not extra_trades:
        await q.edit_message_text(f"📊 **No other positions**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    buttons = []
    for t in extra_trades:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK TO LIST", callback_data="positions")])
    # Also link to closed positions from overflow screen
    buttons.append([InlineKeyboardButton("✅ CLOSED", callback_data="closed_positions")])
    await q.edit_message_text(f"📋 **Other Positions** ({len(extra_trades)} more)\n\n{bal}", reply_markup=InlineKeyboardMarkup(buttons))

async def closed_positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show closed positions (most recent first)."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    trades = api_get("/api/v1/trades?status=closed&limit=50")
    bal = get_balance_display(chat_id)
    if not trades or not trades.get("trades"):
        await q.edit_message_text(f"📊 **No closed positions**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    # Sort by close_timestamp descending (newest closed first)
    closed_list = sorted(trades["trades"], key=lambda t: t.get("close_timestamp", 0), reverse=True)
    buttons = []
    for t in closed_list:
        profit = t.get("profit_pct", 0)
        btn_text = f"✅ {t['pair']} {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("🔄 REFRESH", callback_data="refresh_closed")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="positions")])
    await q.edit_message_text(f"📊 **Closed Positions** (last {len(closed_list)})\n\n{bal}", reply_markup=InlineKeyboardMarkup(buttons))

async def refresh_closed_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Refresh closed positions list."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("🔄 Refreshing...")
    chat_id = q.message.chat_id
    trades = api_get("/api/v1/trades?status=closed&limit=50")
    bal = get_balance_display(chat_id)
    if not trades or not trades.get("trades"):
        await q.edit_message_text(f"📊 **No closed positions**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    closed_list = sorted(trades["trades"], key=lambda t: t.get("close_timestamp", 0), reverse=True)
    buttons = []
    for t in closed_list:
        profit = t.get("profit_pct", 0)
        btn_text = f"✅ {t['pair']} {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("🔄 REFRESH", callback_data="refresh_closed")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="positions")])
    await q.edit_message_text(f"📊 **Closed Positions** (last {len(closed_list)})\n\n{bal}", reply_markup=InlineKeyboardMarkup(buttons))

async def pos_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    # Fetch all open trades from /api/v1/status and find by trade_id
    trades_list = api_get("/api/v1/status") or []
    t = next((trade for trade in trades_list if str(trade.get('trade_id')) == trade_id), None)
    if not t:
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    # Use user's current trade mode for balance display
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
    is_open = t.get("is_open", True)

    # Build PnL line: unrealized for open, realized for closed
    if is_open:
        pnl_line = f"Unrealized: {t.get('profit_pct',0):+.1f}%"
        if t.get('profit_abs') is not None:
            pnl_line += f" (${t['profit_abs']:,.2f})"
    else:
        pnl_line = f"Realized PnL: {t.get('profit_pct',0):+.1f}%"
        if t.get('profit_abs') is not None:
            pnl_line += f" (${t['profit_abs']:,.2f})"

    status_btn = InlineKeyboardButton("🔴 CLOSE POSITION", callback_data=f"close_{trade_id}") if is_open else InlineKeyboardButton("✅ CLOSED", callback_data="dummy")
    # Build TP/SL display
    sl_pct = t.get('stop_loss_pct', 0)
    tp_pct = t.get('take_profit_pct')
    tp_display = f"{tp_pct:.1f}%" if tp_pct is not None else "N/A"
    exit_reason = t.get('exit_reason', '')
    exit_line = f"Exit: {exit_reason}" if not is_open and exit_reason else ""
    text = (f"📊 {t['pair']} {t.get('direction','LONG')} {'OPEN' if is_open else 'CLOSED'}\n\n"
            f"Balance: {bal}\n"
            f"Time: {t.get('open_date','')}"
            + (f" (closed: {t.get('close_date','')})" if not is_open else "") + "\n"
            f"Margin: ${t.get('stake_amount',0):,.2f}  |  Leverage: {t.get('leverage','N/A')}x  |  {pnl_line}\n"
            f"Entry: {t.get('open_rate',0):,.2f}  |  SL: {sl_pct:.1f}%  |  TP: {tp_display}"
            + (f"\n{exit_line}" if exit_line else "") + "\n")
    kb = [
        [status_btn],
        [InlineKeyboardButton("📤 Share PNL", callback_data=f"share_{trade_id}")],
        [InlineKeyboardButton("🔄 Refresh", callback_data=f"pos_{trade_id}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="positions")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    # Start auto-refresh task for this chat (if not already running)
    chat_id = q.message.chat_id
    # Cancel existing task if any
    if chat_id in position_refresh_tasks:
        position_refresh_tasks[chat_id]["task"].cancel()
    # Start new background refresh task
    task = asyncio.create_task(auto_refresh_position(chat_id, trade_id, ctx))
    position_refresh_tasks[chat_id] = {"task": task, "msg_id": q.message.message_id, "trade_id": trade_id}

async def close_position_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    success, _ = api_post(f"/api/v1/trades/{trade_id}/close")
    if success:
        await q.edit_message_text("✅ Position closed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ POSITIONS", callback_data="positions")]]))
    else:
        await q.edit_message_text("❌ Failed to close.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))

async def share_pnl_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    # Fetch trade by ID from /api/v1/status (open) or closed trades endpoint
    trades_list = api_get("/api/v1/status") or []
    t = next((trade for trade in trades_list if str(trade.get('trade_id')) == trade_id), None)
    if not t:
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    # Generate card (placeholder - use PnL card generator when ready)
    card_path = f"generated-cards/pnl_{trade_id}.png"
    # TODO: generate image with Pillow
    text = (f"📈 **PnL Share**\n\n"
            f"{t['pair']} {t.get('direction','LONG')}\n"
            f"PnL: {t.get('profit_pct',0):+.1f}% (${t.get('profit_abs',0):,.2f})\n"
            f"Mode: {t.get('is_mock','MOCK')}")
    # For now, just send text. Later: send image + button to RightclawTrade
    await q.edit_message_text(text + "\n\n_Image card generation pending_", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))

# ── Execute Trade ──
async def execute_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    pairs = user_state.get(chat_id, {}).get("selected_pairs", [])
    if not pairs:
        await q.edit_message_text("❌ No pair selected. Use SESSION MODE first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        return
    p = pairs[0]  # use first selected
    # Validate pair is available on exchange before showing confirm screen (admins bypass)
    user_id = q.from_user.id
    if not is_pair_valid_for_user(p['symbol'], user_id):
        await q.edit_message_text(
            f"❌ **Pair not available**\n\n{p['symbol']} is not listed on Bybit (validation failed).\n\nSelect a valid pair and try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]])
        )
        return
    text = (f"🚀 **EXECUTE TRADE**\n\n"
            f"Pair: {p['symbol']} {p['direction']}\n"
            f"Leverage: {state['leverage']}x\n"
            f"Margin: {state['margin']}%\n"
            f"Mode: {state['trade_mode']}\n\n"
            f"Confirm?")
    kb = [
        [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_{p['symbol']}")],
        [InlineKeyboardButton("❌ CANCEL", callback_data="session_mode")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def confirm_exec_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("⏳ Executing...")
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    pairs = user_state.get(chat_id, {}).get("selected_pairs", [])
    if not pairs:
        await q.edit_message_text("❌ No pair selected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        return
    p = pairs[0]
    # Validate pair is available on exchange before executing (admins bypass)
    user_id = q.from_user.id
    if not is_pair_valid_for_user(p['symbol'], user_id):
        await q.edit_message_text(
            f"❌ **Cannot execute**\n\n{p['symbol']} is not available on the exchange.\n\nSelect a valid pair and try again.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]])
        )
        return
    # Convert to exchange-specific symbol format
    # Bybit linear futures: BTC/USDT -> BTC/USDT:USDT
    exchange_pair = p["symbol"]
    if exchange_pair.endswith("/USDT"):
        exchange_pair = exchange_pair + ":USDT"

    # Block micro caps (price < $0.10)
    price = float(p.get('current_price', 0))
    if price < 0.10:
        await q.answer("⛔ Blocked — micro cap (price < $0.10)")
        return

    # Block non-whitelisted pairs in session mode (manual mode allows any pair)
    mode = state.get("mode", "manual")
    if mode == "session":
        whitelist = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"]
        if p["symbol"] not in whitelist:
            await q.edit_message_text(
                f"❌ **Pair not allowed in session mode**\n\n{p['symbol']} is not in the session whitelist.\n\nSwitch to MANUAL MODE to trade any pair.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
            )
            return
    # Dynamic leverage from AI confidence + trend strength
    confidence = p.get("confidence", 85)
    trend_strength = p.get("trend_strength", 0.5)
    dynamic_leverage = calculate_leverage(confidence, trend_strength)
    payload = {
        "pair": exchange_pair,
        "leverage": dynamic_leverage,
        "margin": state["margin"],
        "direction": p["direction"],
        "dry_run": state["trade_mode"] == "MOCK"
    }
    logger.info(f"Executing trade: {payload} (leverage={dynamic_leverage}, conf={confidence}, trend={trend_strength:.2f})")
    success, error_msg = api_post("/api/v1/forcebuy", payload)
    if success:
        msg = "✅ **Trade executed!**"
        if state["trade_mode"] == "MOCK":
            msg += "\n\n_MOCK mode - no real funds used_"
        msg += "\n\nCheck POSITIONS for status."
        # Try to fetch the newly opened trade ID to provide a direct VIEW POSITION button
        try:
            trades_list = api_get("/api/v1/status") or []
            # Filter for matching pair and sort by timestamp
            matching = [t for t in trades_list if t.get('pair') == exchange_pair]
            if matching:
                latest = max(matching, key=lambda t: t.get('open_timestamp', 0))
                new_trade_id = latest.get('trade_id')
                if new_trade_id is not None:
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("📌 VIEW POSITION", callback_data=f"pos_{new_trade_id}")],
                        [InlineKeyboardButton("⬅️ MAIN", callback_data="main")]
                    ])
                    await q.edit_message_text(msg, reply_markup=kb)
                    # Auto-delete confirmation after 5 minutes
                    asyncio.create_task(delete_after_delay(ctx.bot, chat_id, q.message.message_id, delay=300))
                    return
        except Exception as e:
            logger.debug(f"Could not fetch new trade ID: {e}")
        # Fallback: no direct position button
        await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        # Auto-delete confirmation after 5 minutes
        asyncio.create_task(delete_after_delay(ctx.bot, chat_id, q.message.message_id, delay=300))
    else:
        msg = "❌ **Execution failed**\n\n"
        if error_msg:
            msg += f"**Error:** `{error_msg}`\n\n"
        msg += "Possible reasons:\n• Freqtrade API error\n• Invalid pair/params\n• Exchange down"
        logger.error(f"Trade execution failed for {p['symbol']}: {error_msg}")
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([
        [InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")],
        [InlineKeyboardButton("⬅️ MAIN", callback_data="main")]
    ]))
    # Auto-delete error confirmation after 5 minutes
    asyncio.create_task(delete_after_delay(ctx.bot, chat_id, q.message.message_id, delay=300))

# ── Watch Command (Bot Status) ──
async def watch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /watch — Show real-time bot status:
    - Freqtrade (strategy, uptime, open trades)
    - Telegram Bot (uptime)
    - Watchdog (uptime)
    - System info (memory, CPU)
    """
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id

    # Gather process info
    lines = ["📊 **Bot Status**" "\n"]

    # Helper: find process by command pattern
    def find_process(pattern):
        for p in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time']):
            try:
                cmd = ' '.join(p.info['cmdline'] or [])
                if pattern in cmd:
                    return p
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    # Freqtrade
    ft = find_process('freqtrade trade')
    if ft:
        uptime = int(time.time() - ft.create_time())
        hours, remainder = divmod(uptime, 3600)
        mins, secs = divmod(remainder, 60)
        status_line = (
            f"✅ **Freqtrade** — PID {ft.pid}\n"
            f"Uptime: {hours}h {mins}m {secs}s"
        )
        if uptime < 60:
            status_line += " 🔄 (just restarted)"
        lines.append(status_line)
        # Get strategy from log tail
        try:
            log_tail = subprocess.check_output(
                ['tail', '-20', '/data/.openclaw/workspace/clawforge-repo/logs/freqtrade.log'],
                text=True, timeout=2
            )
            if 'Strategy using' in log_tail:
                for line in log_tail.split('\n'):
                    if 'Strategy using' in line and 'Claw5M' in line:
                        import re
                        m = re.search(r'Strategy using (\S+)', line)
                        if m:
                            lines.append(f"Strategy: {m.group(1)}")
                            break
        except Exception:
            pass
        # Get open trades count from API
        try:
            r = requests.get('http://172.19.0.2:8080/api/v1/status', auth=(API_USER, API_PASS), timeout=3)
            if r.status_code == 200:
                trades_list = r.json()
                if isinstance(trades_list, list):
                    lines.append(f"Open trades: {len(trades_list)}/3")
        except Exception:
            pass
    else:
        # Freqtrade down — check watchdog
        wd = find_process('watchdog.sh')
        if wd:
            # Check recent restart attempt from watchdog.log
            try:
                with open('/data/.openclaw/workspace/clawmimoto-bot/watchdog.log', 'r') as f:
                    log_lines = f.readlines()
                # Find last "Freqtrade down — restarting..."
                last_ts = None
                for line in reversed(log_lines):
                    if 'freqtrade down' in line.lower() and 'restarting' in line.lower():
                        # Timestamp is at start: "Sun Apr 19 09:42:45 +08 2026"
                        ts_str = line[:30].strip()
                        try:
                            dt = datetime.strptime(ts_str, "%a %b %d %H:%M:%S %z %Y")
                            last_ts = dt
                            break
                        except:
                            continue
                if last_ts and (time.time() - last_ts.timestamp()) < 120:
                    lines.append("❌ **Freqtrade** — DOWN (watchdog restarting...)")
                    lines.append(f"   Last restart attempt: {last_ts.strftime('%H:%M:%S')}")
                else:
                    lines.append("❌ **Freqtrade** — DOWN (watchdog monitoring)")
            except Exception:
                lines.append("❌ **Freqtrade** — DOWN")
        else:
            lines.append("❌ **Freqtrade** — DOWN (no watchdog)")

    # Telegram Bot
    bot = find_process('clawforge.telegram_ui')
    if bot:
        uptime = int(time.time() - bot.create_time())
        hours, remainder = divmod(uptime, 3600)
        mins, secs = divmod(remainder, 60)
        status_line = (
            f"✅ **Telegram Bot** — PID {bot.pid}\n"
            f"Uptime: {hours}h {mins}m {secs}s"
        )
        if uptime < 60:
            status_line += " 🔄 (just restarted)"
        lines.append(status_line)
    else:
        wd = find_process('watchdog.sh')
        if wd:
            try:
                with open('/data/.openclaw/workspace/clawmimoto-bot/watchdog.log', 'r') as f:
                    log_lines = f.readlines()
                last_ts = None
                for line in reversed(log_lines):
                    if 'telegram bot down' in line.lower() and 'restarting' in line.lower():
                        ts_str = line[:30].strip()
                        try:
                            dt = datetime.strptime(ts_str, "%a %b %d %H:%M:%S %z %Y")
                            last_ts = dt
                            break
                        except:
                            continue
                if last_ts and (time.time() - last_ts.timestamp()) < 120:
                    lines.append("❌ **Telegram Bot** — DOWN (watchdog restarting...)")
                    lines.append(f"   Last restart attempt: {last_ts.strftime('%H:%M:%S')}")
                else:
                    lines.append("❌ **Telegram Bot** — DOWN (watchdog monitoring)")
            except Exception:
                lines.append("❌ **Telegram Bot** — DOWN")
        else:
            lines.append("❌ **Telegram Bot** — DOWN (no watchdog)")

    # Watchdog
    watchdog = find_process('watchdog.sh')
    if watchdog:
        # Watchdog is a bash script; get its start time
        uptime = int(time.time() - watchdog.create_time())
        hours, remainder = divmod(uptime, 3600)
        mins, secs = divmod(remainder, 60)
        lines.append(f"✅ **Watchdog** — PID {watchdog.pid}\nUptime: {hours}h {mins}m {secs}s")
    else:
        lines.append("⚠️ **Watchdog** — NOT RUNNING (bot not auto-restarting)")

    # System snapshot
    mem = psutil.virtual_memory()
    lines.append(f"\n💾 Memory: {mem.used/1e9:.1f}GB / {mem.total/1e9:.1f}GB ({mem.percent}%)")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
    )

# ── Profit Command ──
async def profit_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /profit — Show P&L summary:
    - Open positions (unrealized)
    - Closed trades (realized)
    - Today's P&L
    - Win rate, avg win/loss
    """
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    lines = ["💰 **Profit Summary**" "\n"]

    try:
        # Open trades (unrealized) — use /api/v1/status which returns list of open trades
        r_open = requests.get('http://172.19.0.2:8080/api/v1/status', auth=(API_USER, API_PASS), timeout=5)
        if r_open.status_code == 200:
            open_trades = r_open.json()
            if isinstance(open_trades, list):
                total_unrealized = sum(t.get('profit_abs', 0) for t in open_trades)
                lines.append(f"📈 **Open Positions** ({len(open_trades)}/3)")
                for t in open_trades:
                    pnl = t.get('profit_abs', 0)
                    pct = t.get('profit_pct', 0)
                    lines.append(f"  {t['pair']}: {pct:+.1f}% (${pnl:,.2f})")
                lines.append(f"Unrealized Total: ${total_unrealized:,.2f}")
        else:
            lines.append("❌ Cannot fetch open trades")

        # Closed trades (realized) — last 20
        r_closed = requests.get('http://172.19.0.2:8080/api/v1/trades?status=closed&limit=20', auth=(API_USER, API_PASS), timeout=5)
        if r_closed.status_code == 200:
            data_closed = r_closed.json()
            closed_trades = data_closed.get('trades', [])
            if closed_trades:
                total_realized = sum(t.get('profit_abs', 0) for t in closed_trades)
                wins = [t for t in closed_trades if t.get('profit_abs', 0) > 0]
                losses = [t for t in closed_trades if t.get('profit_abs', 0) < 0]
                win_rate = len(wins) / len(closed_trades) * 100 if closed_trades else 0
                avg_win = sum(t.get('profit_abs', 0) for t in wins) / len(wins) if wins else 0
                avg_loss = sum(t.get('profit_abs', 0) for t in losses) / len(losses) if losses else 0
                lines.append(f"\n📊 **Closed Trades** (last {len(closed_trades)})")
                lines.append(f"Realized Total: ${total_realized:,.2f}")
                lines.append(f"Win Rate: {win_rate:.0f}% ({len(wins)}W/{len(losses)}L)")
                lines.append(f"Avg Win: ${avg_win:,.2f} | Avg Loss: ${avg_loss:,.2f}")
            else:
                lines.append("\n📊 No closed trades yet")
        else:
            lines.append("\n❌ Cannot fetch closed trades")

        # Today's P&L (sum of closed trades opened today)
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        today_trades = [t for t in closed_trades if t.get('open_date', '').startswith(today)]
        if today_trades:
            today_pnl = sum(t.get('profit_abs', 0) for t in today_trades)
            lines.append(f"\n📅 **Today's P&L**: ${today_pnl:,.2f}")

    except Exception as e:
        logger.error(f"Profit command error: {e}", exc_info=True)
        lines.append(f"\n❌ Error: {str(e)[:100]}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
    )

# ── Daily Command ──
async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /daily — Show today's trading summary:
    - Trades opened/closed today
    - Realized & unrealized P&L
    - Win rate for today's closed trades
    - Best/worst performing pairs
    """
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    lines = ["📅 **Daily Trading Summary**" "\n"]

    try:
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        # Open trades (unrealized) — filter those opened today
        r_open = requests.get('http://172.19.0.2:8080/api/v1/status', auth=(API_USER, API_PASS), timeout=5)
        open_today = []
        if r_open.status_code == 200:
            open_trades = r_open.json()
            if isinstance(open_trades, list):
                for t in open_trades:
                    open_date = t.get('open_date', '')
                    if open_date and open_date.startswith(today):
                        open_today.append(t)
                if open_today:
                    lines.append(f"📈 **Open Today** ({len(open_today)})")
                    for t in open_today:
                        pnl = t.get('profit_abs', 0)
                        pct = t.get('profit_pct', 0)
                        lines.append(f"  {t['pair']}: {pct:+.1f}% (${pnl:,.2f})")
                else:
                    lines.append("📈 No open trades from today yet")

        # Closed trades (realized) — opened today
        r_closed = requests.get('http://172.19.0.2:8080/api/v1/trades?status=closed&limit=50', auth=(API_USER, API_PASS), timeout=5)
        closed_today = []
        if r_closed.status_code == 200:
            data_closed = r_closed.json()
            all_closed = data_closed.get('trades', [])
            for t in all_closed:
                open_date = t.get('open_date', '')
                if open_date and open_date.startswith(today):
                    closed_today.append(t)
            if closed_today:
                total_realized = sum(t.get('profit_abs', 0) for t in closed_today)
                wins = [t for t in closed_today if t.get('profit_abs', 0) > 0]
                losses = [t for t in closed_today if t.get('profit_abs', 0) < 0]
                win_rate = len(wins) / len(closed_today) * 100 if closed_today else 0
                lines.append(f"\n✅ **Closed Today** ({len(closed_today)})")
                lines.append(f"Realized P&L: ${total_realized:,.2f}")
                lines.append(f"Win Rate: {win_rate:.0f}% ({len(wins)}W/{len(losses)}L)")
                # Best/worst
                if closed_today:
                    best = max(closed_today, key=lambda x: x.get('profit_abs', 0))
                    worst = min(closed_today, key=lambda x: x.get('profit_abs', 0))
                    lines.append(f"Best: {best['pair']} (${best['profit_abs']:,.2f})")
                    lines.append(f"Worst: {worst['pair']} (${worst['profit_abs']:,.2f})")
            else:
                lines.append("\n✅ No closed trades from today yet")

        # Combined today's P&L (realized + unrealized)
        realized = sum(t.get('profit_abs', 0) for t in closed_today)
        unrealized = sum(t.get('profit_abs', 0) for t in open_today)
        total_today = realized + unrealized
        lines.append(f"\n💹 **Today's Net P&L**: ${total_today:,.2f}")

    except Exception as e:
        logger.error(f"Daily command error: {e}", exc_info=True)
        lines.append(f"\n❌ Error: {str(e)[:100]}")

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]])
    )

# ── Scan Command ──
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scan command: run AI scan asynchronously and send results."""
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    # Clear stale scan cache before running new scan
    if chat_id in user_state and "scan_results" in user_state[chat_id]:
        user_state[chat_id].pop("scan_results", None)
    # Acknowledge immediately
    status_msg = await update.message.reply_text(
        "🔍 **Scanning market...**\n\nFetching Bybit hot pairs, analyzing 5M charts, order book, sentiment...",
        parse_mode="Markdown"
    )

    async def do_scan():
        try:
            # Run blocking scan in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            setups = await loop.run_in_executor(None, ai_scan_pairs, None, chat_id)

            if not setups:
                try:
                    await status_msg.edit_text("❌ **Scan failed** - No pairs returned.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
                except: pass
                return
            user_state[chat_id]["selected_pairs"] = setups
            # Delete status and send results (ignore if already deleted)
            try:
                await status_msg.delete()
            except: pass
            await send_scan_message(chat_id, setups, context)
        except Exception as e:
            logger.error(f"Scan error: {e}", exc_info=True)
            try:
                await status_msg.edit_text(f"❌ **Scan error**: {str(e)[:100]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
            except: pass

    # Schedule scan (allows immediate response to /scan)
    asyncio.create_task(do_scan())

async def refresh_scan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-run scan and update message (async)."""
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    query = update.callback_query
    await query.answer("🔄 Running fresh scan...")
    chat_id = query.message.chat_id
    # Clear stale scan cache before refresh
    if chat_id in user_state and "scan_results" in user_state[chat_id]:
        user_state[chat_id].pop("scan_results", None)

    async def do_refresh():
        try:
            # Run blocking scan in executor
            loop = asyncio.get_event_loop()
            setups = await loop.run_in_executor(None, ai_scan_pairs, None, chat_id)

            if not setups:
                try:
                    await query.edit_message_text("❌ **Scan failed** - No pairs returned.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]]))
                except: pass
                return
            user_state[chat_id]["selected_pairs"] = setups
            try:
                await query.message.delete()
            except: pass
            await send_scan_message(chat_id, setups, context)
        except Exception as e:
            logger.error(f"Refresh scan error: {e}", exc_info=True)
            try:
                await query.edit_message_text(
                    f"❌ **Refresh failed**: {str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 RETRY", callback_data="/scan")],
                        [InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")]
                    ])
                )
            except: pass
    asyncio.create_task(do_refresh())

async def send_scan_message(chat_id, setups, context):
    """Send 4 separate scan result messages, each with EXECUTE and SKIP buttons."""
    # Clear old scan messages for this user first (auto-delete)
    scan_msg_ids = user_state.get(chat_id, {}).get('scan_msg_ids', [])
    for old_msg_id in scan_msg_ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_msg_id)
        except Exception:
            pass
    user_state[chat_id]['scan_msg_ids'] = []

    # Store results in user_state for later retrieval by callbacks
    user_state.setdefault(chat_id, {})['scan_results'] = {p['symbol']: p for p in setups}
    mode_header = get_mode_header(chat_id)
    for idx, p in enumerate(setups, 1):
        # Calculate SL/TP percentages for display
        entry = p.get('entry', p.get('current_price', 0))
        sl = p.get('sl', 0)
        tp = p.get('tp', 0)
        if p.get('direction') == 'LONG':
            sl_pct = ((sl - entry) / entry * 100) if entry else 0
            tp_pct = ((tp - entry) / entry * 100) if entry else 0
        else:
            sl_pct = ((entry - sl) / entry * 100) if entry else 0
            tp_pct = ((entry - tp) / entry * 100) if entry else 0
        # Score-based color coding
        ai_score = p.get('ai_score', 0)
        if ai_score >= 8:
            score_emoji = "🟢"
            urgency = "STRONG SETUP"
        elif ai_score >= 6:
            score_emoji = "🟡"
            urgency = "MODERATE"
        else:
            score_emoji = "🔴"
            urgency = "WEAK — SKIP?"
        dir_emoji = "📈" if p['direction'] == 'LONG' else "📉"
        session = p.get('session', 'manual')
        # Format block
        text = (
            f"{mode_header}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{score_emoji} SCAN #{idx} — {urgency}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪙 {p['symbol']} | {p['direction']} {dir_emoji}\n"
            f"💰 Entry: {p.get('entry_strategy','market').upper()} @ ${p.get('current_price',0):,.2f}\n"
            f"🛡 SL: ${sl:,.4f} (-{abs(sl_pct):.1f}% margin)\n"
            f"🎯 TP: ${tp:,.4f} (+{tp_pct:.1f}% margin)\n"
            f"📊 RRR: {p.get('rrr',0):.1f}:1\n"
            f"📈 Volume: {p.get('volume_ratio',0):.1f}x | 4H: {p.get('change',0):+.1f}%\n"
            f"🤖 AI: {ai_score}/10 | Conf: {p.get('confidence',0)}%\n"
            f"🕐 Session: {session}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ EXECUTE", callback_data=f"exec_confirm_{p['symbol']}")],
            [InlineKeyboardButton("⏭ SKIP", callback_data=f"skip_{p['symbol']}")]
        ])
        try:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="Markdown")
            # Track message ID for auto-delete on next scan
            user_state[chat_id].setdefault('scan_msg_ids', []).append(msg.message_id)
        except Exception as e:
            logger.error(f"Failed to send scan result for {p['symbol']}: {e}")

# ── Alert ──
async def alert_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle alert set callback: expects data like '/alert PAIR PRICE'."""
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    query = update.callback_query
    await query.answer()
    parts = query.data.split()
    if len(parts) < 3:
        await query.edit_message_text("❌ Invalid alert format.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    pair = parts[1]
    try:
        price = float(parts[2])
    except ValueError:
        await query.edit_message_text("❌ Invalid price.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    alert_id = f"{pair}_{price}_{datetime.utcnow().timestamp()}"
    context.bot_data.setdefault('alerts', {})[alert_id] = {
        'pair': pair,
        'price': price,
        'user_id': query.from_user.id,
        'created_at': datetime.utcnow().isoformat()
    }
    await query.edit_message_text(
        f"🔔 **Alert Set**\n\n• Pair: {pair}\n• Trigger: ${price:,.2f}\n• ID: `{alert_id[:8]}`\n\n_You'll get notified when price hits this level_",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data=f"pair_{pair}")]])
    )

# ── Custom Pair Scan ──
async def custom_scan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle custom pair scan button press."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    # Extract pair from callback data: custom_scan_BTC/USDT
    pair = q.data.replace("custom_scan_", "")

    # Run AI analysis
    result = analyze_pair(pair)
    chat_id = q.message.chat_id
    # Enrich with user-specific trade params (quantity, stake, etc.)
    result = enrich_trade_params(result, chat_id)
    user_state[chat_id]["selected_pairs"] = [result]

    # Build detail view (same as pair_detail_cb)
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    conf = result["confidence"]
    greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
    # Get real-time price for alert (prefer fresh ticker, fallback to kline price)
    symbol_clean = result['symbol'].replace('/', '')
    cur_price = result.get('current_price', 0)
    try:
        ticker_price, _ = get_binance_ticker(symbol_clean)
        if ticker_price and ticker_price > 0:
            cur_price = ticker_price
    except Exception as e:
        logger.debug(f"Ticker fetch failed: {e}")
    # Enriched trade params (already enriched above)
    entry = result.get('entry', cur_price or 0)
    sl = result.get('sl', 0)
    tp = result.get('tp', 0)
    rrr = result.get('rrr', 2.0)
    stake = result.get('stake_amount', 0)
    qty = result.get('quantity', 0)
    lev = state['leverage']
    # Direction arrow for SL/TP (P&L percentage at those levels)
    if result['direction'] == 'LONG':
        sl_pct = (sl/entry - 1)*100 if entry else 0
        tp_pct = (tp/entry - 1)*100 if entry else 0
    else:
        sl_pct = (entry - sl) / entry * 100 if entry else 0
        tp_pct = (entry - tp) / entry * 100 if entry else 0
    proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
    text = (f"📊 {result['symbol']} {result['direction']} {state['trade_mode']}\n\n"
            f"Balance: {bal}\n"
            f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
            f"Reasons: {' | '.join(result['reasons'])}\n"
            f"Leverage: {lev}x  |  Margin: {state['margin']}%  (${stake:,.0f})\n"
            f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
            f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
            f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
            f"Trailing: activates +50%, offset 2%\n"
            f"Confidence: {conf}% {greens} 🦞")
    kb = []
    # Only show EXECUTE if pair is valid on exchange (admins bypass)
    user_id = q.from_user.id
    if is_pair_valid_for_user(result['symbol'], user_id):
        kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
    # Add SET ALERT button with current price
    if cur_price and cur_price > 0:
        kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
    kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{result['symbol']}")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ── Error handler ──
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    exc = ctx.error
    # Ignore benign Telegram errors
    if isinstance(exc, BadRequest) and "Message is not modified" in str(exc):
        return
    logger.error(f"Exception: {exc}", exc_info=exc)

async def set_commands(app: Application) -> None:
    """Set restricted bot commands — only expose our custom trading commands."""
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("cmd", "Show command center"),
        BotCommand("scan", "AI scan of hot pairs"),
        BotCommand("watch", "Check bot status"),
        BotCommand("profit", "Show P&L summary"),
        BotCommand("daily", "Today's trading summary"),
    ])
    # Send startup notification to admin
    admin_id = os.getenv("ADMIN_TELEGRAM_ID", "7093901111")
    try:
        msg = await app.bot.send_message(
            chat_id=admin_id,
            text="✅ *Clawmimoto Bot online*\n\nFreqtrade API connected. All systems go.",
            parse_mode="Markdown"
        )
        # Auto-delete after 3 seconds
        async def delete_later():
            await asyncio.sleep(3)
            try:
                await app.bot.delete_message(chat_id=admin_id, message_id=msg.message_id)
            except: pass
        asyncio.create_task(delete_later())
    except Exception as e:
        logger.debug(f"Startup notification failed: {e}")

# ── Build & Run ──
# ── Refresh Pair Detail ──
async def refresh_pair_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Refresh analysis for a pair from detail view."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("🔄 Refreshing analysis...")
    chat_id = q.message.chat_id
    # Extract symbol from callback data: refresh_pair_BTC/USDT
    symbol = q.data.split("_", 2)[2]
    # Re-analyze
    try:
        result = analyze_pair(symbol)
        result.setdefault('symbol', symbol)
        result.setdefault('direction', 'LONG')
        result.setdefault('change', 0.0)
        result.setdefault('confidence', 85)
        result.setdefault('reasons', ['Volume spike', 'Momentum'])
        result.setdefault('current_price', 0)
        result = enrich_trade_params(result, chat_id)
        # Update selected_pairs
        user_state.setdefault(chat_id, {"selected_pairs": []})
        user_state[chat_id]['selected_pairs'] = [result]
        # Render detail (same as select_pair_cb rendering)
        state = get_state(chat_id)
        real, mock = get_balance()
        bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
        conf = result['confidence']
        greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
        cur_price = result.get('current_price', 0)
        if not cur_price:
            try:
                symbol_clean = result['symbol'].replace('/', '')
                cur_price, _ = get_binance_ticker(symbol_clean)
            except: pass
        entry = result.get('entry', cur_price or 0)
        sl = result.get('sl', 0)
        tp = result.get('tp', 0)
        rrr = result.get('rrr', 2.0)
        stake = result.get('stake_amount', 0)
        qty = result.get('quantity', 0)
        lev = state['leverage']
        if result['direction'] == 'LONG':
            sl_pct = (sl/entry - 1)*100 if entry else 0
            tp_pct = (tp/entry - 1)*100 if entry else 0
        else:
            sl_pct = (entry - sl) / entry * 100 if entry else 0
            tp_pct = (entry - tp) / entry * 100 if entry else 0
        proj_profit = stake * lev * abs(tp - entry) / entry if entry else 0
        back_target = user_state[chat_id].get('pair_detail_back', 'manual_mode')
        text = (f"📊 {result['symbol']} {result['direction']} {state['trade_mode']}\n\n"
                f"Balance: {bal}\n"
                f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
                f"Reasons: {' | '.join(result['reasons'])}\n"
                f"Leverage: {lev}x  |  Margin: {state['margin']}%  (${stake:,.0f})\n"
                f"Entry: ${entry:,.4f}  |  SL: ${sl:,.4f} ({sl_pct:+.1f}%)  |  TP: ${tp:,.4f} ({tp_pct:+.1f}%)\n"
                f"RRR: {rrr:.1f}  |  Qty: {qty:.6f}\n"
                f"Projected TP P&L: ${proj_profit:,.2f} (+{tp_pct:.1f}%)\n"
                f"Trailing: activates +50%, offset 2%\n"
                f"Confidence: {conf}% {greens} 🦞")
        kb = []
        user_id = update.effective_user.id
        if is_pair_valid_for_user(result['symbol'], user_id):
            kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
        try:
            symbol_clean = result['symbol'].replace('/', '')
            cur_price, _ = get_binance_ticker(symbol_clean)
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
        except Exception as e:
            logger.debug(f"Alert price fetch failed: {e}")
        kb.append([InlineKeyboardButton("🔄 REFRESH", callback_data=f"refresh_pair_{result['symbol']}")])
        kb.append([InlineKeyboardButton("⬅️ BACK", callback_data=back_target)])
        await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        logger.error(f"refresh_pair_detail error: {e}", exc_info=True)
        await q.edit_message_text(f"❌ Refresh failed: {str(e)[:100]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
async def history_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    try:
        import asyncio
        def _fetch_history():
            import requests as _req
            r = _req.get(
                f"{SUPABASE_URL}/rest/v1/trades",
                params={"is_open": "eq.false", "order": "close_date.desc", "limit": "10"},
                headers={"apikey": SUPABASE_ANON_KEY, "Authorization": f"Bearer {SUPABASE_ANON_KEY}"},
                timeout=10
            )
            r.raise_for_status()
            return r.json()
        trades = await asyncio.get_event_loop().run_in_executor(None, _fetch_history)
        if not trades:
            text = "📋 *TRADE HISTORY*\n\nNo closed trades yet."
        else:
            lines = ["📋 *TRADE HISTORY*", "━━━━━━━━━━━━━━━━━━━━", ""]
            for t in trades:
                raw_pair = t.get("pair") or ""
                pair = raw_pair.split("/", 1)[0] if "/" in raw_pair else raw_pair
                direction = t.get("direction") or "LONG"
                profit_pct = (t.get("profit_ratio") or 0) * 100
                profit_abs = t.get("profit_abs") or 0
                exit_reason = (t.get("exit_reason") or "").replace("_", " ")
                close_date = (t.get("close_date") or "")[:16].replace("T", " ")
                leverage = t.get("leverage") or 20
                icon = "✅" if profit_pct > 0 else "❌"
                sign = "+" if profit_pct > 0 else ""
                lines.append(
                    f"{icon} *{pair}* {direction} `{leverage}x`\n"
                    f"   P&L: `{sign}{profit_pct:.2f}%` · ${sign}{profit_abs:.2f}\n"
                    f"   Exit: `{exit_reason}`\n"
                    f"   📅 `{close_date}`\n"
                )
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            text = "\n".join(lines)
    except Exception as e:
        logger.error(f"History fetch error: {e}")
        text = "📋 *TRADE HISTORY*\n\nFailed to load. Try again."
    kb = [[InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    # Wait for Freqtrade API to become available (retry up to 10 times)
    max_tries = 10
    for i in range(max_tries):
        test = api_get("/api/v1/ping")
        if test:
            logger.info("Connected to Freqtrade API")
            break
        logger.warning(f"Freqtrade API not reachable (attempt {i+1}/{max_tries}), retrying in 5s...")
        time.sleep(5)
    else:
        logger.error("Cannot connect to Freqtrade API after retries — exiting")
        return
    logger.info("Connected to Freqtrade API")
    app = Application.builder().token(TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler("watch", watch_command))
    app.add_handler(CommandHandler("profit", profit_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler(["start", "cmd"], start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    # Callbacks
    app.add_handler(CallbackQueryHandler(main_cb, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(toggle_mode_cb, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(toggle_trading_mode_cb, pattern="^toggle_trading_mode$"))
    app.add_handler(CallbackQueryHandler(socials_cb, pattern="^socials$"))
    app.add_handler(CallbackQueryHandler(lambda u,c: u.callback_query.answer(), pattern="^noop$"))
    app.add_handler(CallbackQueryHandler(show_balance_cb, pattern="^show_balance$"))
    app.add_handler(CallbackQueryHandler(show_stats_cb, pattern="^show_stats$"))
    app.add_handler(CallbackQueryHandler(show_gains_cb, pattern="^show_gains$"))
    app.add_handler(CallbackQueryHandler(show_news_cb, pattern="^show_news$"))
    app.add_handler(CallbackQueryHandler(toggle_macro_cb, pattern="^toggle_macro$"))
    app.add_handler(CallbackQueryHandler(cooknow_cb, pattern="^cooknow$"))
    app.add_handler(CallbackQueryHandler(settings_cb, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(settings_tab_cb, pattern="^settings_tab_(manual|session)$"))
    app.add_handler(CallbackQueryHandler(toggle_sutamm_cb, pattern="^toggle_sutamm$"))
    app.add_handler(CallbackQueryHandler(session_defaults_cb, pattern="^session_defaults$"))
    app.add_handler(CallbackQueryHandler(sl_tp_cb, pattern="^(sl_up|sl_down|tp_up|tp_down|sess_lev_up|sess_lev_down|sess_mar_up|sess_mar_down)$"))
    app.add_handler(CallbackQueryHandler(set_trade_mode_cb, pattern="^set_mock$"))
    app.add_handler(CallbackQueryHandler(set_trade_mode_cb, pattern="^set_real$"))
    app.add_handler(CallbackQueryHandler(set_trade_mode_cb, pattern="^set_manual$"))
    app.add_handler(CallbackQueryHandler(set_trade_mode_cb, pattern="^set_session$"))
    app.add_handler(CallbackQueryHandler(trade_menu_cb, pattern="^trade_menu$"))
    app.add_handler(CallbackQueryHandler(scan_pair_prompt_cb, pattern="^scan_pair_prompt$"))
    app.add_handler(CallbackQueryHandler(custom_scan_cb, pattern=r"^custom_scan_"))
    app.add_handler(CallbackQueryHandler(session_mode_cb, pattern="^session_mode$"))
    app.add_handler(CallbackQueryHandler(session_adjust_cb, pattern="^(lev|mar)_(up|down)$"))
    app.add_handler(CallbackQueryHandler(ai_scan_cb, pattern="^ai_scan$"))
    app.add_handler(CallbackQueryHandler(pair_detail_cb, pattern="^pair_"))
    app.add_handler(CallbackQueryHandler(select_pair_cb, pattern="^select_"))
    app.add_handler(CallbackQueryHandler(manual_mode_cb, pattern="^manual_mode$"))
    app.add_handler(CallbackQueryHandler(add_pair_menu_cb, pattern="^add_pair_menu$"))
    app.add_handler(CallbackQueryHandler(other_pair_input_cb, pattern="^other_pair_input$"))
    app.add_handler(CallbackQueryHandler(more_opportunities_cb, pattern="^more_opportunities$"))
    app.add_handler(CallbackQueryHandler(positions_cb, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(pos_detail_cb, pattern="^pos_"))
    app.add_handler(CallbackQueryHandler(refresh_positions_cb, pattern="^refresh_positions$"))
    app.add_handler(CallbackQueryHandler(other_positions_cb, pattern="^other_positions$"))
    app.add_handler(CallbackQueryHandler(closed_positions_cb, pattern="^closed_positions$"))
    app.add_handler(CallbackQueryHandler(refresh_closed_cb, pattern="^refresh_closed$"))
    app.add_handler(CallbackQueryHandler(close_position_cb, pattern="^close_"))
    app.add_handler(CallbackQueryHandler(share_pnl_cb, pattern="^share_"))
    app.add_handler(CallbackQueryHandler(execute_cb, pattern="^execute$"))
    app.add_handler(CallbackQueryHandler(market_now_cb, pattern="^market_now$"))
    app.add_handler(CallbackQueryHandler(confirm_exec_cb, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(alert_set_callback, pattern=r'^/alert '))
    app.add_handler(CallbackQueryHandler(refresh_scan_callback, pattern=r'^refresh_scan$'))
    app.add_handler(CallbackQueryHandler(refresh_pair_detail_cb, pattern=r'^refresh_pair_'))
    app.add_handler(CallbackQueryHandler(exec_confirm_cb, pattern=r'^exec_confirm_'))
    app.add_handler(CallbackQueryHandler(skip_pair_cb, pattern=r'^skip_'))
    app.add_handler(CallbackQueryHandler(session_approve_cb, pattern=r'^session_approve_'))
    app.add_handler(CallbackQueryHandler(session_skip_cb, pattern=r'^session_skip_'))
    app.add_handler(CallbackQueryHandler(history_cb, pattern='^history$'))
    app.add_error_handler(error_handler)
    logger.info("Starting Clawmimoto Telegram UI...")
    # Start background snapshot thread (every 4 hours)
    def _snapshot_thread():
        """Runs in separate thread; uses synchronous requests to Telegram API."""
        import time, json
        CHANNEL_LOG_PATH = Path("/data/.openclaw/workspace/clawmimoto-bot/user_data/channel_message_log.json")
        CHANNEL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        while True:
            time.sleep(14400)  # 4 hours
            try:
                msg = build_market_snapshot()
                token = TOKEN
                chat_id = os.getenv("RIGHTCLAW_CHANNEL", "@RightclawTrade")
                # Try channel first
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {"chat_id": chat_id, "text": msg, "parse_mode": "Markdown", "disable_web_page_preview": True}
                r = requests.post(url, json=payload, timeout=10)
                if r.status_code == 200:
                    result = r.json()
                    msg_id = result.get("result", {}).get("message_id")
                    if msg_id:
                        entry = {
                            "message_id": msg_id,
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "chat_id": chat_id,
                            "type": "market_snapshot",
                        }
                        logs = []
                        if CHANNEL_LOG_PATH.exists():
                            try:
                                with open(CHANNEL_LOG_PATH, "r", encoding="utf-8") as lf:
                                    logs = json.load(lf)
                            except Exception:
                                logs = []
                        logs.append(entry)
                        with open(CHANNEL_LOG_PATH, "w", encoding="utf-8") as lf:
                            json.dump(logs, lf, indent=2, ensure_ascii=False)
                        logger.info(f"✅ Market snapshot sent to {chat_id} (msg_id={msg_id})")
                    continue
                # Fallback to DM if channel fails (e.g., bot not in channel)
                chat_id = os.getenv("TELEGRAM_CHAT_ID", "7093901111")
                payload["chat_id"] = chat_id
                r = requests.post(url, json=payload, timeout=10)
                if r.status_code == 200:
                    logger.info(f"✅ Market snapshot sent to DM {chat_id}")
                else:
                    logger.warning(f"Snapshot failed: {r.status_code} {r.text[:100]}")
            except Exception as e:
                logger.error(f"Snapshot thread error: {e}")
    t = threading.Thread(target=_snapshot_thread, daemon=True)
    t.start()

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

