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
from datetime import datetime, timezone
from pathlib import Path
import feedparser
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, error, BotCommand
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

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
            # Fetch fresh trade data
            t_data = api_get(f"/api/v1/trades?trade_id={trade_id}")
            if not t_data or not t_data.get("trades"):
                continue  # trade gone, will be cleaned up by cancel
            t = t_data["trades"][0]
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
API_URL = os.getenv("FREQTRADE_API_URL", "http://127.0.0.1:8080")
API_USER = os.getenv("FREQTRADE_API_USER", "admin")
API_PASS = os.getenv("FREQTRADE_API_PASS", "admin")
BINGX_API_KEY = os.getenv("BINGX_API_KEY")
BINGX_API_SECRET = os.getenv("BINGX_API_SECRET")
STEPFUN_API_KEY = os.getenv("STEPFUN_API_KEY")

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
user_state = {}  # {chat_id: {"leverage": 50, "margin": 1, "trade_mode": "MOCK", "selected_pair": None}}

def get_state(chat_id):
    if chat_id not in user_state:
        user_state[chat_id] = {"leverage": 50, "margin": 1, "trade_mode": "MOCK", "selected_pair": None}
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

# ── BingX API ──
def bingx_signed_request(method, endpoint, params=None):
    if not BINGX_API_KEY or not BINGX_API_SECRET:
        return None
    base_url = "https://open-api.bingx.com"
    url = f"{base_url}{endpoint}"
    if params:
        sorted_params = sorted(params.items())
        query = '&'.join([f"{k}={v}" for k, v in sorted_params])
        signature = hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        url += f"?{query}&signature={signature}"
    headers = {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}
    try:
        r = requests.request(method, url, headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"BingX API error: {e}")
        return None

def get_bingx_hot_pairs(limit=5):
    """Fetch top hot pairs from BingX ticker with Binance fallback."""
    try:
        data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", timeout=5)
        if data and "data" in data:
            pairs = []
            for item in data["data"][:limit]:
                symbol = item.get("symbol", "").upper()
                # BingX uses BTC-USDT format; convert to BTC/USDT for display
                symbol = symbol.replace("-", "/")
                pairs.append(symbol)
            logger.info(f"BingX hot pairs: {pairs}")
            return pairs
    except Exception as e:
        logger.debug(f"BingX hot pairs error: {e}")
    # Fallback to Binance 24hr gainers
    try:
        r = requests.get("https://api.binance.com/api/v3/ticker/24hr", timeout=5)
        if r.status_code == 200:
            data = r.json()
            # Sort by percentChange descending, exclude stablecoins
            stable = ["USDT", "USDC", "BUSD", "DAI"]
            filtered = [d for d in data if not any(s in d.get("symbol", "") for s in stable)]
            filtered.sort(key=lambda x: float(x.get("priceChangePercent", 0)), reverse=True)
            pairs = [f"{d['symbol'][:-4]}/{d['symbol'][-4:]}" for d in filtered[:limit]]
            logger.info(f"Binance fallback hot pairs: {pairs}")
            return pairs
    except Exception as e:
        logger.debug(f"Binance fallback error: {e}")
    # Ultimate fallback
    fallback = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT"][:limit]
    logger.warning("All hot pair sources failed, using hardcoded list")
    return fallback

def get_bingx_klines(symbol, interval="5m", limit=50):
    """Fetch klines from BingX with Binance fallback."""
    # Try BingX first
    try:
        data = bingx_signed_request("GET", "/openApi/swap/v2/quote/klines", {"symbol": symbol, "interval": interval, "limit": str(limit)}, timeout=5)
        if data and "data" in data and len(data["data"]) >= limit:
            logger.info(f"Data source: BingX klines for {symbol}")
            return data
    except Exception as e:
        logger.debug(f"BingX klines error: {e}")
    # Fallback to Binance
    try:
        binance_symbol = symbol.replace("/", "")
        url = f"https://api.binance.com/api/v3/klines?symbol={binance_symbol}&interval={interval}&limit={limit}"
        r = requests.get(url, timeout=5)
        if r.status_code == 200:
            raw = r.json()
            candles = []
            for c in raw:
                candles.append({
                    "open": c[1], "high": c[2], "low": c[3], "close": c[4], "volume": c[5]
                })
            logger.info(f"Binance klines fallback for {symbol} ({len(candles)} candles)")
            return {"data": candles}
    except Exception as e:
        logger.debug(f"Binance klines fallback error: {e}")
    return None

