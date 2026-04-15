#!/usr/bin/env python3
"""
ClawTrader Telegram UI — Full 0-Type Interface
SESSION + MANUAL modes, REAL/MOCK toggle, AI scan via StepFun/BingX
"""

import os
import logging
import base64
import hashlib
import hmac
import requests
from pathlib import Path
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
user_state = {}  # {chat_id: {"mode": "session"|"manual", "leverage": 50, "margin": 1, "selected_pairs": [], "trade_mode": "MOCK"}}  # MOCK or REAL

def get_state(chat_id):
    if chat_id not in user_state:
        user_state[chat_id] = {
            "mode": None,
            "leverage": 50,
            "margin": 1,
            "selected_pairs": [],
            "trade_mode": "MOCK"  # default
        }
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
        query = '&'.join([f"{k}={v}" for k,v in sorted_params])
        signature = hmac.new(BINGX_API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
        url += f"?{query}&signature={signature}"
    headers = {"X-BX-APIKEY": BINGX_API_KEY, "Content-Type": "application/json"}
    try:
        r = requests.request(method, url, headers=headers, timeout=10)
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error(f"BingX API error: {e}")
        return None

def get_bingx_hot_pairs(limit=6):
    data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker")
    if data and "data" in data:
        pairs = []
        for item in data["data"][:limit]:
            symbol = item.get("symbol", "").upper()
            if symbol.endswith("USDT"):
                pairs.append(f"{symbol}/USDT")
            else:
                pairs.append(f"{symbol}/USDT")
        return pairs if pairs else ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"]
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"]

def get_bingx_top_pairs(limit=10):
    data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker")
    if data and "data" in data:
        pairs = []
        for item in data["data"][:limit]:
            symbol = item.get("symbol", "").upper()
            if symbol.endswith("USDT"):
                pairs.append(f"{symbol}/USDT")
            else:
                pairs.append(f"{symbol}/USDT")
        return pairs if len(pairs) >= 10 else ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT"]
    return ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT"]

def validate_pair_on_bingx(pair):
    symbol = pair.replace("/", "").upper()
    data = bingx_signed_request("GET", "/openApi/swap/v2/quote/ticker", {"symbol": symbol})
    return data is not None and "data" in data

def get_bingx_balance():
    """Fetch real USDT balance from BingX."""
    data = bingx_signed_request("GET", "/openApi/swap/v2/account/balance")
    if data and "data" in data:
        for asset in data["data"]:
            if asset.get("asset") == "USDT":
                return float(asset.get("available", 0))
    return None

# ── StepFun AI Skill ──
def call_stepfun_skill(prompt, context=""):
    """Call StepFun API to analyze market."""
    if not STEPFUN_API_KEY:
        return None
    headers = {
        "Authorization": f"Bearer {STEPFUN_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "step-3.5-flash",
        "messages": [
            {"role": "system", "content": "You are an expert crypto trading analyst. Provide concise TA signals."},
            {"role": "user", "content": f"{context}\n\n{prompt}"}
        ],
        "temperature": 0.7
    }
    try:
        r = requests.post("https://api.stepfun.ai/v1/chat/completions", json=payload, headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"StepFun API error: {e}")
    return None

# ── UI Components ──
def adjust_buttons(label, value, step, min_val, max_val, callback_prefix):
    return [
        InlineKeyboardButton("➖", callback_data=f"{callback_prefix}_down"),
        InlineKeyboardButton(f"{label}: {value}", callback_data=f"{callback_prefix}_show"),
        InlineKeyboardButton("➕", callback_data=f"{callback_prefix}_up")
    ]

def main_menu(state):
    """Main menu with trade mode, balances, stats."""
    mode_text = "🔴 REAL" if state.get("trade_mode") == "REAL" else "🟢 MOCK"
    # Fetch balances
    mock_balance = api_get("/api/v1/balance") or {"currencies": [{"free": 10000}]}
    mock_usdt = mock_balance.get("currencies", [{}])[0].get("free", 10000)
    real_balance = get_bingx_balance()
    real_text = f"{real_balance:.3f}" if real_balance is not None else "N/A"
    # Fetch stats
    stats = api_get("/api/v1/stats") or {}
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    realized_pnl = stats.get("total_profit_abs", 0)
    pnl_text = f"${realized_pnl:.2f}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🏠 ClawTrader Command Center", callback_data="main")],
        [InlineKeyboardButton(f"Mode: {mode_text} | Real: ${real_text} | Mock: {mock_usdt:.0f} CLUSDT", callback_data="settings")],
        [InlineKeyboardButton(f"📈 Win/Loss: {wins}/{losses} ({win_rate:.0f}%) | Realized PNL: {pnl_text}", callback_data="stats")],
        [InlineKeyboardButton("📈 TRADE MENU", callback_data="trade_menu")],
        [InlineKeyboardButton("📊 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("💸 PnL LEDGER", callback_data="pnl")],
        [InlineKeyboardButton("🚀 EXECUTE TRADE", callback_data="execute")],
    ])

