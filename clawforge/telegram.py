"""ClawForge Telegram Bot — Pure button-driven UI."""

import logging
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)
from freqtrade.rpc import RPC

logger = logging.getLogger(__name__)

# ── Keyboards ──

def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📈 TRADE MENU", callback_data="trade_menu")],
        [InlineKeyboardButton("📊 POSITIONS", callback_data="positions")],
        [InlineKeyboardButton("💸 PnL LEDGER", callback_data="pnl")],
        [InlineKeyboardButton("🚀 EXECUTE TRADE", callback_data="execute")],
    ])

def trade_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 NY SESSION", callback_data="session_ny")],
        [InlineKeyboardButton("🟢 TOKYO SESSION", callback_data="session_tokyo")],
        [InlineKeyboardButton("🟢 LONDON SESSION", callback_data="session_london")],
        [InlineKeyboardButton("🟢 ALL SESSIONS", callback_data="session_all")],
        [InlineKeyboardButton("🔴 DISARM", callback_data="session_off")],
        [InlineKeyboardButton("⬅️ BACK", callback_data="main")],
    ])

def positions_list(trades: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"📌 {t['pair']} — {t['profit_pct']:+.2f}%", callback_data=f"close_{t['id']}")]
        for t in trades
    ]
    buttons.append([InlineKeyboardButton("⬅️ BACK", callback_data="main")])
    return InlineKeyboardMarkup(buttons)

# ── Handlers ──

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🏠 **ClawForge Command Center**", reply_markup=main_menu())

async def main_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("🏠 **ClawForge Command Center**\n\nSelect an action:", reply_markup=main_menu())

async def trade_menu_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text(
        "⏰ **Select Trading Session**\n\n"
        "NY: 00:00–08:00 UTC\n"
        "Tokyo: 08:00–16:00 UTC\n"
        "London: 16:00–24:00 UTC\n\n"
        "_Bot scans only during selected session(s)_",
        reply_markup=trade_menu()
    )

async def positions_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rpc: RPC = ctx.bot_data["rpc"]
    trades = rpc.open_trades()
    if not trades:
        await q.edit_message_text("📊 **No open positions**", reply_markup=main_menu())
        return
    await q.edit_message_text("📊 **Open Positions**\n\nSelect to close:", reply_markup=positions_list(trades))

async def pnl_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rpc: RPC = ctx.bot_data["rpc"]
    stats = rpc.stats()
    text = f"""💸 **PnL Ledger**

**Today:**
• Gross: `${stats['today_profit_abs']:.2f}`
• Net: `${stats['total_profit_abs'] - stats.get('total_fee', 0):.2f}`
• Open Trades: {stats['open_trades']}

_Updates every 3s_"""
    await q.edit_message_text(text, reply_markup=main_menu(), parse_mode="Markdown")

async def execute_cb(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    rpc: RPC = ctx.bot_data["rpc"]
    result = rpc.forcebuy()
    msg = "✅ **Trade executed**" if result else "❌ **Execution failed**"
    await q.edit_message_text(msg, reply_markup=main_menu())

# ── Builder ──

def build_bot(token: str, rpc: Optional[RPC] = None) -> Application:
    app = Application.builder().token(token).build()
    app.bot_data["rpc"] = rpc

    app.add_handler(CommandHandler(["start", "cmd"], start))
    app.add_handler(CallbackQueryHandler(main_cb, pattern="^main$"))
    app.add_handler(CallbackQueryHandler(trade_menu_cb, pattern="^trade_menu$"))
    app.add_handler(CallbackQueryHandler(positions_cb, pattern="^positions$"))
    app.add_handler(CallbackQueryHandler(pnl_cb, pattern="^pnl$"))
    app.add_handler(CallbackQueryHandler(execute_cb, pattern="^execute$"))

    return app