# ── Single Pair Analyzer ──
def analyze_pair(pair):
    """Analyze a single pair (format 'BTC/USDT') and return result dict."""
    print(f"[DEBUG] analyze_pair called with: {pair}")
    symbol = pair.replace("/", "")
    klines_data = get_bingx_klines(symbol, interval="5m", limit=50)
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
        "entry": 0, "sl": 0, "tp": 0, "rrr": 2.0,
        "current_price": current_price
    }

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

def is_pair_valid_on_bingx(pair: str) -> bool:
    """Check if pair exists on BingX (our exchange) with Binance fallback for resilience."""
    try:
        symbol = pair.replace("/", "-").upper()
        ticker = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": symbol})
        if ticker and "data" in ticker:
            data = ticker["data"]
            price = float(data.get("lastPrice", 0))
            if price > 0:
                return True
    except Exception as e:
        logger.debug(f"BingX validation error for {pair}: {e}")
    # Fallback: check Binance (most pairs cross-listed)
    try:
        symbol = pair.replace("/", "")
        price, _ = get_binance_ticker(symbol)
        return price is not None and price > 0
    except Exception as e:
        logger.debug(f"Binance fallback validation error for {pair}: {e}")
    return False

def is_pair_valid_for_user(pair: str, user_id: int) -> bool:
    """Admin bypass: admins can use any pair without API validation."""
    if is_admin(user_id):
        return True
    return is_pair_valid_on_bingx(pair)

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
    """Return (real_balance, mock_balance)"""
    # Real: from BingX
    real = None
    if BINGX_API_KEY and BINGX_API_SECRET:
        data = bingx_signed_request("GET", "/openApi/swap/v2/account/balance")
        if data and "data" in data:
            for asset in data["data"]:
                if asset.get("asset") == "USDT":
                    real = float(asset.get("available", 0))
    # Mock: from Freqtrade
    mock_data = api_get("/api/v1/balance") or {}
    mock = mock_data.get("currencies", [{}])[0].get("free", 10000)
    return (real, mock)

def format_balance(real, mock, mode):
    """BalRealMoc: display balance based on current mode"""
    if mode == "REAL":
        return f"${real:.3f} USDT" if real is not None else "Real: N/A"
    else:
        return f"{mock:.0f} CLUSDT"

# ── Stats: wins & Gains ──
def get_stats():
    s = api_get("/api/v1/stats") or {}
    wins = s.get("wins", 0)
    losses = s.get("losses", 0)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    realized_pnl = s.get("total_profit_abs", 0)
    return wins, losses, win_rate, realized_pnl

def format_wins():
    w, l, wr, _ = get_stats()
    return f"{w}/{l} ({wr:.0f}%)"

def format_gains():
    _, _, _, pnl = get_stats()
    pnl_pct = (pnl / 10000 * 100) if pnl else 0  # based on $10k initial
    return f"{pnl_pct:+.1f}% ${pnl:,.2f}"