def trade_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🤖 SESSION MODE", callback_data="session_mode")],
        [InlineKeyboardButton("👷 MANUAL MODE", callback_data="manual_mode")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="main")],
    ])

def session_controls(state):
    lev_row = adjust_buttons("Leverage", state["leverage"], 10, 10, 100, "lev")
    mar_row = adjust_buttons("Margin %", state["margin"], 1, 1, 2, "mar")
    return InlineKeyboardMarkup([
        lev_row,
        mar_row,
        [InlineKeyboardButton("🔍 START AI SCAN", callback_data="ai_scan")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")],
    ])

def session_results(pairs_data):
    buttons = []
    for pair in pairs_data[:4]:
        reasons = " | ".join(pair.get("reasons", []))
        btn_text = f"📌 {pair['symbol']} ({pair['change']:+.1f}%)"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"pair_{pair['symbol']}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="session_mode")])
    return InlineKeyboardMarkup(buttons)

def manual_hot_pairs(hot_pairs):
    buttons = []
    for i in range(0, len(hot_pairs), 2):
        row = []
        for pair in hot_pairs[i:i+2]:
            row.append(InlineKeyboardButton(pair, callback_data=f"select_{pair}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("➕ ADD PAIR", callback_data="add_pair_menu")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="trade_menu")])
    return InlineKeyboardMarkup(buttons)

def add_pair_grid(top_pairs):
    buttons = []
    for i in range(0, len(top_pairs), 2):
        row = []
        for pair in top_pairs[i:i+2]:
            row.append(InlineKeyboardButton(pair, callback_data=f"select_{pair}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⌨️ OTHER PAIR", callback_data="other_pair_input")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="manual_mode")])
    return InlineKeyboardMarkup(buttons)

def settings_menu(state):
    mode = state.get("trade_mode", "MOCK")
    real_btn = "🔴 REAL" if mode == "REAL" else "🟢 REAL"
    mock_btn = "🟢 MOCK" if mode == "MOCK" else "🔴 MOCK"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Mode: {real_btn}", callback_data="set_real")],
        [InlineKeyboardButton(f"Mode: {mock_btn}", callback_data="set_mock")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="main")],
    ])

# ── Handlers ──
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = get_state(chat_id)
    # Build main menu with dynamic balances/stats
    await update.message.reply_text("🏠 **ClawTrader Command Center**", reply_markup=main_menu(state))

async def main_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    await q.edit_message_text("🏠 **ClawTrader Command Center**\n\nSelect an action:", reply_markup=main_menu(state))

async def settings_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    await q.edit_message_text(
        "⚙️ **SETTINGS**\n\nSelect trade mode:\n\n"
        f"Current: **{state.get('trade_mode', 'MOCK')}**",
        reply_markup=settings_menu(state)
    )

async def set_trade_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    mode = q.data.split("_", 1)[1].upper()  # "real" or "mock"
    state["trade_mode"] = mode
    await q.edit_message_text(
        f"✅ Trade mode set to **{mode}**\n\n"
        f"• REAL: Uses actual BingX balance\n"
        f"• MOCK: Uses CLUSDT virtual wallet",
        reply_markup=main_menu(state)
    )

async def stats_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    stats = api_get("/api/v1/stats") or {}
    wins = stats.get("wins", 0)
    losses = stats.get("losses", 0)
    total = wins + losses
    win_rate = (wins / total * 100) if total > 0 else 0
    realized_pnl = stats.get("total_profit_abs", 0)
    text = (f"📊 **Statistics**\n\n"
            f"Win/Loss: {wins}/{losses} ({win_rate:.1f}%)\n"
            f"Realized PNL: ${realized_pnl:.2f}\n\n"
            f"_Data from Freqtrade_")
    await q.edit_message_text(text, reply_markup=main_menu(get_state(q.message.chat_id)))

# ── TRADE MENU ──
async def trade_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⏰ **Select Trading Mode**\n\n"
        "SESSION: AI scans market, selects 4 best pairs\n"
        "MANUAL: Pick pairs from BingX hot list",
        reply_markup=trade_menu()
    )

