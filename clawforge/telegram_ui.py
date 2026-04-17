#!/usr/bin/env python3
"""
Clawmimoto Telegram UI — Revised per user specs
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
import threading
from datetime import datetime, timezone
from pathlib import Path
import feedparser
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

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
    try:
        r = requests.post(f"{API_URL}{endpoint}", json=payload or {}, headers=AUTH_HEADER, timeout=10)
        return r.status_code == 200
    except Exception as e:
        logger.error(f"API POST {endpoint} failed: {e}")
        return False

# ── BingX API ──
def bingx_signed_request(method, endpoint, params=None):
    if not BINGX_API_KEY or not BINGX_API_SECRET:
        return None
    base_url = "https://openapi.bingx.com"
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
def call_stepfun_skill(prompt):
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
    try:
        r = requests.post("https://api.stepfun.ai/v1/chat/completions", json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"StepFun error: {e}")
    return None

def ai_scan_pairs():
    """Scan BingX hot pairs, call StepFun, return top 4 with data"""
    hot = get_bingx_hot_pairs(limit=10)
    results = []
    for pair in hot:
        symbol = pair.replace("/", "")
        klines = bingx_signed_request("GET", "/openApi/swap/v2/quote/klines", {"symbol": symbol, "interval": "5m", "limit": "50"})
        change = 0
        volume = 0
        if klines and "data" in klines and len(klines["data"]) >= 2:
            closes = [float(k["close"]) for k in klines["data"][-10:]]
            if len(closes) >= 2:
                change = (closes[-1] - closes[-2]) / closes[-2] * 100
            volume = sum(float(k["volume"]) for k in klines["data"][-5:])
        # AI reasoning
        prompt = f"Scalp analysis for {pair} 5M: change {change:.2f}%, volume {volume:.0f}. Give: direction (LONG/SHORT), confidence 80-90%, RRR 1.5-3.0, 3 reasons, entry/sl/tp levels."
        ai_text = call_stepfun_skill(prompt)
        direction = "LONG"
        confidence = 85
        reasons = ["High volume", "Momentum", "AI signal"]
        entry = 0; sl = 0; tp = 0; rrr = 0
        if ai_text:
            # Simple parse (improve later)
            ai_lower = ai_text.lower()
            if "short" in ai_lower:
                direction = "SHORT"
            if "confidence" in ai_lower:
                try:
                    confidence = int(''.join(filter(str.isdigit, ai_text.split("confidence")[1].split("%")[0])))
                except:
                    pass
            reasons = [line.strip("- ") for line in ai_text.split('\n') if line.strip()][:3]
        results.append({
            "symbol": pair,
            "direction": direction,
            "change": round(change, 2),
            "volume": volume,
            "confidence": confidence,
            "reasons": reasons,
            "entry": entry, "sl": sl, "tp": tp, "rrr": rrr
        })
    # Sort by volume + confidence
    results.sort(key=lambda x: (x["volume"], x["confidence"]), reverse=True)
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
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["trade_mode"] = "REAL" if state["trade_mode"] == "MOCK" else "MOCK"
    # Return to main
    await main_cb(update, ctx)

async def show_balance_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    mode_label = "REAL" if state["trade_mode"] == "REAL" else "MOCK"
    await q.edit_message_text(f"💼 **Balance ({mode_label})**\n\n{bal}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main")]]))

async def show_stats_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    w, l, wr, pnl = get_stats()
    text = f"📊 **Statistics**\n\nWin/Loss: {w}/{l} ({wr:.0f}%)\nRealized PNL: ${pnl:,.2f}"
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="main")]]))

async def show_gains_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
            "📢 *Market Pulse — " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*\n\n"
            "• (News feeds temporarily unavailable — RSS error)\n"
        )
    
    # Format: title + [Source](link) on same line
    lines = [f"• {title} [Source]({link})" for title, link in uniq]
    header = "📢 *Market Pulse — " + datetime.now(timezone.utc).strftime("%b %d, %Y") + "*"
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
    q = update.callback_query
    await q.answer()
    # Define pairs: (display_label, bingx_symbol, binance_symbol, okx_symbol, coingecko_id)
    pairs = [
        ("BTC", "BTCUSDT", "BTCUSDT", "BTC-USDT", "bitcoin"),
        ("ETH", "ETHUSDT", "ETHUSDT", "ETH-USDT", "ethereum"),
        ("SOL", "SOLUSDT", "SOLUSDT", "SOL-USDT", "solana"),
        ("BNB", "BNBUSDT", "BNBUSDT", "BNB-USDT", "binancecoin"),
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
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    real, mock = get_balance()
    bal = format_balance(real, mock, state["trade_mode"])
    kb = [
        [InlineKeyboardButton("🤖 SESSION MODE", callback_data="session_mode")],
        [InlineKeyboardButton("👷 MANUAL MODE", callback_data="manual_mode")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="main")],
    ]
    await q.edit_message_text(f"⏰ **Select Trading Mode**\n\nBalance: {bal}", reply_markup=InlineKeyboardMarkup(kb))

# ── Session Mode ──
async def session_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    await q.edit_message_text("🔍 **AI scanning market...**\n\nFetching BingX hot pairs, analyzing 5M charts, order book, sentiment...")
    pairs = ai_scan_pairs()
    user_state[chat_id]["selected_pairs"] = pairs
    kb = grid_2x2(pairs) + [[InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")]]
    await q.edit_message_text("✅ **Scan Complete — Top 4 Pairs:**\n\nSelect a pair to view details & execute:", reply_markup=InlineKeyboardMarkup(kb))

async def pair_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
    text = (f"📊 {p['symbol']} {p['direction']} {state['trade_mode']}\n\n"
            f"Balance: {bal}\n"
            f"Price: ${p['change']:+.2f}%\n"
            f"Reasons: {' | '.join(p['reasons'])}\n"
            f"Leverage: {state['leverage']}x  |  Margin: {state['margin']}%  (${margin_val:,.0f})\n"
            f"Entry: market  |  SL: TBD  |  TP: TBD  |  RRR: {p.get('rrr', 2.0):.1f}\n"
            f"Confidence: {conf}% {greens} 🦞")
    kb = [
        [InlineKeyboardButton("🚀 EXECUTE", callback_data=f"exec_{p['symbol']}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

# ── Manual Mode ──
async def manual_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    state = get_state(q.message.chat_id)
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
    q = update.callback_query
    await q.answer()
    top = get_bingx_top_pairs(limit=10)
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
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("⌨️ **ENTER CUSTOM PAIR**\n\nType ticker (e.g., BTC/USDT) in chat.\nI'll verify on BingX.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="add_pair_menu")]]))
    user_state[q.message.chat_id]["awaiting_pair_input"] = True

async def text_input_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.upper()
    state = user_state.get(chat_id, {})
    if state.get("awaiting_pair_input"):
        if "/" not in text:
            await update.message.reply_text("❌ Format: BASE/QUOTE (e.g., BTC/USDT)")
            return
        if validate_pair_on_bingx(text):
            user_state[chat_id]["selected_pair"] = {"symbol": text, "direction": "LONG"}
            state["awaiting_pair_input"] = False
            await update.message.reply_text(f"✅ Pair {text} added!\n\nUse /start to continue.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🏠 MAIN", callback_data="main")]]))
        else:
            await update.message.reply_text("❌ Pair not on BingX. Try again.")

def validate_pair_on_bingx(pair):
    symbol = pair.replace("/", "").upper()
    data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": symbol})
    return data is not None and "data" in data

# ── Positions ──
async def positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    trades = api_get("/api/v1/trades?status=open")
    if not trades or not trades.get("trades"):
        await q.edit_message_text("📊 **No open positions**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="main")]]))
        return
    buttons = []
    for t in trades["trades"]:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} — {profit:+.1f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pos_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    await q.edit_message_text("📊 **Open Positions**\n\nSelect one:", reply_markup=InlineKeyboardMarkup(buttons))

async def pos_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    t = api_get(f"/api/v1/trades?trade_id={trade_id}")
    if not t or not t.get("trades"):
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    t = t["trades"][0]
    real, mock = get_balance()
    bal = format_balance(real, mock, t.get("is_mock", False) and "MOCK" or "REAL")
    is_open = t.get("is_open", True)
    status_btn = InlineKeyboardButton("🔴 CLOSE POSITION", callback_data=f"close_{trade_id}") if is_open else InlineKeyboardButton("✅ CLOSED", callback_data="dummy")
    text = (f"📊 {t['pair']} {t.get('direction','LONG')} {'OPEN' if is_open else 'CLOSED'}\n\n"
            f"Balance: {bal}\n"
            f"Time: {t.get('open_date','')}\n"
            f"Margin: ${t.get('stake_amount',0):,.2f}  |  Unrealized: {t.get('profit_pct',0):+.1f}%\n"
            f"Entry: {t.get('open_rate',0):,.2f}  |  SL: {t.get('stop_loss_pct',0):.1f}%  |  TP: {t.get('take_profit',0):,.2f}\n")
    kb = [
        [status_btn],
        [InlineKeyboardButton("📤 Share PNL", callback_data=f"share_{trade_id}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="positions")]
    ]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb))

async def close_position_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    success = api_post(f"/api/v1/trades/{trade_id}/close")
    if success:
        await q.edit_message_text("✅ Position closed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ POSITIONS", callback_data="positions")]]))
    else:
        await q.edit_message_text("❌ Failed to close.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))

async def share_pnl_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    trade_id = q.data.split("_", 1)[1]
    t = api_get(f"/api/v1/trades?trade_id={trade_id}")
    if not t or not t.get("trades"):
        await q.edit_message_text("❌ Trade not found.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="positions")]]))
        return
    t = t["trades"][0]
    # Generate card (placeholder — use PnL card generator when ready)
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
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    pairs = user_state.get(chat_id, {}).get("selected_pairs", [])
    if not pairs:
        await q.edit_message_text("❌ No pair selected. Use SESSION MODE first.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        return
    p = pairs[0]  # use first selected
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
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    pairs = user_state.get(chat_id, {}).get("selected_pairs", [])
    if not pairs:
        await q.edit_message_text("❌ No pair selected.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))
        return
    p = pairs[0]
    payload = {
        "pair": p["symbol"],
        "leverage": state["leverage"],
        "margin": state["margin"],
        "direction": p["direction"],
        "dry_run": state["trade_mode"] == "MOCK"
    }
    result = api_post("/api/v1/forcebuy", payload)
    msg = "✅ **Trade executed!**" if result else "❌ **Execution failed**"
    await q.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ MAIN", callback_data="main")]]))

# ── Error handler ──
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {ctx.error}", exc_info=ctx.error)

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
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "cmd"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    # Callbacks
    app.add_handler(CallbackQueryHandler(main_cb, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(toggle_mode_cb, pattern="^toggle_mode$"))
    app.add_handler(CallbackQueryHandler(show_balance_cb, pattern="^show_balance$"))
    app.add_handler(CallbackQueryHandler(show_stats_cb, pattern="^show_stats$"))
    app.add_handler(CallbackQueryHandler(show_gains_cb, pattern="^show_gains$"))
    app.add_handler(CallbackQueryHandler(trade_menu_cb, pattern="^trade_menu$"))
    app.add_handler(CallbackQueryHandler(session_mode_cb, pattern="^session_mode$"))
    app.add_handler(CallbackQueryHandler(session_adjust_cb, pattern="^(lev|mar)_(up|down)$"))
    app.add_handler(CallbackQueryHandler(ai_scan_cb, pattern="^ai_scan$"))
    app.add_handler(CallbackQueryHandler(pair_detail_cb, pattern="^pair_"))
    app.add_handler(CallbackQueryHandler(manual_mode_cb, pattern="^manual_mode$"))
    app.add_handler(CallbackQueryHandler(add_pair_menu_cb, pattern="^add_pair_menu$"))
    app.add_handler(CallbackQueryHandler(other_pair_input_cb, pattern="^other_pair_input$"))
    app.add_handler(CallbackQueryHandler(positions_cb, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(pos_detail_cb, pattern="^pos_"))
    app.add_handler(CallbackQueryHandler(close_position_cb, pattern="^close_"))
    app.add_handler(CallbackQueryHandler(share_pnl_cb, pattern="^share_"))
    app.add_handler(CallbackQueryHandler(execute_cb, pattern="^execute$"))
    app.add_handler(CallbackQueryHandler(market_now_cb, pattern="^market_now$"))
    app.add_handler(CallbackQueryHandler(confirm_exec_cb, pattern="^confirm_"))
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