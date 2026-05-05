"""
Claw5MSniper — Base strategy for ClawForge.
5M TF, ISOLATED margin, 3 trades/day max, trailing SL at +50%.
"""

import os
from datetime import datetime

import pandas as pd
import pandas_ta as ta
from freqtrade.strategy import BooleanParameter, DecimalParameter, IntParameter, IStrategy


class Claw5MSniper(IStrategy):
    """5-minute sniper with institutional risk management."""

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 50

    # ── Risk Management (configurable via env/config) ──
    max_open_trades = 3

    @property
    def stoploss(self) -> float:
        """Configurable stoploss. Range: -0.005 to -0.05 (0.5% to 5%)"""
        val = float(os.getenv("CLAW_STOPLOSS", "-0.01"))
        return max(-0.05, min(-0.005, val))

    @property
    def trailing_stop(self) -> bool:
        """Configurable trailing stop enable/disable"""
        return os.getenv("CLAW_TRAILING_STOP", "true").lower() in ("true", "1", "yes")

    @property
    def trailing_stop_positive(self) -> float:
        """Configurable trailing stop positive. Range: 0.005 to 0.03 (0.5% to 3%)"""
        val = float(os.getenv("CLAW_TRAILING_STOP_POSITIVE", "0.01"))
        return max(0.005, min(0.03, val))

    @property
    def trailing_stop_positive_offset(self) -> float:
        """Configurable trailing stop positive offset. Range: 0.005 to 0.05 (0.5% to 5%)"""
        val = float(os.getenv("CLAW_TRAILING_STOP_POSITIVE_OFFSET", "0.012"))
        return max(0.005, min(0.05, val))

    trailing_only_offset_is_reached = True
    minimal_roi = {"0": 1.0}

    # ── Indicators ──
    rsi_enabled = BooleanParameter(default=True, space="buy")
    rsi_period = IntParameter(10, 30, default=14, space="buy")
    rsi_buy = IntParameter(20, 40, default=30, space="buy")
    rsi_sell = IntParameter(60, 80, default=70, space="sell")

    macd_enabled = BooleanParameter(default=True, space="buy")
    macd_fast = IntParameter(8, 20, default=12, space="buy")
    macd_slow = IntParameter(20, 40, default=26, space="buy")
    macd_signal = IntParameter(5, 15, default=9, space="buy")

    ema_fast = IntParameter(5, 20, default=10, space="buy")
    ema_slow = IntParameter(20, 50, default=30, space="buy")

    # ── DeepSeek AI Sentiment ──
    use_sentiment = BooleanParameter(default=True, space="buy")
    sentiment_threshold = DecimalParameter(0.6, 0.9, default=0.82, space="buy")

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()

        if self.rsi_enabled.value:
            df["rsi"] = ta.rsi(df["close"], length=self.rsi_period.value)

        if self.macd_enabled.value:
            macd = ta.macd(df["close"], fast=self.macd_fast.value, slow=self.macd_slow.value, signal=self.macd_signal.value)
            df["macd"] = macd["MACD_12_26_9"]
            df["macdsignal"] = macd["MACDs_12_26_9"]
            df["macdhist"] = macd["MACDh_12_26_9"]

        df["ema_fast"] = ta.ema(df["close"], length=self.ema_fast.value)
        df["ema_slow"] = ta.ema(df["close"], length=self.ema_slow.value)
        df["ema_cross"] = (df["ema_fast"] > df["ema_slow"]).astype(int)

        df["session"] = self.get_session(df["date"])

        return df

    def populate_buy_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["buy"] = 0

        cond_rsi = self.rsi_enabled.value & (df["rsi"] < self.rsi_buy.value)
        cond_macd = self.macd_enabled.value & (df["macd"] > df["macdsignal"]) & (df["macdhist"] > 0)
        cond_ema = df["ema_cross"] == 1
        cond_session = df["session"].isin(["LONDON_OPEN_KZ", "LONDON_NY_KZ", "NY_CLOSE_KZ"])

        buy_cond = cond_rsi & cond_macd & cond_ema & cond_session

        if self.use_sentiment.value:
            from clawforge.integrations.deepseek import get_sentiment_score
            sentiment = get_sentiment_score(metadata["pair"])
            # Keep buy_cond as a Series by combining sentiment check into the mask
            cond_sentiment = sentiment >= self.sentiment_threshold.value
            buy_cond = buy_cond & cond_sentiment

        df.loc[buy_cond, "buy"] = 1
        return df

    def populate_sell_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["sell"] = 0

        cond_rsi = self.rsi_enabled.value & (df["rsi"] > self.rsi_sell.value)
        cond_macd = self.macd_enabled.value & (df["macd"] < df["macdsignal"]) & (df["macdhist"] < 0)
        cond_ema = df["ema_cross"] == 0

        sell_cond = cond_rsi | cond_macd | cond_ema
        df.loc[sell_cond, "sell"] = 1
        return df

    @staticmethod
    def get_session(date_series: pd.Series) -> pd.Series:
        """Map UTC hour to crypto trading session + ICT kill zones.

        Kill zones (highest probability entries):
          LONDON_OPEN_KZ  : 07:00-09:00 UTC
          LONDON_NY_KZ    : 13:00-16:00 UTC (highest volume)
          NY_CLOSE_KZ     : 20:00-22:00 UTC (reversals)

        Regular sessions:
          ASIA            : 00:00-07:00 UTC (range, low volatility)
          LONDON          : 09:00-13:00 UTC
          NY              : 16:00-20:00 UTC

        Dead zone (no trades):
          DEAD            : 22:00-00:00 UTC
        """
        def _session(ts):
            hour = ts.hour
            minute = ts.minute
            # Convert to float hour for precise boundary checks
            h = hour + minute / 60.0

            # ── Kill Zones (highest priority) ──
            if 7.0 <= h < 9.0:
                return "LONDON_OPEN_KZ"   # Kill zone 1
            if 13.0 <= h < 16.0:
                return "LONDON_NY_KZ"     # Kill zone 2 — best setups
            if 20.0 <= h < 22.0:
                return "NY_CLOSE_KZ"      # Kill zone 3 — reversals

            # ── Regular Sessions ──
            if 0.0 <= h < 7.0:
                return "ASIA"             # Range, wait for London
            if 9.0 <= h < 13.0:
                return "LONDON"           # London mid-session
            if 16.0 <= h < 20.0:
                return "NY"              # NY mid-session

            # ── Dead Zone ──
            return "DEAD"               # 22:00-00:00 — no trades
        return date_series.apply(_session)

    @staticmethod
    def hyperopt_loss_function(results_df: pd.DataFrame, trade_count: int, min_date: datetime,
                               max_date: datetime, processed: dict, *args, **kwargs) -> float:
        """Optimize for Risk/Reward Ratio ≥ 2.0."""
        if trade_count == 0:
            return 1000000

        wins = results_df[results_df["profit_abs"] > 0]
        losses = results_df[results_df["profit_abs"] < 0]

        if len(wins) == 0 or len(losses) == 0:
            return 1000000

        avg_win = wins["profit_abs"].mean()
        avg_loss = abs(losses["profit_abs"].mean())
        rrr = avg_win / avg_loss if avg_loss > 0 else 0

        return max(0, 2.0 - rrr) * 1000 + max(0, trade_count - 100) * 0.1
