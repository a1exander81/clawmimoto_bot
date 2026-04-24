#!/usr/bin/env python3
"""
Supabase Sync — ClawForge
Polls Freqtrade every 30s, pushes new trades to Supabase.
"""
import os
import sys
import json
import time
import requests
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# Config
SUPABASE_URL = "https://aauypnqsmyxzacchbiya.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImFhdXlwbnFzbXl4emFjY2hiaXlhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3Njk3ODYwNSwiZXhwIjoyMDkyNTU0NjA1fQ.BXd5zfbNDGLn6Mvuaky3yVeEQebsR_ICIJz0LxZIZ_Y"
FT_URL = "http://127.0.0.1:8080"
FT_USER = "clawforge"
FT_PASS = open('/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-bot/.env').read()
FT_PASS = [l.split('=',1)[1].strip() for l in FT_PASS.split('\n') if l.startswith('FREQTRADE_API_PASS')][0]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

def ft_get(endpoint):
    try:
        r = requests.get(f"{FT_URL}{endpoint}", auth=(FT_USER, FT_PASS), timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f"Freqtrade error: {e}")
    return None

def supabase_upsert(table, data):
    try:
        r = requests.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            headers=HEADERS,
            json=data if isinstance(data, list) else [data],
            timeout=10
        )
        if r.status_code in [200, 201]:
            return True
        logger.error(f"Supabase error {r.status_code}: {r.text[:200]}")
    except Exception as e:
        logger.error(f"Supabase upsert error: {e}")
    return False

def supabase_get(table, params=""):
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{params}",
            headers=HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        logger.error(f"Supabase get error: {e}")
    return []

def sync_trades():
    """Sync closed trades from Freqtrade to Supabase."""
    trades = ft_get("/api/v1/trades?limit=50")
    if not trades:
        return

    # Get existing trade IDs from Supabase
    existing = supabase_get("trades", "select=trade_id")
    existing_ids = {t["trade_id"] for t in existing}

    new_trades = []
    for t in trades.get("trades", []):
        if t.get("is_open"):
            continue  # skip open trades
        trade_id = t.get("trade_id") or t.get("id")
        if trade_id in existing_ids:
            continue  # already synced

        # Determine session
        open_hour = 0
        try:
            open_dt = datetime.fromisoformat(t.get("open_date", "").replace("Z", "+00:00"))
            open_hour = open_dt.hour
        except:
            pass

        if 5 <= open_hour < 8:
            session = "pre_london"
        elif 7 <= open_hour < 13:
            session = "london"
        elif 12 <= open_hour < 18:
            session = "ny"
        else:
            session = "manual"

        new_trades.append({
            "trade_id": trade_id,
            "pair": t.get("pair"),
            "direction": "SHORT" if t.get("is_short") else "LONG",
            "entry_price": t.get("open_rate"),
            "close_price": t.get("close_rate"),
            "profit_ratio": t.get("profit_ratio"),
            "profit_abs": t.get("profit_abs"),
            "exit_reason": t.get("exit_reason"),
            "open_date": t.get("open_date"),
            "close_date": t.get("close_date"),
            "leverage": int(t.get("leverage") or 20),
            "stake_amount": t.get("stake_amount"),
            "is_open": False,
            "session": session
        })

    if new_trades:
        if supabase_upsert("trades", new_trades):
            logger.info(f"Synced {len(new_trades)} new trades to Supabase")
    else:
        logger.debug("No new trades to sync")

def sync_open_trades():
    """Sync open trades to Supabase."""
    open_trades = ft_get("/api/v1/status")
    if not open_trades:
        return

    for t in open_trades:
        trade_id = t.get("trade_id") or t.get("id")
        supabase_upsert("trades", {
            "trade_id": trade_id,
            "pair": t.get("pair"),
            "direction": "SHORT" if t.get("is_short") else "LONG",
            "entry_price": t.get("open_rate"),
            "profit_ratio": t.get("profit_ratio"),
            "profit_abs": t.get("profit_abs"),
            "open_date": t.get("open_date"),
            "leverage": int(t.get("leverage") or 20),
            "stake_amount": t.get("stake_amount"),
            "is_open": True,
            "session": "live"
        })

def keepalive():
    """Ping Supabase to prevent free tier pausing."""
    try:
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/trades?limit=1",
            headers=HEADERS,
            timeout=10
        )
        logger.info(f"Keepalive ping: {r.status_code}")
    except Exception as e:
        logger.error(f"Keepalive error: {e}")

def main():
    logger.info("Supabase sync started")
    ping_counter = 0
    
    while True:
        try:
            sync_trades()
            sync_open_trades()
            ping_counter += 1
            
            # Keepalive every 100 cycles (~50 min)
            if ping_counter >= 100:
                keepalive()
                ping_counter = 0
                
        except Exception as e:
            logger.error(f"Sync error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    main()
