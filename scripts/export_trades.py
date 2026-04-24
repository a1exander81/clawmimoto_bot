#!/usr/bin/env python3
"""
Export trades from Freqtrade to CSV/JSON for analysis.
Part 1 of 3 — Imports and fetch functions.
"""

import requests
import json
import statistics
import subprocess
from datetime import datetime, timezone
from pathlib import Path

FREQTRADE_URL = "http://localhost:8080"
AUTH = ("clawforge", "CiRb7PvcBwsVVs7XnKvw")

def fetch_trades():
    r = requests.get(
        f"{FREQTRADE_URL}/api/v1/trades",
        auth=AUTH,
        params={"limit": 500},
        timeout=10
    )
    return r.json().get("trades", [])

def fetch_stats():
    r = requests.get(
        f"{FREQTRADE_URL}/api/v1/stats",
        auth=AUTH,
        timeout=10
    )
    return r.json()

def convert_trade(t):
    entry_ts = t.get("open_date")
    exit_ts = t.get("close_date")
    profit_pct = t.get("profit_ratio", 0) * 100
    try:
        dt = datetime.fromisoformat(
            entry_ts.replace("Z","+00:00")
        )
        sgt_hour = (dt.hour + 8) % 24
        if 6 <= sgt_hour < 7:
            session = "pre_london"
        elif 16 <= sgt_hour < 20:
            session = "london"
        elif 21 <= sgt_hour <= 23:
            session = "ny"
        else:
            session = "manual"
    except:
        session = "manual"

    return {
        "trade_id": t.get("trade_id"),
        "pair": t.get("pair"),
        "session": session,
        "direction": "SHORT" if t.get("is_short") else "LONG",
        "entry_ts": entry_ts,
        "exit_ts": exit_ts,
        "entry_price": t.get("open_rate"),
        "exit_price": t.get("close_rate"),
        "profit_pct": round(profit_pct, 4),
        "profit_abs": round(t.get("profit_abs", 0), 4),
        "leverage": t.get("leverage", 1),
        "duration_min": t.get("trade_duration", 0),
        "exit_reason": t.get("exit_reason"),
        "win": profit_pct > 0,
        "stake_amount": t.get("stake_amount"),
    }

def calculate_metadata(trades, period):
    """
    Calculate performance metadata from a list of converted trades.
    Returns dict with aggregated stats.
    """
    if not trades:
        return {}
    wins = [t for t in trades if t["win"]]
    total = len(trades)
    win_rate = len(wins) / total * 100 if total > 0 else 0
    total_pnl = sum(t["profit_pct"] for t in trades)
    pnls = [t["profit_pct"] for t in trades]
    if len(pnls) > 1:
        avg = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        sharpe = (avg / std * (252**0.5)) if std > 0 else 0
    else:
        sharpe = 0
    cumulative = 0
    peak = 0
    max_dd = 0
    for t in trades:
        cumulative += t["profit_pct"]
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    sessions = {}
    for s in ["pre_london", "london", "ny", "manual"]:
        s_trades = [t for t in trades if t["session"] == s]
        sessions[s] = {
            "count": len(s_trades),
            "win_rate": round(len([t for t in s_trades if t["win"]]) / len(s_trades) * 100, 2) if s_trades else 0,
            "total_pnl": round(sum(t["profit_pct"] for t in s_trades), 2)
        }
    return {
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_trades": total,
        "win_rate": round(win_rate, 2),
        "total_pnl_pct": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "avg_duration_min": round(sum(t["duration_min"] for t in trades) / total, 1),
        "avg_leverage": round(sum(t["leverage"] for t in trades) / total, 1),
        "sessions": sessions,
        "best_trade": max(trades, key=lambda x: x["profit_pct"])["profit_pct"] if trades else 0,
        "worst_trade": min(trades, key=lambda x: x["profit_pct"])["profit_pct"] if trades else 0,
    }

def export():
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    print(f"Starting export for {period}...")

    trades_raw = fetch_trades()
    trades = [convert_trade(t) for t in trades_raw if t.get("close_date")]

    if not trades:
        print("No closed trades to export")
        return

    print(f"Found {len(trades)} closed trades")

    base = Path("/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-backtests/backtests")
    out_dir = base / period / "live"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Write trades.jsonl
    with open(out_dir / "trades.jsonl", "w") as f:
        for t in trades:
            f.write(json.dumps(t) + "\n")
    print(f"Wrote trades.jsonl")

    # Write metadata.json
    meta = calculate_metadata(trades, period)
    with open(out_dir / "metadata.json", "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Wrote metadata.json")
    print(f"Stats: {meta['total_trades']} trades | WR: {meta['win_rate']}% | PnL: {meta['total_pnl_pct']}%")

    # Git commit and push
    repo = Path("/docker/openclaw-0jn0/data/.openclaw/workspace/clawmimoto-backtests")
    subprocess.run(["git", "add", "backtests/"], cwd=repo)
    result = subprocess.run([
        "git", "commit", "-m",
        f"data: trade export {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    ], cwd=repo, capture_output=True, text=True)
    print(result.stdout)
    subprocess.run(["git", "push"], cwd=repo)
    print("Pushed to GitHub")

if __name__ == "__main__":
    export()
