"""Web3 subscription gating — Solana Pay verification."""

import os
from typing import Optional
from pathlib import Path
import json

class SubscriptionGate:
    """Check if user has paid for ClawForge access."""

    def __init__(self, db_path: str = "data/subscriptions.json"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def _load(self):
        if self.db_path.exists():
            with open(self.db_path) as f:
                self.db = json.load(f)
        else:
            self.db = {"subscribers": {}}

    def _save(self):
        with open(self.db_path, "w") as f:
            json.dump(self.db, f, indent=2)

    def verify_payment(self, txid: str, expected_amount: float = 10.0) -> bool:
        """
        Verify Solana transaction via RPC.
        In production, call Solana RPC getTransaction.
        """
        # Stub — replace with actual Solana RPC check
        if txid and len(txid) > 10:
            return True
        return False

    def is_subscribed(self, telegram_id: int) -> bool:
        return str(telegram_id) in self.db.get("subscribers", {})

    def add_subscriber(self, telegram_id: int, txid: str, tier: str = "basic"):
        self.db["subscribers"][str(telegram_id)] = {
            "txid": txid,
            "tier": tier,
            "active": True
        }
        self._save()

gate = SubscriptionGate()
