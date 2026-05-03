# grid_layer/process_manager.py
"""Passivbot subprocess manager – launches and monitors grid trading instances."""
import subprocess
import sys
import os
import logging

logger = logging.getLogger(__name__)
active_grid_bots = {}  # symbol -> Popen object

def start_grid_bot(symbol: str, config_path: str) -> str:
    """Launch passivbot for a given symbol with config path."""
    if symbol in active_grid_bots and active_grid_bots[symbol].poll() is None:
        return f"Grid bot for {symbol} already running (PID {active_grid_bots[symbol].pid})."
    passivbot_dir = os.environ.get("PASSIVBOT_DIR", "./passivbot")
    cmd = [sys.executable, f"{passivbot_dir}/src/main.py", config_path]
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=passivbot_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        active_grid_bots[symbol] = proc
        logger.info(f"Grid bot {symbol} started (PID {proc.pid})")
        return f"✅ Grid bot {symbol} started (PID {proc.pid})"
    except Exception as e:
        logger.error(f"Failed to start grid bot {symbol}: {e}")
        return f"❌ Failed to start {symbol}: {str(e)}"

def stop_grid_bot(symbol: str) -> str:
    """Stop a running grid bot."""
    proc = active_grid_bots.get(symbol)
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
        del active_grid_bots[symbol]
        logger.info(f"Grid bot {symbol} stopped.")
        return f"🛑 Grid bot {symbol} stopped."
    return f"No active grid bot for {symbol}."

def get_active_grid_bots() -> dict:
    """Return dict of currently running grid bots: {symbol: pid}."""
    alive = {}
    for sym, proc in list(active_grid_bots.items()):
        if proc.poll() is None:
            alive[sym] = proc.pid
        else:
            # Clean up dead entries
            del active_grid_bots[sym]
    return alive