# ── AI Scan ──
def call_stepfun_skill(prompt, retries=1):
    """Call StepFun API with timeout and simple retry."""
    if not STEPFUN_API_KEY:
        return None
    headers = {"Authorization": f"Bearer {STEPFUN_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "step-3.5-flash",
        "messages": [
            {"role": "system", "content": "You are an expert crypto scalping analyst. Provide concise TA with confidence % (80-90) and RRR."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7
    }
    for attempt in range(retries + 1):
        try:
            r = requests.post("https://api.stepfun.ai/v1/chat/completions", json=payload, headers=headers, timeout=10)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"]
            logger.warning(f"StepFun HTTP {r.status_code}: {r.text[:100]}")
        except Exception as e:
            logger.error(f"StepFun error (attempt {attempt+1}): {e}")
        if attempt < retries:
            time.sleep(1)
    return None

def ai_scan_pairs(custom_pairs=None):
    """Scan hot pairs or custom list, get klines (with fallback), call StepFun, return top 4."""
    pairs_to_scan = custom_pairs if custom_pairs else get_bingx_hot_pairs(limit=6)
    results = []
    for pair in pairs_to_scan:
        # Ensure format
        if "/" not in pair:
            pair = f"{pair}/USDT"
        symbol = pair.replace("/", "")
        klines_data = get_bingx_klines(symbol, interval="5m", limit=50)
        change = 0
        volume = 0
        if klines_data and "data" in klines_data and len(klines_data["data"]) >= 2:
            closes = [float(k["close"]) for k in klines_data["data"][-10:]]
            if len(closes) >= 2:
                change = (closes[-1] - closes[-2]) / closes[-2] * 100
            volume = sum(float(k["volume"]) for k in klines_data["data"][-5:])
        # AI reasoning
        prompt = f"Scalp analysis for {pair} 5M: change {change:.2f}%, volume {volume:.0f}. Give: direction (LONG/SHORT), confidence 80-90%, RRR 1.5-3.0, 3 reasons."
        ai_text = call_stepfun_skill(prompt)
        direction = "LONG" if change >= 0 else "SHORT"
        confidence = 85 if change >= 0 else 75
        reasons = ["High volume", "Momentum", "AI signal"]
        entry = 0; sl = 0; tp = 0; rrr = 0
        if ai_text:
            ai_lower = ai_text.lower()
            if "short" in ai_lower:
                direction = "SHORT"
            if "confidence" in ai_lower:
                try:
                    confidence = int(''.join(filter(str.isdigit, ai_text.split("confidence")[1].split("%")[0])))
                except: pass
            reasons = [line.strip("- * ") for line in ai_text.split('\n') if line.strip()][:3] or reasons
        results.append({
            "symbol": pair,
            "direction": direction,
            "change": round(change, 2),
            "volume": volume,
            "confidence": confidence,
            "reasons": reasons,
            "entry": entry, "sl": sl, "tp": tp, "rrr": rrr
        })
    # Sort by confidence desc, take top 4
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results[:4]

# ── UI Builders ──
def mode_button(mode):
    label = "🔴 REAL" if mode == "REAL" else "🟢 MOCK"
    return InlineKeyboardButton(f"Mode: {label}", callback_data="toggle_mode")

def balance_button(mode):
    real, mock = get_balance()
    bal = format_balance(real, mock, mode)
    return InlineKeyboardButton(f"Balance: {bal}", callback_data="show_balance")

def wins_button():
    return InlineKeyboardButton(f"Win/Loss: {format_wins()}", callback_data="show_stats")

def gains_button():
    return InlineKeyboardButton(f"Gains: {format_gains()}", callback_data="show_gains")

def lev_margin_buttons(state):
    lev = state["leverage"]
    mar = state["margin"]
    # Leverage: +10 / -10
    lev_plus = InlineKeyboardButton("➕ Leverage", callback_data="lev_up")
    lev_label = InlineKeyboardButton(f"{lev}x", callback_data="lev_show")
    lev_minus = InlineKeyboardButton("➖ Leverage", callback_data="lev_down")
    # Margin: +1% / -1%
    mar_plus = InlineKeyboardButton("➕ Margin", callback_data="mar_up")
    mar_label = InlineKeyboardButton(f"{mar}%", callback_data="mar_show")
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
    kb = [
        [mode_button(state["trade_mode"])],
        [wins_button(), gains_button()],
        [InlineKeyboardButton("📈 TRADE MENU", callback_data="trade_menu")],
        [InlineKeyboardButton("📊 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("📈 MARKET NOW", callback_data="market_now")],
    ]
    await update.message.reply_text(f"🏠 **Clawmimoto Command Center**\n\n{news}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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
    news = get_market_news()
    kb = [
        [mode_button(state["trade_mode"])],
        [wins_button(), gains_button()],
        [InlineKeyboardButton("📈 TRADE MENU", callback_data="trade_menu")],
        [InlineKeyboardButton("📊 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("📈 MARKET NOW", callback_data="market_now")],
    ]
    await q.edit_message_text(f"🏠 **Clawmimoto Command Center**\n\n{news}", reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

async def toggle_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["trade_mode"] = "REAL" if state["trade_mode"] == "MOCK" else "MOCK"
    # Return to main
    await main_cb(update, ctx)

async def show_balance_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    mode_label = "REAL" if state["trade_mode"] == "REAL" else "MOCK"
    await q.edit_message_text(f"💼 **Balance ({mode_label})**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main")]]))

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
    for label, bingx_sym, binance_sym, okx_sym, cg_id in pairs:
        price, change, source = None, None, None
        # BingX
        try:
            ticker = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": bingx_sym})
            if ticker and "data" in ticker:
                d = ticker["data"]
                price, change = float(d["lastPrice"]), float(d["priceChangePercent"])
                source = "BingX"
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
    """Fetch real crypto news from RSS feeds (no caching, no storage)."""
    feeds = [
        "https://cointelegraph.com/rss",
        "https://feeds.coindesk.com/coindesk/bitcoin",
        "https://decrypt.co/feed",
        "https://theblock.co/feed",
    ]
    articles = []
    for url in feeds:
        try:
            d = feedparser.parse(url)
            if d.entries:
                entry = d.entries[0]  # most recent from this feed
                title = entry.get('title', '').strip()
                link = entry.get('link', '').strip()
                # Strip UTM tracking params from URL
                if '?' in link and 'utm_' in link:
                    link = link.split('?')[0]
                if title and link:
                    articles.append((title, link))
        except Exception as e:
            logger.debug(f"RSS fetch error from {url}: {e}")
    # Deduplicate by title and limit to 4
    seen = set()
    uniq = []
    for title, link in articles:
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
    # Define pairs: (display_label, bingx_symbol, binance_symbol, okx_symbol, coingecko_id)
    pairs = [
        ("BTC", "BTC-USDT", "BTCUSDT", "BTC-USDT", "bitcoin"),
        ("ETH", "ETH-USDT", "ETHUSDT", "ETH-USDT", "ethereum"),
        ("SOL", "SOL-USDT", "SOLUSDT", "SOL-USDT", "solana"),
        ("BNB", "BNB-USDT", "BNBUSDT", "BNB-USDT", "binancecoin"),
    ]
    message = "📈 Market Now\n\n"
    sources = {"BingX": False, "Binance": False, "OKX": False, "CoinGecko": False}
    for label, bingx_sym, binance_sym, okx_sym, cg_id in pairs:
        price = None
        change = None
        source = None
        # 1. Try BingX
        try:
            ticker = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": bingx_sym})
            if ticker and "data" in ticker:
                d = ticker["data"]
                price = float(d.get("lastPrice", 0))
                change = float(d.get("priceChangePercent", 0))
                source = "BingX"
                sources["BingX"] = True
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
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    kb = [
        [InlineKeyboardButton("🤖 SESSION MODE", callback_data="session_mode")],
        [InlineKeyboardButton("👷 MANUAL MODE", callback_data="manual_mode")],
        [InlineKeyboardButton("🔍 SCAN PAIR", callback_data="scan_pair_prompt")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="main")],
    ]
    await q.edit_message_text(f"⏰ **Select Trading Mode**\n\nBalance: {bal}", reply_markup=InlineKeyboardMarkup(kb))

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
        reply_markup=InlineKeyboardMarkup(kb)
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
    pairs = ai_scan_pairs()
    user_state[chat_id]["selected_pairs"] = pairs
    kb = grid_2x2(pairs) + [[InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")]]
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
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    margin_val = (10000 if state["trade_mode"] == "MOCK" else (real or 10000)) * (state["margin"] / 100)
    # Confidence green squares
    conf = p["confidence"]
    greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
    # Get real-time price (from result or fresh ticker)
    cur_price = p.get('current_price', 0)
    if not cur_price:
        try:
            symbol_clean = p['symbol'].replace('/', '')
            cur_price, _ = get_binance_ticker(symbol_clean)
        except: pass
    text = (f"📊 {p['symbol']} {p['direction']} {state['trade_mode']}\n\n"
            f"Balance: {bal}\n"
            f"Change: {p['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
            f"Reasons: {' | '.join(p['reasons'])}\n"
            f"Leverage: {state['leverage']}x  |  Margin: {state['margin']}%  (${margin_val:,.0f})\n"
            f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {p.get('rrr', 2.0):.1f}\n"
            f"Confidence: {conf}% {greens} 🦞")
    kb = []
    # Only show EXECUTE if pair is valid on exchange (admins bypass)
    user_id = update.effective_user.id
    if is_pair_valid_for_user(p['symbol'], user_id):
        kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
    # Add SET ALERT button with current price
    try:
        symbol_clean = p['symbol'].replace('/', '')
        cur_price, _ = get_binance_ticker(symbol_clean)
        if cur_price and cur_price > 0:
            kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {p['symbol']} {cur_price:.2f}")])
    except Exception as e:
        logger.debug(f"Alert price fetch failed: {e}")
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
        
        # Store in user_state
        user_state.setdefault(chat_id, {"selected_pairs": []})
        user_state[chat_id]['selected_pairs'] = [result]
        
        # Determine back target from context
        back_target = user_state[chat_id].get('pair_detail_back', 'manual_mode')
        
        # Render detail
        state = get_state(chat_id)
        real, mock = get_balance()
        bal = format_balance(real, mock, state.get("trade_mode", "MOCK"))
        margin_val = (10000 if state["trade_mode"] == "MOCK" else (real or 10000)) * (state["margin"] / 100)
        conf = result['confidence']
        greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
        cur_price = result.get('current_price', 0)
        if not cur_price:
            try:
                symbol_clean = result['symbol'].replace('/', '')
                cur_price, _ = get_binance_ticker(symbol_clean)
            except: pass
        text = (f"📊 {result['symbol']} {result['direction']} {state['trade_mode']}\n\n"
                f"Balance: {bal}\n"
                f"Change: {result['change']:+.2f}%"
                + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "")
                + "\n"
                f"Reasons: {' | '.join(result['reasons'])}\n"
                f"Leverage: {state['leverage']}x  |  Margin: {state['margin']}%  (${margin_val:,.0f})\n"
                f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {result.get('rrr', 2.0):.1f}\n"
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
    pairs = get_bingx_hot_pairs(limit=6)
    kb = []
    for i in range(0, len(pairs), 2):
        row = []
        for p in pairs[i:i+2]:
            row.append(InlineKeyboardButton(p, callback_data=f"select_{p}"))
        kb.append(row)
    kb.append([InlineKeyboardButton("➕ ADD PAIR", callback_data="add_pair_menu")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")])
    await q.edit_message_text("👷 **MANUAL MODE**\n\nSelect pair to trade:", reply_markup=InlineKeyboardMarkup(kb))

async def add_pair_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    # Set back-context for pair detail
    user_state.setdefault(chat_id, {})
    user_state[chat_id]['pair_detail_back'] = 'add_pair_menu'
    top = get_bingx_hot_pairs(limit=10)
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
    await q.edit_message_text("⌨️ **ENTER CUSTOM PAIR**\n\nType ticker (e.g., BTC/USDT) in chat.\nI'll verify on BingX.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="add_pair_menu")]]))
    user_state[q.message.chat_id]["awaiting_pair_input"] = True

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

    # Handle BingX URL paste (with or without http prefix)
    text_lower = text.lower()
    if "bingx.com" in text_lower:
        print(f"[DEBUG] BingX URL detected: {text[:80]}")
        logger.info(f"BingX URL detected: {text[:80]}")
        pair = extract_pair_from_bingx_url(text)
        print(f"[DEBUG] Extracted pair: {pair}")
        logger.info(f"Extracted pair: {pair}")
        if pair:
            # Validate pair exists on BingX (admins bypass)
            user_id = update.effective_user.id
            if not is_pair_valid_for_user(pair, user_id):
                await update.message.reply_text(
                    f"❌ **Pair not available**\n\n{pair} is not listed on BingX (validation failed).\n\nTry a different pair like BTC/USDT, ETH/USDT, SOL/USDT.",
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
                user_state[chat_id]['selected_pairs'] = [result]
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
            margin_val = (10000 if state.get("trade_mode", "MOCK") == "MOCK" else (real or 10000)) * (state.get("margin", 1) / 100)
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
            text_msg = (f"📊 {result['symbol']} {result['direction']} {state.get('trade_mode','MOCK')}\n\n"
                        f"Balance: {bal}\n"
                        f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
                        f"Reasons: {' | '.join(result['reasons'])}\n"
                        f"Leverage: {state.get('leverage',50)}x  |  Margin: {state.get('margin',1)}%  (${margin_val:,.0f})\n"
                        f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {result.get('rrr',2.0):.1f}\n"
                        f"Confidence: {conf}% {greens} 🦞")
            kb = [[InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")]]
            # Add SET ALERT button with current price
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
            await update.message.reply_text(text_msg, reply_markup=InlineKeyboardMarkup(kb))
            return
        else:
            await update.message.reply_text("❌ Could not extract pair from URL.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
            return

    # Binance futures URL handling
    if "binance.com" in text_lower and "/futures/" in text_lower:
        pair = extract_pair_from_binance_url(text)
        if pair:
            # Validate pair exists on BingX (admins bypass)
            user_id = update.effective_user.id
            if not is_pair_valid_for_user(pair, user_id):
                await update.message.reply_text(
                    f"❌ **Pair not available**\n\n{pair} is not listed on BingX (validation failed).\n\nTry a different pair like BTC/USDT, ETH/USDT, SOL/USDT.",
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
                user_state[chat_id]['selected_pairs'] = [result]
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
            margin_val = (10000 if state.get("trade_mode", "MOCK") == "MOCK" else (real or 10000)) * (state.get("margin", 1) / 100)
            conf = result["confidence"]
            greens = "🟩" * ((conf - 80) // 10 + 1) if conf >= 80 else "🟨"
            symbol_clean = result['symbol'].replace('/', '')
            cur_price = result.get('current_price', 0)
            try:
                ticker_price, _ = get_binance_ticker(symbol_clean)
                if ticker_price and ticker_price > 0:
                    cur_price = ticker_price
            except: pass
            text_msg = (f"📊 {result['symbol']} {result['direction']} {state.get('trade_mode','MOCK')}\n\n"
                        f"Balance: {bal}\n"
                        f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
                        f"Reasons: {' | '.join(result['reasons'])}\n"
                        f"Leverage: {state.get('leverage',50)}x  |  Margin: {state.get('margin',1)}%  (${margin_val:,.0f})\n"
                        f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {result.get('rrr',2.0):.1f}\n"
                        f"Confidence: {conf}% {greens} 🦞")
            kb = [[InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")]]
            if cur_price and cur_price > 0:
                kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
            await update.message.reply_text(text_msg, reply_markup=InlineKeyboardMarkup(kb))
            return

    if state.get("awaiting_pair_input"):
        if "/" not in text:
            await update.message.reply_text("❌ Format: BASE/QUOTE (e.g., BTC/USDT)", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
            return
        if validate_pair_on_bingx(text):
            user_state[chat_id]["selected_pair"] = {"symbol": text, "direction": "LONG"}
            state["awaiting_pair_input"] = False
            await update.message.reply_text(f"✅ Pair {text} added!\n\nUse /start to continue.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 MAIN", callback_data="main")]]))
        else:
            await update.message.reply_text("❌ Pair not on BingX. Try again.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))

def validate_pair_on_bingx(pair):
    symbol = pair.replace("/", "").upper()
    data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": symbol})
    return data is not None and "data" in data

def extract_pair_from_bingx_url(url):
    """Extract pair from BingX perpetual URL.
    Example: https://bingx.com/en/perpetual/GENIUS-USDT -> GENIUS/USDT
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
                return pair
        # Fallback: last path segment
        if path_parts:
            pair_raw = path_parts[-1]
            pair = pair_raw.replace('-', '/').upper()
            if '/' in pair:
                return pair
    except Exception as e:
        logger.debug(f"URL parse error: {e}")
    return None

def extract_pair_from_binance_url(url):
    """Extract pair from Binance futures URL.
    Example: https://www.binance.com/en/futures/GENIUSUSDT -> GENIUS/USDT
    """
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        # Check if it's a binance.com futures URL
        if 'binance.com' not in parsed.netloc.lower():
            return None
        path_parts = parsed.path.strip('/').split('/')
        # Look for 'futures' segment and take next, or take last segment
        for i, part in enumerate(path_parts):
            if part.lower() == 'futures' and i + 1 < len(path_parts):
                symbol = path_parts[i + 1].upper()
                # Binance USDT-margined futures symbols end with USDT (e.g., BTCUSDT)
                if symbol.endswith('USDT'):
                    base = symbol[:-4]
                    return f"{base}/USDT"
        # Fallback: last path segment
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
    trades = api_get("/api/v1/trades?status=open")
    if not trades or not trades.get("trades"):
        await q.edit_message_text("📊 **No open positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    
    # Build 2x3 grid for first 6 pairs
    buttons = []
    trade_list = trades["trades"]
    visible_trades = trade_list[:6]
    extra_trades = trade_list[6:]
    
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
    
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    await q.edit_message_text("📊 **Open Positions**\n\nSelect one:", reply_markup=InlineKeyboardMarkup(buttons))

async def refresh_positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Refresh the positions list (called from Refresh button)."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer("🔄 Refreshing...")
    trades = api_get("/api/v1/trades?status=open")
    if not trades or not trades.get("trades"):
        await q.edit_message_text("📊 **No open positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    buttons = []
    for t in trades["trades"]:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} - {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("🔄 Refresh", callback_data="refresh_positions")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    await q.edit_message_text("📊 **Open Positions**\n\nSelect one:", reply_markup=InlineKeyboardMarkup(buttons))

async def other_positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show additional positions beyond the first 6 (overflow list)."""
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trades = api_get("/api/v1/trades?status=open")
    if not trades or not trades.get("trades"):
        await q.edit_message_text("📊 **No open positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    
    # Get trades from index 6 onward
    extra_trades = trades["trades"][6:]
    if not extra_trades:
        await q.edit_message_text("📊 **No other positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    buttons = []
    for t in extra_trades:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK TO LIST", callback_data="positions")])
    await q.edit_message_text(f"📋 **Other Positions** ({len(extra_trades)} more)", reply_markup=InlineKeyboardMarkup(buttons))

async def pos_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not await enforce_access(update, ctx, allow_whitelisted=True, require_channel=True):
        return
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    t = api_get(f"/api/v1/trades?trade_id={trade_id}")
    if not t or not t.get("trades"):
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    t = t["trades"][0]
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
    t = api_get(f"/api/v1/trades?trade_id={trade_id}")
    if not t or not t.get("trades"):
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    t = t["trades"][0]
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
            f"❌ **Pair not available**\n\n{p['symbol']} is not listed on BingX (validation failed).\n\nSelect a valid pair and try again.",
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
    payload = {
        "pair": p["symbol"],
        "leverage": state["leverage"],
        "margin": state["margin"],
        "direction": p["direction"],
        "dry_run": state["trade_mode"] == "MOCK"
    }
    logger.info(f"Executing trade: {payload}")
    success, error_msg = api_post("/api/v1/forcebuy", payload)
    if success:
        msg = "✅ **Trade executed!**"
        if state["trade_mode"] == "MOCK":
            msg += "\n\n_MOCK mode - no real funds used_"
        msg += "\n\nCheck POSITIONS for status."
    else:
        msg = "❌ **Execution failed**\n\n"
        if error_msg:
            msg += f"**Error:** `{error_msg}`\n\n"
        msg += "Possible reasons:\n• Freqtrade API error\n• Invalid pair/params\n• Exchange down"
        logger.error(f"Trade execution failed for {p['symbol']}: {error_msg}")
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))

# ── Scan Command ──
async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /scan command: run AI scan asynchronously and send results."""
    if not await enforce_access(update, context, allow_whitelisted=True, require_channel=True):
        return
    chat_id = update.effective_chat.id
    # Acknowledge immediately
    status_msg = await update.message.reply_text(
        "🔍 **Scanning market...**\n\nFetching BingX hot pairs, analyzing 5M charts, order book, sentiment...",
        parse_mode="Markdown"
    )

    async def do_scan():
        try:
            # Start facts cycling task
            facts_task = asyncio.create_task(cycle_facts_on_message(status_msg, "🔍 **Scanning market..."))

            # Run blocking scan in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            setups = await loop.run_in_executor(None, ai_scan_pairs)

            # Cancel facts task
            facts_task.cancel()
            try:
                await facts_task
            except:
                pass

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

    async def do_refresh():
        try:
            # Start facts cycling task
            facts_task = asyncio.create_task(cycle_facts_on_message(query.message, "🔄 **Refreshing scan..."))

            # Run blocking scan in executor
            loop = asyncio.get_event_loop()
            setups = await loop.run_in_executor(None, ai_scan_pairs)

            # Cancel facts task
            facts_task.cancel()
            try:
                await facts_task
            except:
                pass

            user_state[chat_id]["selected_pairs"] = setups
            try:
                await query.message.delete()
            except: pass
            await send_scan_message(chat_id, setups, context)
        except Exception as e:
            logger.error(f"Refresh scan error: {e}", exc_info=True)
            try:
                await query.edit_message_text(
                    f"❌ **Scan failed**: {str(e)[:100]}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 RETRY", callback_data="/scan")],
                        [InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")]
                    ])
                )
            except: pass
    asyncio.create_task(do_refresh())

async def send_scan_message(chat_id, setups, context):
    """Format and send scan results with a refresh button."""
    text = "✅ **Scan Complete - Top 4 Pairs:**\n\nSelect a pair to view details & execute:\n\n"
    for i, p in enumerate(setups, 1):
        price_str = ""
        if p.get('current_price'):
            price_str = f" @ ${p['current_price']:,.2f}"
        text += f"{i}. {p['symbol']} {p['direction']} - {p['change']:+.2f}%{price_str} | Conf: {p['confidence']}%\n"
    kb = grid_2x2(setups)
    kb.append([InlineKeyboardButton("🔄 Refresh Scan", callback_data="/scan")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")])
    await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

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
    user_state[chat_id]["selected_pairs"] = [result]

    # Build detail view (same as pair_detail_cb)
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    margin_val = (10000 if state["trade_mode"] == "MOCK" else (real or 10000)) * (state["margin"] / 100)
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
    text = (f"📊 {result['symbol']} {result['direction']} {state['trade_mode']}\n\n"
            f"Balance: {bal}\n"
            f"Change: {result['change']:+.2f}%" + (f"  |  Current: ${cur_price:,.2f}" if cur_price else "") + "\n"
            f"Reasons: {' | '.join(result['reasons'])}\n"
            f"Leverage: {state['leverage']}x  |  Margin: {state['margin']}%  (${margin_val:,.0f})\n"
            f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {result.get('rrr',2.0):.1f}\n"
            f"Confidence: {conf}% {greens} 🦞")
    kb = []
    # Only show EXECUTE if pair is valid on exchange (admins bypass)
    user_id = q.from_user.id
    if is_pair_valid_for_user(result['symbol'], user_id):
        kb.append([InlineKeyboardButton("🚀 EXECUTE", callback_data="execute")])
    # Add SET ALERT button with current price
    if cur_price and cur_price > 0:
        kb.append([InlineKeyboardButton("🔔 SET ALERT", callback_data=f"/alert {result['symbol']} {cur_price:.2f}")])
    kb.append([InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")])
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ── Error handler ──
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    error = ctx.error
    # Ignore benign Telegram errors
    if isinstance(error, error.BadRequest) and "Message is not modified" in str(error):
        return
    logger.error(f"Exception: {error}", exc_info=error)

async def set_commands(app: Application) -> None:
    """Set restricted bot commands — only expose our custom trading commands."""
    await app.bot.set_my_commands([
        BotCommand("start", "Show main menu"),
        BotCommand("cmd", "Show command center"),
        BotCommand("scan", "AI scan of hot pairs"),
    ])

# ── Build & Run ──
def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return
    test = api_get("/api/v1/ping")
    if not test:
        logger.error("Cannot connect to Freqtrade API")
        return
    logger.info("Connected to Freqtrade API")
    app = Application.builder().token(TOKEN).post_init(set_commands).build()
    app.add_handler(CommandHandler(["start", "cmd"], start))
    app.add_handler(CommandHandler("scan", scan_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    # Callbacks
    app.add_handler(CallbackQueryHandler(main_cb, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(toggle_mode_cb, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(show_balance_cb, pattern="^show_balance$"))
    app.add_handler(CallbackQueryHandler(show_stats_cb, pattern="^show_stats$"))
    app.add_handler(CallbackQueryHandler(show_gains_cb, pattern="^show_gains$"))
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
    app.add_handler(CallbackQueryHandler(positions_cb, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(pos_detail_cb, pattern="^pos_"))
    app.add_handler(CallbackQueryHandler(refresh_positions_cb, pattern="^refresh_positions$"))
    app.add_handler(CallbackQueryHandler(other_positions_cb, pattern="^other_positions$"))
    app.add_handler(CallbackQueryHandler(close_position_cb, pattern="^close_"))
    app.add_handler(CallbackQueryHandler(share_pnl_cb, pattern="^share_"))
    app.add_handler(CallbackQueryHandler(execute_cb, pattern="^execute$"))
    app.add_handler(CallbackQueryHandler(market_now_cb, pattern="^market_now$"))
    app.add_handler(CallbackQueryHandler(confirm_exec_cb, pattern="^confirm_"))
    app.add_handler(CallbackQueryHandler(alert_set_callback, pattern=r'^/alert '))
    app.add_handler(CallbackQueryHandler(refresh_scan_callback, pattern=r'^/scan$'))
    app.add_error_handler(error_handler)
    logger.info("Starting Clawmimoto Telegram UI...")
    # Start background snapshot thread (every 4 hours)
    def _snapshot_thread():
        """Runs in separate thread; uses synchronous requests to Telegram API."""
        import time
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
                    logger.info(f"✅ Market snapshot sent to {chat_id}")
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
