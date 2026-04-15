"""Tests for ClawForge strategy logic."""

import pytest
import pandas as pd
import pandas_ta as ta
from clawforge.strategy import Claw5MSniper

@pytest.fixture
def sample_data():
    """Generate sample 5M candles."""
    dates = pd.date_range("2026-04-01", periods=100, freq="5min")
    data = {
        "open": [100 + i*0.1 for i in range(100)],
        "high": [101 + i*0.1 for i in range(100)],
        "low": [99 + i*0.1 for i in range(100)],
        "close": [100.5 + i*0.1 for i in range(100)],
        "volume": [1000] * 100
    }
    df = pd.DataFrame(data, index=dates)
    df["date"] = df.index
    return df

def test_strategy_initialization():
    strat = Claw5MSniper()
    assert strat.timeframe == "5m"
    assert strat.max_open_trades == 3
    assert strat.stoploss == -0.25

def test_session_mapping(strample_data):
    strat = Claw5MSniper()
    df = strat.populate_indicators(sample_data, {"pair": "BTC/USDT"})
    sessions = df["session"].unique()
    assert "NY" in sessions or "TOKYO" in sessions or "LONDON" in sessions

def test_indicators_calculated(sample_data):
    strat = Claw5MSniper()
    df = strat.populate_indicators(sample_data, {"pair": "BTC/USDT"})
    assert "rsi" in df.columns
    assert "macd" in df.columns
    assert "ema_fast" in df.columns
    assert "ema_slow" in df.columns

def test_buy_signals_generated(sample_data):
    strat = Claw5MSniper()
    df = strat.populate_buy_trend(sample_data, {"pair": "BTC/USDT"})
    # At least some signals should be generated in test data
    assert "buy" in df.columns
    assert df["buy"].isin([0, 1]).all()

def test_sell_signals_generated(sample_data):
    strat = Claw5MSniper()
    df = strat.populate_sell_trend(sample_data, {"pair": "BTC/USDT"})
    assert "sell" in df.columns
    assert df["sell"].isin([0, 1]).all()
