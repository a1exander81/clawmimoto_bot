"""
Claw5MHybrid — MTF Surgical Scalper (EMA+HA + Volume + 1H/4H Filter)
Conservative trend-following with multi-timeframe confirmation.
"""

from datetime import datetime, timezone, timedelta
import pandas as pd
import pandas_ta as ta
from freqtrade.strategy import IStrategy, IntParameter, BooleanParameter, DecimalParameter
from freqtrade.persistence import Trade
from typing import Optional, Tuple


class Claw5MHybrid(IStrategy):
    """5-minute hybrid scalper: EMA cloud + HA + volume spike + MTF confirmation."""

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 150  # need 1H/4H data

    force_entry = True
    use_exit_signal = False
    min_hold_minutes = 2

    # ── Risk Management ──
    max_open_trades = 3
    stoploss = -0.25
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.5
    trailing_only_offset_is_reached = True
    minimal_roi = {"0": 1.0}

    # ── MTF Filter Controls ──
    use_1h_filter = BooleanParameter(default=True, space="buy")
    use_4h_filter = BooleanParameter(default=True, space="buy")
    use_volume_filter = BooleanParameter(default=True, space="buy")
    volume_multiplier = DecimalParameter(1.2, 2.0, default=1.3, space="buy")

    min_adx = IntParameter(15, 35, default=25, space="buy")
    min_trend_strength = DecimalParameter(0.4, 0.8, default=0.6, space="buy")

    offsession_reduce_size = BooleanParameter(default=True, space="buy")
    weekend_filter = BooleanParameter(default=True, space="buy")

    # ── Position & Order Types ──
    position_mode = "one-way"
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "stoploss_on_exchange_interval": 60,
    }

    # ── Indicators (hyperoptable) ──
    use_ema8 = BooleanParameter(default=True, space="buy")
    use_ema20 = BooleanParameter(default=True, space="buy")
    use_ema50 = BooleanParameter(default=True, space="buy")
    use_volume_spike = BooleanParameter(default=True, space="buy")
    volume_multiplier_pct = IntParameter(15, 30, default=20, space="buy")
    use_atr_filter = BooleanParameter(default=True, space="buy")
    min_atr_pct = DecimalParameter(0.0005, 0.005, default=0.001, space="buy")

    use_custom_stoploss = True

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()

        # EMA cloud
        if self.use_ema8.value:
            df["ema8"] = ta.ema(df["close"], length=8)
        if self.use_ema20.value:
            df["ema20"] = ta.ema(df["close"], length=20)
        if self.use_ema50.value:
            df["ema50"] = ta.ema(df["close"], length=50)

        # Heikin-Ashi
        ha = ta.ha(df["open"], df["high"], df["low"], df["close"])
        df["ha_open"] = ha["HA_open"]
        df["ha_high"] = ha["HA_high"]
        df["ha_low"] = ha["HA_low"]
        df["ha_close"] = ha["HA_close"]

        # Volume
        df["volume_ma20"] = df["volume"].rolling(20).mean()
        df["volume_spike"] = df["volume"] > df["volume_ma20"] * (1 + self.volume_multiplier_pct.value / 100)

        # ATR volatility filter
        if self.use_atr_filter.value:
            atr = ta.atr(df["high"], df["low"], df["close"], 14)
            df["atr_pct"] = atr / df["close"]
        else:
            df["atr_pct"] = 0

        df["session"] = self.get_session(df["date"])

        # Cache 1H and 4H
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
        if self.last_1h is None:
            return 0, 0.0, 0
        last = self.last_1h
        ema_bull = (last['close'] > last.get('ema20', 0) > last.get('ema50', 0) > last.get('ema200', 0))
        ema_bear = (last['close'] < last.get('ema20', 999999) < last.get('ema50', 999999) < last.get('ema200', 999999))
        adx = last.get('adx', 0)
        adx_score = min(adx / 50.0, 1.0) * 0.4
        macd_hist = abs(last.get('macdhist', 0))
        macd_norm = min(macd_hist / last['close'] * 10000, 1.0) * 0.3
        struct_score = 0.3 if ema_bull or ema_bear else 0.0
        strength = adx_score + macd_norm + struct_score
        if ema_bull and adx >= self.min_adx.value:
            bias = 1
        elif ema_bear and adx >= self.min_adx.value:
            bias = -1
        else:
            bias = 0
        confidence = int(strength * 100)
        return bias, strength, confidence

    def get_macro_bias(self) -> int:
        if not self.use_4h_filter.value or self.last_4h is None:
            return 0
        last = self.last_4h
        if last['close'] > last.get('ema200', last['ema50']):
            return 1
        elif last['close'] < last.get('ema200', last['ema50']):
            return -1
        return 0

    def populate_buy_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["buy"] = 0

        # 5M entry conditions
        cond_ema = (df["ema8"] > df["ema20"]) & (df["ema20"] > df["ema50"])
        cond_ha = (df["ha_close"] > df["ema8"]) & (df["ha_open"] < df["ha_close"])
        cond_volume = self.use_volume_spike.value & df["volume_spike"]
        cond_session = df["session"].isin(["NY", "TOKYO", "LONDON"])
        cond_atr = True
        if self.use_atr_filter.value:
            cond_atr = df["atr_pct"] >= self.min_atr_pct.value

        base_cond = cond_ema & cond_ha & cond_volume & cond_session & cond_atr

        # MTF filtering
        trend_bias, trend_strength, confidence = self.get_1h_trend_strength()
        macro_bias = self.get_macro_bias()

        current_session = df["session"].iloc[-1] if len(df) > 0 else "OTHER"
        offsession_weak = (current_session == "OTHER") and (trend_strength < 0.7)

        allow_trade = False
        if self.use_1h_filter.value and trend_bias == 0:
            allow_trade = False
        elif self.use_4h_filter.value and macro_bias != 0 and macro_bias != trend_bias:
            allow_trade = False
        elif offsession_weak and self.offsession_reduce_size.value:
            allow_trade = False
        else:
            allow_trade = True

        if allow_trade:
            df.loc[base_cond, "buy"] = 1

        self.latest_trend_strength = trend_strength
        self.latest_trend_bias = trend_bias
        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["exit_long"] = 0
        df["exit_short"] = 0
        exit_long = (df["ema8"] < df["ema20"]) | (df["ha_close"] < df["ema8"])
        exit_short = (df["ema8"] > df["ema20"]) | (df["ha_close"] > df["ema8"])
        df.loc[exit_long, "exit_long"] = 1
        df.loc[exit_short, "exit_short"] = 1
        return df

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        if current_profit >= 0.50:
            return -0.25
        elif current_profit >= 0.30:
            return (trade.open_rate - current_rate) / current_rate
        return self.stoploss

    def custom_exit(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        hold_time = current_time - trade.open_date
        if hold_time < timedelta(minutes=self.min_hold_minutes):
            return None
        dataframe = self.dp.get_pair_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 1:
            return None
        latest = dataframe.iloc[-1]
        exit_long = (latest.get('ema8', 0) < latest.get('ema20', 0)) or (latest.get('ha_close', 0) < latest.get('ema8', 0))
        if exit_long and not trade.is_short:
            return "TA exit: EMA/HA reversal"
        exit_short = (latest.get('ema8', 0) > latest.get('ema20', 0)) or (latest.get('ha_close', 0) > latest.get('ema8', 0))
        if exit_short and trade.is_short:
            return "TA exit: EMA/HA reversal"
        return None

    @staticmethod
    def get_session(date_series: pd.Series) -> pd.Series:
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

    @staticmethod
    def calculate_confidence(df_row) -> int:
        base = 75
        if df_row.get('volume_spike', False):
            base += 5
        if df_row.get('atr_pct', 0) > 0.001:
            base += 5
        return min(base, 95)

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, **kwargs) -> float:
        base = 50.0
        strength = getattr(self, 'latest_trend_strength', 0.5)
        if strength >= 0.7:
            return min(base * 1.5, 100)
        elif strength >= 0.4:
            return base
        else:
            return max(base * 0.5, 20)

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