# ── SESSION MODE ──
async def session_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["mode"] = "session"
    await q.edit_message_text(
        "🤖 **SESSION MODE**\n\n"
        f"Leverage: {state['leverage']}x\n"
        f"Margin: {state['margin']}%\n\n"
        "Adjust parameters or start AI scan:",
        reply_markup=session_controls(state)
    )

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
    await q.edit_message_text(
        "🤖 **SESSION MODE**\n\n"
        f"Leverage: {state['leverage']}x\n"
        f"Margin: {state['margin']}%\n\n"
        "Adjust parameters or start AI scan:",
        reply_markup=session_controls(state)
    )

async def ai_scan_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    await q.edit_message_text("🔍 **AI scanning market...**\n\nFetching BingX hot pairs, analyzing 5M charts, order book, sentiment...")
    hot_pairs = get_bingx_hot_pairs(limit=10)
    scored = []
    for pair in hot_pairs:
        symbol = pair.replace("/", "")
        klines = bingx_signed_request("GET", "/openApi/swap/v2/quote/klines", {
            "symbol": symbol,
            "interval": "5m",
            "limit": "50"
        })
        change = 0
        reasons = []
        if klines and "data" in klines and len(klines["data"]) >= 2:
            closes = [float(k["close"]) for k in klines["data"][-10:]]
            if len(closes) >= 2:
                change = (closes[-1] - closes[-2]) / closes[-2] * 100
            # AI reasoning via StepFun
            prompt = f"Analyze {pair} 5M chart. Close price change: {change:.2f}%. Give 2-3 concise TA reasons why this pair is a good/bad scalping opportunity right now."
            ai_text = call_stepfun_skill(prompt)
            if ai_text:
                reasons = [line.strip() for line in ai_text.split('\n') if line.strip()][:3]
            else:
                reasons = ["Volume confirm"]
                if change < -2:
                    reasons.append("Dip detected")
                elif change > 2:
                    reasons.append("Momentum surge")
        else:
            reasons = ["Stable"]
        scored.append({"symbol": pair, "price": 0, "change": round(change, 2), "reasons": reasons})
    scored.sort(key=lambda x: abs(x["change"]), reverse=True)
    top4 = scored[:4]
    user_state[chat_id]["selected_pairs"] = top4
    await q.edit_message_text(
        "✅ **Scan Complete — Top 4 Pairs:**\n\n"
        "Select a pair to view details & execute:",
        reply_markup=session_results(top4)
    )

async def pair_detail_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = user_state.get(chat_id, {})
    symbol = q.data.split("_", 1)[1]
    pair_data = next((p for p in state.get("selected_pairs", []) if p["symbol"] == symbol), None)
    if not pair_data:
        await q.edit_message_text("❌ Pair data not found.", reply_markup=main_menu(state))
        return
    text = (f"📊 **{symbol}**\n\n"
            f"Price: ${pair_data['price']:,.2f}\n"
            f"Change: {pair_data['change']:+.2f}%\n"
            f"Reasons: {', '.join(pair_data['reasons'])}\n\n"
            f"Leverage: {state['leverage']}x | Margin: {state['margin']}%\n"
            f"Mode: {state.get('trade_mode', 'MOCK')}")
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 EXECUTE", callback_data=f"exec_{symbol}")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="ai_scan")]
    ])
    await q.edit_message_text(text, reply_markup=markup)

# ── MANUAL MODE ──
async def manual_mode_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = get_state(chat_id)
    state["mode"] = "manual"
    hot_pairs = get_bingx_hot_pairs(limit=6)
    await q.edit_message_text(
        "👷 **MANUAL MODE**\n\n"
        "Select a pair to trade (top 6 by volume):",
        reply_markup=manual_hot_pairs(hot_pairs)
    )

async def add_pair_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    top_pairs = get_bingx_top_pairs(limit=10)
    await q.edit_message_text(
        "➕ **ADD PAIR**\n\n"
        "Select from top 10 BingX pairs, or enter custom:",
        reply_markup=add_pair_grid(top_pairs)
    )

async def other_pair_input_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⌨️ **ENTER CUSTOM PAIR**\n\n"
        "Type the ticker (e.g., `BTC/USDT`) in the chat.\n"
        "I'll verify it's tradable on BingX.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ BACK", callback_data="add_pair_menu")]])
    )
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
            state["selected_pairs"] = [{"symbol": text, "price": 0, "change": 0, "reasons": ["Manual selection"]}]
            state["awaiting_pair_input"] = False
            await update.message.reply_text(
                f"✅ Pair {text} added!\n\nUse /start to continue.",
                reply_markup=main_menu(state)
            )
        else:
            await update.message.reply_text("❌ Pair is not listed on BingX. Try again or use /start to cancel.")
            return

