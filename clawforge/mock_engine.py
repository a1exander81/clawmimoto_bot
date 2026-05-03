# clawforge/mock_engine.py
"""Mock trading engine with CLUSDT virtual balance backed by Supabase."""
import ccxt
import logging
import requests
from datetime import datetime, timezone
from typing import Optional, Tuple
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://aauypnqsmyxzacchbiya.supabase.co")
# Use service role key for write operations (insert/update on mock tables),
# fall back to anon key if service role not set.
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFhdXlwbnFzbXl4emFjY2hiaXlhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzY5Nzg2MDUsImV4cCI6MjA5MjU1NDYwNX0.H8RbnYbUb55jr0RnOVpca2wkYgv_jKs8NuUHjruqWls",
)

INITIAL_BALANCE = 10_000.0


def _headers() -> dict:
    return {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _rest(method: str, table: str, params: str = "", json_data=None) -> Optional[list]:
    """Generic Supabase REST helper."""
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    if params:
        url += f"?{params}"
    try:
        r = requests.request(
            method,
            url,
            headers=_headers(),
            json=json_data,
            timeout=10,
        )
        if r.status_code in (200, 201):
            return r.json() if r.text else []
        logger.warning("Supabase %s %s → %s: %s", method, table, r.status_code, r.text[:200])
    except Exception as e:
        logger.error("Supabase REST error: %s", e)
    return None


class MockEngine:
    """Simulate trades using a virtual CLUSDT balance in Supabase."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.exchange = ccxt.bybit({"enableRateLimit": True})
        self.fee_rate = 0.001  # 0.1 % mock fee

    # ── Account helpers ──────────────────────────────────────

    def _ensure_account(self):
        """Create account row with initial_balance if it doesn't exist."""
        rows = _rest(
            "GET",
            "mock_accounts",
            f"user_id=eq.{self.user_id}&select=user_id",
        )
        if rows is None:
            return  # transient error, caller will handle
        if not rows:
            _rest(
                "POST",
                "mock_accounts",
                json_data={
                    "user_id": self.user_id,
                    "balance_clusdt": INITIAL_BALANCE,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    # ── Balance ─────────────────────────────────────────────

    def get_balance(self) -> float:
        """Return current CLUSDT balance (0.0 if no account)."""
        self._ensure_account()
        rows = _rest("GET", "mock_accounts", f"user_id=eq.{self.user_id}&select=balance_clusdt")
        if rows and len(rows) > 0:
            return float(rows[0]["balance_clusdt"])
        return 0.0

    def update_balance(self, delta: float):
        """Add *delta* to balance (negative for debit)."""
        current = self.get_balance()
        new_bal = round(current + delta, 2)
        _rest(
            "PATCH",
            "mock_accounts",
            params=f"user_id=eq.{self.user_id}",
            json_data={"balance_clusdt": new_bal},
        )

    # ── Order simulation ─────────────────────────────────────

    def place_order(
        self, symbol: str, side: str, qty: float, price: Optional[float] = None
    ) -> dict:
        """Simulate a limit order. Fills immediately if market price permits.

        Returns ``{"status": "filled", "price": <fill_price>}`` or
        ``{"status": "open", "message": "Price not reached"}``.
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker["last"]
        except Exception as e:
            logger.error("Cannot fetch ticker for %s: %s", symbol, e)
            return {"status": "error", "message": str(e)[:100]}

        fill_price = None
        if side == "buy" and (price is None or current_price <= price):
            fill_price = current_price
        elif side == "sell" and (price is None or current_price >= price):
            fill_price = current_price

        if fill_price:
            fee = round(qty * fill_price * self.fee_rate, 2)
            self.update_balance(-fee)
            trade_data = {
                "user_id": self.user_id,
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "price": fill_price,
                "pnl_clusdt": 0.0,
                "fee_clusdt": fee,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "strategy": "mock",
            }
            _rest("POST", "mock_trades", json_data=trade_data)
            self._update_position(symbol, side, qty, fill_price)
            return {"status": "filled", "price": fill_price}
        return {"status": "open", "message": "Price not reached"}

    def close_position(self, symbol: str) -> Tuple[bool, str]:
        """Close an open mock position at current market price."""
        pos = self.get_position(symbol)
        if not pos:
            return False, "No open position"
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            current_price = ticker["last"]
        except Exception as e:
            return False, f"Price fetch error: {str(e)[:80]}"

        side = pos["side"]
        qty = float(pos["size"])
        entry_price = float(pos["entry_price"])

        pnl = (current_price - entry_price) * qty if side == "buy" else (entry_price - current_price) * qty
        fee = round(qty * current_price * self.fee_rate, 2)
        net_pnl = round(pnl - fee, 2)
        self.update_balance(net_pnl)

        close_side = "sell" if side == "buy" else "buy"
        _rest(
            "POST",
            "mock_trades",
            json_data={
                "user_id": self.user_id,
                "symbol": symbol,
                "side": close_side,
                "qty": qty,
                "price": current_price,
                "pnl_clusdt": net_pnl,
                "fee_clusdt": fee,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "strategy": "mock",
            },
        )

        _rest("DELETE", "mock_positions", params=f"user_id=eq.{self.user_id}&symbol=eq.{symbol}")

        emoji = "🟢" if net_pnl >= 0 else "🔴"
        return True, f"{emoji} Closed {symbol} — PnL: {net_pnl:+.2f} CLUSDT"

    # ── Positions ────────────────────────────────────────────

    def _update_position(self, symbol: str, side: str, qty: float, price: float):
        """Upsert mock position (volume-weighted average entry)."""
        existing = self.get_position(symbol)
        now_iso = datetime.now(timezone.utc).isoformat()
        if existing:
            old_size = float(existing["size"])
            old_entry = float(existing["entry_price"])
            new_size = old_size + qty
            new_entry = round((old_entry * old_size + price * qty) / new_size, 4)
            _rest(
                "PATCH",
                "mock_positions",
                params=f"user_id=eq.{self.user_id}&symbol=eq.{symbol}",
                json_data={
                    "size": new_size,
                    "entry_price": new_entry,
                    "updated_at": now_iso,
                },
            )
        else:
            _rest(
                "POST",
                "mock_positions",
                json_data={
                    "user_id": self.user_id,
                    "symbol": symbol,
                    "side": side,
                    "size": qty,
                    "entry_price": price,
                    "mark_price": price,
                    "unrealised_pnl": 0.0,
                    "updated_at": now_iso,
                },
            )

    def get_position(self, symbol: str) -> Optional[dict]:
        """Return position dict or None."""
        rows = _rest(
            "GET",
            "mock_positions",
            f"user_id=eq.{self.user_id}&symbol=eq.{symbol}&select=*",
        )
        if rows and len(rows) > 0:
            return rows[0]
        return None

    def get_all_positions(self) -> list:
        """Return list of all open mock positions."""
        rows = _rest("GET", "mock_positions", f"user_id=eq.{self.user_id}&select=*")
        return rows or []

    # ── Trade history ────────────────────────────────────────

    def get_trade_history(self, limit: int = 20) -> list:
        """Return most recent mock trades, newest first."""
        rows = _rest(
            "GET",
            "mock_trades",
            f"user_id=eq.{self.user_id}&order=closed_at.desc&limit={limit}&select=*",
        )
        return rows or []
