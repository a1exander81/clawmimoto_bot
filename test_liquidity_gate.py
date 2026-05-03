# test_liquidity_gate.py
"""Quick test script to verify the liquidity gate and market state."""
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config.sessions import get_market_state, WEEKDAY_PROFILES, TRADING_SESSIONS
from clawforge.liquidity_gate import (
    is_market_tradable,
    get_claw_params,
    get_weekend_grid_params,
    get_weekday_grid_params,
    get_grid_params,
)


def test_market_state():
    """Test the market state detection."""
    state = get_market_state()
    print(f"{'='*50}")
    print("MARKET STATE")
    print(f"{'='*50}")
    print(f"  Weekday:      {state['weekday']}")
    print(f"  Is Weekend:   {state['is_weekend']}")
    print(f"  Session:      {state['active_session']}")
    print(f"  Tendency:     {state['tendency']}")
    print(f"  Vol Rank:     {state['volatility_rank']}")
    print()

    # Show profile for current day
    profile = WEEKDAY_PROFILES.get(state['weekday'], {})
    if profile:
        print(f"  Day Profile:  {state['weekday']}")
        print(f"    Avg Return: {profile.get('avg_return_pct', '?')}%")
        print(f"    Tendency:   {profile.get('tendency', '?')}")

    # Show all sessions
    print(f"\n  Active Sessions:")
    for key in sorted(TRADING_SESSIONS.keys()):
        sess = TRADING_SESSIONS[key]
        marker = " ◀ ACTIVE" if key == state.get('active_session') else ""
        print(f"    {sess['emoji']} {sess['name']:20s} "
              f"{sess['gmt_start'].strftime('%H:%M')}-{sess['gmt_end'].strftime('%H:%M')} UTC"
              f"  [{sess['volatility_level']}]{marker}")
    print()


def test_liquidity_gate():
    """Test the liquidity gate against Bybit live data (up to 15s cooldown)."""
    print(f"{'='*50}")
    print("LIQUIDITY GATE")
    print(f"{'='*50}")

    for pair in ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        for layer in ["claw", "grid"]:
            tradable, reason = is_market_tradable(pair, layer=layer)
            status = "✅ TRADABLE" if tradable else "❌ BLOCKED"
            print(f"  {status} | {pair:12s} | {layer:5s} | {reason}")
    print()


def test_grid_params():
    """Test grid parameter selection."""
    print(f"{'='*50}")
    print("GRID PARAMETERS")
    print(f"{'='*50}")

    print("  Weekend params:")
    wp = get_weekend_grid_params()
    for k, v in wp.items():
        print(f"    {k:30s} = {v}")

    print("\n  Weekday params per session:")
    for sk in ["pre_london", "london", "ny_overlap", "ny"]:
        dp = get_weekday_grid_params(sk)
        print(f"    {dp['label']:40s} spacing={dp['grid_spacing_factor']}  "
              f"tp={dp['tp_markup_pct']}  exposure={dp['max_wallet_exposure_pct']}%")

    print("\n  get_grid_params (auto-dispatch):")
    state = get_market_state()
    gp = get_grid_params(state)
    print(f"    Active: {gp['label']:35s} spacing={gp['grid_spacing_factor']}  "
          f"tp={gp['tp_markup_pct']}  exposure={gp['max_wallet_exposure_pct']}%")
    print()


def test_claw_params():
    """Test Claw-specific parameter selection."""
    print(f"{'='*50}")
    print("CLAW PARAMETERS")
    print(f"{'='*50}")

    state = get_market_state()
    cp = get_claw_params(state)
    print(f"  Claw mode:   {cp['label']}")
    print(f"  Max trades:  {cp['max_trades']}")
    print(f"  Risk/trade:  {cp['risk_per_trade_pct']}%")
    print(f"  Volume thr:  {cp['min_volume_threshold']}")
    print(f"  Mean-rev:    {cp['mean_reversion_only']}")
    print()


if __name__ == "__main__":
    print()
    test_market_state()
    test_grid_params()
    test_claw_params()
    test_liquidity_gate()

    print(f"{'='*50}")
    print("ALL TESTS COMPLETE")
    print(f"{'='*50}")
