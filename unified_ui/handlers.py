# unified_ui/handlers.py
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config.sessions import TRADING_SESSIONS, get_market_state
from clawforge.liquidity_gate import (
    is_market_tradable,
    get_claw_params,
    get_grid_params,
    get_weekend_grid_params,
    get_weekday_grid_params,
)
from unified_ui.main_menu import main_menu_keyboard

logger = logging.getLogger(__name__)

active_sessions = {
    "claw": None,
    "grid": None,
}


def _market_banner() -> str:
    """Return a weekend warning banner if applicable."""
    state = get_market_state()
    if state.get("is_weekend", False):
        return (
            "📉 **WEEKEND MARKET** — Reduced liquidity. "
            "Fake breakout risk elevated.\n"
            "🕸️ Grid layer: conservative mode | "
            "⚔️ Claw layer: mean-reversion only\n\n"
        )
    return ""


async def claw_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 1)
    if len(parts) != 2:
        await query.edit_message_text("❌ Malformed callback data.")
        return
    _, session_key = parts
    session = TRADING_SESSIONS.get(session_key)
    if not session:
        await query.edit_message_text("❌ Unknown session.")
        return

    # ── Market state check ──
    state = get_market_state()
    banner = _market_banner()

    # ── Liquidity gate check for a representative pair ──
    is_ok, reason = is_market_tradable("BTC/USDT", layer="claw")
    if not is_ok:
        text = (
            f"{banner}"
            f"🚫 **Claw — Liquidity Gate Blocked**\n\n"
            f"Market conditions unsuitable for Claw (directional) trading.\n"
            f"Reason: {reason}\n\n"
            f"Switch to a different session or try again later."
        )
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Apply Claw-specific params ──
    active_sessions["claw"] = session_key
    claw_params = get_claw_params(state)
    reversion_warning = ""
    if claw_params.get("mean_reversion_only"):
        reversion_warning = "\n⚠️ Mean-reversion setups only (weekend mode)."

    text = (
        f"{banner}"
        f"🔥 Clawmimoto switched to **{session['emoji']} {session['name']}** session.\n"
        f"Volatility: {session['volatility_level'].upper()}\n"
        f"Max trades: {claw_params['max_trades']}\n"
        f"Risk per trade: {claw_params['risk_per_trade_pct']}%{reversion_warning}"
    )
    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def claw_stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    active_sessions["claw"] = None
    await query.edit_message_text("🛑 Clawmimoto stopped.", reply_markup=main_menu_keyboard())


async def grid_session_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":", 1)
    if len(parts) != 2:
        await query.edit_message_text("❌ Malformed callback data.")
        return
    _, session_key = parts

    # ── Market state & liquidity check ──
    state = get_market_state()
    banner = _market_banner()

    is_ok, reason = is_market_tradable("BTC/USDT", layer="grid")
    if not is_ok:
        text = (
            f"{banner}"
            f"🚫 **Grid — Liquidity Gate Blocked**\n\n"
            f"Market conditions unsuitable for Grid (contrarian) trading.\n"
            f"Reason: {reason}\n\n"
            f"Try again later or select a different time."
        )
        await query.edit_message_text(
            text,
            reply_markup=main_menu_keyboard(),
            parse_mode="Markdown",
        )
        return

    # ── Get grid params ──
    grid_params = get_grid_params(state)
    active_sessions["grid"] = session_key

    text = (
        f"{banner}"
        f"🕸️ Grid Engine switched to **{grid_params['label']}**.\n"
        f"Grid spacing factor: {grid_params['grid_spacing_factor']}\n"
        f"TP markup: {grid_params['tp_markup_pct']}%\n"
        f"Max wallet exposure: {grid_params['max_wallet_exposure_pct']}%\n"
        f"Max trades: {grid_params.get('max_trades_per_session', 3)}"
    )
    await query.edit_message_text(
        text,
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def grid_stop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    active_sessions["grid"] = None
    await query.edit_message_text("🛑 Grid Engine stopped.", reply_markup=main_menu_keyboard())


async def ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
