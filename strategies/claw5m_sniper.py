"""
Claw5MSniper — MTF (Multi-Timeframe) Surgical Scalper
1H trend filter + 4H macro bias + 5M entry + 1M timing
Dynamic leverage based on trend strength
Volume confirmation on entry
Session × Trend interaction matrix
"""

from datetime import datetime, timezone, timedelta
import pandas as pd
import pandas_ta as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter
from freqtrade.persistence import Trade
from typing import Optional, Tuple


class Claw5MSniper(IStrategy):
    """5-minute sniper with institutional risk management + MTF confirmation."""

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 100  # need 1H/4H data too

    # Allow external API to force entries
    force_entry = True
    use_exit_signal = False
    min_hold_minutes = 2

    # ── Risk Management ──
    max_open_trades = 3
    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.01
    trailing_stop_positive_offset = 0.10
    trailing_only_offset_is_reached = True
    minimal_roi = {"0": 0.10}

    # Use custom leverage() method
    use_custom_leverage = True

    # ── MTF Filter Controls ──
    use_1h_filter = BooleanParameter(default=True, space="buy")
    use_4h_filter = BooleanParameter(default=True, space="buy")
    use_volume_filter = BooleanParameter(default=True, space="buy")
    volume_multiplier = DecimalParameter(1.2, 2.0, default=1.3, space="buy")

    # 1H Trend Strength Thresholds
    min_adx = IntParameter(15, 35, default=25, space="buy")
    min_trend_strength = DecimalParameter(0.4, 0.8, default=0.6, space="buy")

    # Session × Trend Interaction
    offsession_reduce_size = BooleanParameter(default=True, space="buy")
    weekend_filter = BooleanParameter(default=True, space="buy")

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

    # ── StepFun Sentiment ──
    use_sentiment = BooleanParameter(default=False, space="buy")
    sentiment_threshold = DecimalParameter(0.6, 0.9, default=0.75, space="buy")

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()

        # 5M indicators
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
        # Volume spike baseline
        df["volume_ma20"] = df["volume"].rolling(20).mean()
        df["session"] = self.get_session(df["date"])

        # Cache 1H and 4H data for buy logic (last row only)
        pair = metadata["pair"]
        df_1h = self.dp.get_pair_dataframe(pair, "1h")
        df_4h = self.dp.get_pair_dataframe(pair, "4h")

        self.last_1h = None
        self.last_4h = None
        if df_1h is not None and len(df_1h) >= 50:
            df_1h = df_1h.copy()
            df_1h["ema20"] = ta.ema(df_1h["close"], 20)
            df_1h["ema50"] = ta.ema(df_1h["close"], 50)
            df_1h["ema200"] = ta.ema(df_1h["close"], 200)
            macd_1h = ta.macd(df_1h["close"], 12, 26, 9)
            df_1h["macd"] = macd_1h["MACD_12_26_9"]
            df_1h["macdsignal"] = macd_1h["MACDs_12_26_9"]
            df_1h["macdhist"] = macd_1h["MACDh_12_26_9"]
            df_1h["adx"] = ta.adx(df_1h["high"], df_1h["low"], df_1h["close"], 14)["ADX_14"]
            self.last_1h = df_1h.iloc[-1]

        if df_4h is not None and len(df_4h) >= 50:
            df_4h = df_4h.copy()
            df_4h["ema200"] = ta.ema(df_4h["close"], 200)
            self.last_4h = df_4h.iloc[-1]

        return df

    def get_1h_trend_strength(self) -> Tuple[int, float, int]:
        """
        Return (bias: -1/0/1, strength: 0–1, confidence: 0–100).
        Bias: 1=bullish, -1=bearish, 0=neutral
        Strength: composite score (ADX + MACD + EMA structure)
        """
        if self.last_1h is None:
            return 0, 0.0, 0

        last = self.last_1h

        # EMA stack structure
        ema_bull = (last['close'] > last.get('ema20', 0) > last.get('ema50', 0) > last.get('ema200', 0))
        ema_bear = (last['close'] < last.get('ema20', 999999) < last.get('ema50', 999999) < last.get('ema200', 999999))

        # ADX strength (normalized 0–1, cap at 50)
        adx = last.get('adx', 0)
        adx_score = min(adx / 50.0, 1.0) * 0.4

        # MACD histogram momentum (normalized by price, scaled)
        macd_hist = abs(last.get('macdhist', 0))
        macd_norm = min(macd_hist / last['close'] * 10000, 1.0) * 0.3

        # EMA structure bonus
        struct_score = (0.3 if ema_bull or ema_bear else 0.0)

        strength = adx_score + macd_norm + struct_score

        # Bias determination
        if ema_bull and adx >= self.min_adx.value:
            bias = 1
        elif ema_bear and adx >= self.min_adx.value:
            bias = -1
        else:
            bias = 0

        confidence = int(strength * 100)
        return bias, strength, confidence

    def get_macro_bias(self) -> int:
        """4H macro bias: 1=bullish, -1=bearish, 0=neutral."""
        if not self.use_4h_filter.value or self.last_4h is None:
            return 0
        last = self.last_4h
        # Price relative to EMA200 on 4H
        if last['close'] > last.get('ema200', last['ema50']):
            return 1
        elif last['close'] < last.get('ema200', last['ema50']):
            return -1
        return 0

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["buy"] = 0

        # 5M entry conditions
        cond_rsi = self.rsi_enabled.value & (df["rsi"] < self.rsi_buy.value)
        cond_macd = self.macd_enabled.value & (df["macd"] > df["macdsignal"]) & (df["macdhist"] > 0)
        cond_ema = df["ema_cross"] == 1
        cond_session = df["session"].isin(["NY", "TOKYO", "LONDON"])

        # Volume confirmation (if enabled)
        cond_volume = pd.Series([True] * len(df), index=df.index)
        if self.use_volume_filter.value:
            vol_ratio = df["volume"] / df["volume_ma20"]
            cond_volume = vol_ratio > self.volume_multiplier.value

        # Base 5M setup
        base_cond = cond_rsi & cond_macd & cond_ema & cond_session & cond_volume

        # MTF filtering
        trend_bias, trend_strength, confidence = self.get_1h_trend_strength()
        macro_bias = self.get_macro_bias()

        # Session × Trend interaction
        current_session = df["session"].iloc[-1] if len(df) > 0 else "OTHER"
        offsession_weak = (current_session == "OTHER") and (trend_strength < 0.7)

        # Decision gates
        allow_trade = False

        if self.use_1h_filter.value and trend_bias == 0:
            allow_trade = False  # 1H neutral → skip
        elif self.use_4h_filter.value and macro_bias != 0 and macro_bias != trend_bias:
            allow_trade = False  # 4H contradicts 1H → skip
        elif offsession_weak and self.offsession_reduce_size.value:
            allow_trade = False  # off-session weak trend → skip
        else:
            allow_trade = True

        if allow_trade:
            df.loc[base_cond, "buy"] = 1

        # Store trend_strength for dynamic sizing/leverage
        self.latest_trend_strength = trend_strength
        self.latest_trend_bias = trend_bias

        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
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
        """Map UTC hour to trading session."""
        def _session(ts):
            hour = ts.hour
            if 0 <= hour < 8:
                return "NY"
            elif 8 <= hour < 16:
                return "TOKYO"
            elif 16 <= hour < 24:
                return "LONDON"
            return "OTHER"
        return date_series.apply(_session)

    def custom_exit(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        hold_time = current_time - trade.open_date
        if hold_time < timedelta(minutes=self.min_hold_minutes):
            return None
        dataframe = self.dp.get_pair_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 1:
            return None
        latest = dataframe.iloc[-1]
        sell = False
        if self.rsi_enabled.value and latest.get('rsi', 0) > self.rsi_sell.value:
            sell = True
        if self.macd_enabled.value and (latest.get('macd', 0) < latest.get('macdsignal', 0)) and (latest.get('macdhist', 0) < 0):
            sell = True
        if latest.get('ema_cross', 1) == 0:
            sell = True
        if sell:
            return "TA exit signal"
        return None

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """Three-phase stoploss:
        - <10% profit: fixed -5% SL
        - 10%–20% profit: move to breakeven
        - >=20% profit: let trailing take over (trail offset 1%, activation 20%)
        """
        if current_profit >= 0.20:
            return -0.25  # far away; trailing handles it
        elif current_profit >= 0.10:
            return (trade.open_rate - current_rate) / current_rate
        return self.stoploss  # -0.05

    @staticmethod
    def hyperopt_loss_function(results_df: pd.DataFrame, trade_count: int, min_date: datetime,
                               max_date: datetime, processed: dict, *args, **kwargs) -> float:
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

    # ── Dynamic Leverage ──
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        """
        Dynamic leverage based on 1H trend strength.
        Base: 50x (from user state)
        Strong (strength ≥0.7): 1.5× → 75x
        Moderate (0.4–0.7): 1.0× → 50x
        Weak (<0.4): 0.5× → 25x
        """
        base = 50.0
        strength = getattr(self, 'latest_trend_strength', 0.5)
        if strength >= 0.7:
            return min(base * 1.5, 100)
        elif strength >= 0.4:
            return base
        else:
            return max(base * 0.5, 20)