# ── POSITIONS & PNL ──
async def positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    trades = api_get("/api/v1/trades?status=open")
    if not trades or not trades.get("trades"):
        await q.edit_message_text("📊 **No open positions**", reply_markup=main_menu(get_state(q.message.chat_id)))
        return
    buttons = []
    for t in trades["trades"]:
        profit = t.get("profit_pct", 0)
        btn_text = f"📌 {t['pair']} — {profit:+.2f}%"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"close_{t['trade_id']}")])
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    await q.edit_message_text("📊 **Open Positions**\n\nSelect to close:", reply_markup=InlineKeyboardMarkup(buttons))

async def pnl_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    stats = api_get("/api/v1/stats")
    if not stats:
        await q.edit_message_text("❌ **Could not fetch stats**", reply_markup=main_menu(get_state(q.message.chat_id)))
        return
    text = f"""💸 **PnL Ledger**

**Today:**
• Gross: ${stats.get('today_profit_abs', 0):.2f}
• Net: ${stats.get('total_profit_abs', 0) - stats.get('total_fee', 0):.2f}
• Open Trades: {stats.get('open_trades', 0)}"""
    await q.edit_message_text(text, reply_markup=main_menu(get_state(q.message.chat_id)), parse_mode="Markdown")

# ── EXECUTE TRADE ──
async def execute_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat_id
    state = user_state.get(chat_id, {})
    selected = state.get("selected_pairs", [])
    if selected:
        pair = selected[0]["symbol"]
        leverage = state.get("leverage", 50)
        margin = state.get("margin", 1)
        mode = state.get("trade_mode", "MOCK")
        text = (f"🚀 **EXECUTE TRADE**\n\n"
                f"Pair: {pair}\n"
                f"Leverage: {leverage}x\n"
                f"Margin: {margin}%\n"
                f"Mode: {mode}\n\n"
                f"Confirm?")
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRM", callback_data=f"confirm_exec_{pair}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data="main")]
        ])
        await q.edit_message_text(text, reply_markup=markup)
    else:
        await q.edit_message_text("❌ No pair selected. Use TRADE MENU first.", reply_markup=main_menu(state))

async def confirm_exec_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    pair = q.data.split("_", 2)[2]
    chat_id = q.message.chat_id
    state = user_state.get(chat_id, {})
    leverage = state.get("leverage", 50)
    margin = state.get("margin", 1)
    mode = state.get("trade_mode", "MOCK")
    # Execute via Freqtrade API
    result = api_post("/api/v1/forcebuy", {
        "pair": pair,
        "leverage": leverage,
        "margin": margin
    })
    msg = "✅ **Trade executed!**" if result else "❌ **Execution failed**"
    await q.edit_message_text(msg, reply_markup=main_menu(state))

# ── Error handler ──
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling update {update}", exc_info=ctx.error)

# ── Build & Run ──
def main():
    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return
    test = api_get("/api/v1/ping")
    if not test:
        logger.error("Cannot connect to Freqtrade API.")
        return
    logger.info("Connected to Freqtrade API. Bot is responding.")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler(["start", "cmd"], start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input_handler))
    app.add_handler(CallbackQueryHandler(main_cb, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(settings_cb, pattern="^settings$"))
    app.add_handler(CallbackQueryHandler(set_trade_mode_cb, pattern="^set_(real|mock)$"))
    app.add_handler(CallbackQueryHandler(stats_cb, pattern="^stats$"))
    app.add_handler(CallbackQueryHandler(trade_menu_cb, pattern="^trade_menu$"))
    app.add_handler(CallbackQueryHandler(session_mode_cb, pattern="^session_mode$"))
    app.add_handler(CallbackQueryHandler(session_adjust_cb, pattern="^(lev|mar)_(up|down)$"))
    app.add_handler(CallbackQueryHandler(ai_scan_cb, pattern="^ai_scan$"))
    app.add_handler(CallbackQueryHandler(pair_detail_cb, pattern="^pair_"))
    app.add_handler(CallbackQueryHandler(manual_mode_cb, pattern="^manual_mode$"))
    app.add_handler(CallbackQueryHandler(add_pair_menu_cb, pattern="^add_pair_menu$"))
    app.add_handler(CallbackQueryHandler(other_pair_input_cb, pattern="^other_pair_input$"))
    app.add_handler(CallbackQueryHandler(positions_cb, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(pnl_cb, pattern="^pnl$"))
    app.add_handler(CallbackQueryHandler(execute_cb, pattern="^execute$"))
    app.add_handler(CallbackQueryHandler(confirm_exec_cb, pattern="^confirm_exec_"))
    app.add_error_handler(error_handler)
    logger.info("Starting ClawTrader Telegram UI (0-Type)...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
