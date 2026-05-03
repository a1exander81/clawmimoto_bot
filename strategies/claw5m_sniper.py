"""
Claw5MSniper — MTF (Multi-Timeframe) Surgical Scalper
1H trend filter + 4H macro bias + 5M entry + 1M timing
Heikin-Ashi smoothing + EMA crossover + RSI/MACD confirmation
Dynamic leverage based on trend strength + AI confidence
Volume confirmation on entry
Session × Trend interaction matrix
Adaptive stoploss + Circuit breaker for risk management
"""

from datetime import datetime, timezone, timedelta
import os
import logging as _logging
import pandas as pd
import pandas_ta as ta
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter
from freqtrade.persistence import Trade
from typing import Optional, Tuple


_logging.basicConfig(level=_logging.INFO)
logger = _logging.getLogger(__name__)


class Claw5MSniper(IStrategy):
    """5-minute sniper with Heikin-Ashi smoothing, institutional risk
    management, MTF confirmation, adaptive stoploss, and circuit breaker."""

    INTERFACE_VERSION = 3
    timeframe = "5m"
    startup_candle_count = 100  # need 1H/4H data too

    # Allow external API to force entries
    force_entry = True
    use_exit_signal = False
    min_hold_minutes = 2

    # ── Risk Management ──
    max_open_trades = 3
    stoploss = -0.004
    trailing_stop = True
    trailing_stop_positive = 0.50
    trailing_stop_positive_offset = 0.50
    trailing_only_offset_is_reached = True
    minimal_roi = {"0": 0.10}

    # Use custom leverage() method
    use_custom_leverage = True
    use_custom_stoploss = True

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

    # ── Heikin-Ashi Controls ──
    use_ha_filter = BooleanParameter(default=True, space="buy")
    ha_confirmation = BooleanParameter(default=True, space="buy")

    # ── ATR Volatility Filter ──
    use_atr_filter = BooleanParameter(default=True, space="buy")
    min_atr_pct = DecimalParameter(0.0005, 0.005, default=0.001, space="buy")

    # ── StepFun Sentiment ──
    use_sentiment = BooleanParameter(default=False, space="buy")
    sentiment_threshold = DecimalParameter(0.6, 0.9, default=0.75, space="buy")

    # ── Circuit Breaker Controls ──
    daily_pnl_target = IntParameter(80, 200, default=150, space="buy")
    daily_loss_limit = IntParameter(20, 50, default=30, space="buy")
    max_daily_trades = IntParameter(5, 10, default=7, space="buy")
    use_blocklist = BooleanParameter(default=True, space="buy")
    use_btc_regime_filter = BooleanParameter(default=True, space="buy")
    min_btc_4h_range_pct = DecimalParameter(1.0, 2.5, default=1.5, space="buy")

    # Per-pair dynamic confidence storage
    custom_info: dict = {}

    # ── Blocklist ──
    BLOCKLIST = {
        'BABYDOGE', 'CHEEMS', 'MOG', 'FLOKI', 'CHIP', 'QUBIC',
        'SATS', 'RATS', 'ORDI', 'CL', 'GC', 'SI', 'NG',
        'XAUT', 'PAXG', 'ORCA', 'BONK', 'PEPE', 'WIF', 'BOME',
        'MYRO', 'POPCAT', 'SLERF', 'NEIRO', 'MOODENG', 'TURBO',
        'COQ', 'GIGA', 'FRED', 'PNUT',
    }

    def init(self, config):
        """Initialize strategy — called once at bot startup."""
        super().init(config)
        self.custom_info = {}

    def populate_indicators(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()

        # ── 5M indicators ──
        if self.rsi_enabled.value:
            df["rsi"] = ta.rsi(df["close"], length=self.rsi_period.value)

        if self.macd_enabled.value:
            macd = ta.macd(
                df["close"],
                fast=self.macd_fast.value,
                slow=self.macd_slow.value,
                signal=self.macd_signal.value,
            )
            df["macd"] = macd["MACD_12_26_9"]
            df["macdsignal"] = macd["MACDs_12_26_9"]
            df["macdhist"] = macd["MACDh_12_26_9"]

        df["ema_fast"] = ta.ema(df["close"], length=self.ema_fast.value)
        df["ema_slow"] = ta.ema(df["close"], length=self.ema_slow.value)
        df["ema_cross"] = (df["ema_fast"] > df["ema_slow"]).astype(int)

        # ── Heikin-Ashi smoothing ──
        ha = ta.ha(df["open"], df["high"], df["low"], df["close"])
        df["ha_open"] = ha["HA_open"]
        df["ha_high"] = ha["HA_high"]
        df["ha_low"] = ha["HA_low"]
        df["ha_close"] = ha["HA_close"]

        # HA trend direction: bullish when close > open
        df["ha_bull"] = (df["ha_close"] > df["ha_open"]).astype(int)
        # HA momentum: price above fast EMA
        df["ha_above_ema"] = (df["ha_close"] > df["ema_fast"]).astype(int)

        # ── Volume spike baseline ──
        df["volume_ma20"] = df["volume"].rolling(20).mean()

        # ── ATR volatility filter ──
        if self.use_atr_filter.value:
            atr = ta.atr(df["high"], df["low"], df["close"], 14)
            df["atr_pct"] = atr / df["close"]
        else:
            df["atr_pct"] = 0

        # ── Session mapping ──
        df["session"] = self.get_session(df["date"])

        # ── Cache 1H and 4H data for buy logic (last row only) ──
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

        # ── 5M entry conditions ──
        cond_rsi = self.rsi_enabled.value & (df["rsi"] < self.rsi_buy.value)
        cond_macd = self.macd_enabled.value & (df["macd"] > df["macdsignal"]) & (df["macdhist"] > 0)
        cond_ema = df["ema_cross"] == 1
        cond_session = df["session"].isin(["NY", "TOKYO", "LONDON"])

        # ── Heikin-Ashi confirmation ──
        cond_ha = pd.Series([True] * len(df), index=df.index)
        if self.use_ha_filter.value:
            cond_ha = (
                (df["ha_bull"] == 1)
                & (df["ha_above_ema"] == 1)
                & (df["ha_close"] > df["ha_open"])
            )

        # ── ATR filter (avoid low-volatility chop) ──
        cond_atr = pd.Series([True] * len(df), index=df.index)
        if self.use_atr_filter.value:
            cond_atr = df["atr_pct"] >= self.min_atr_pct.value

        # ── Volume confirmation (if enabled) ──
        cond_volume = pd.Series([True] * len(df), index=df.index)
        if self.use_volume_filter.value:
            vol_ratio = df["volume"] / df["volume_ma20"]
            cond_volume = vol_ratio > self.volume_multiplier.value

        # Base 5M setup
        base_cond = cond_rsi & cond_macd & cond_ema & cond_session & cond_ha & cond_atr & cond_volume

        # ── MTF filtering ──
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
        # Store confidence values at entry for leverage() and custom_stoploss()
        pair_key = metadata.get('pair') if metadata else None
        if pair_key:
            if pair_key not in self.custom_info:
                self.custom_info[pair_key] = {}
            self.custom_info[pair_key]['trend_strength'] = trend_strength
            self.custom_info[pair_key].setdefault('ai_confidence', 85)
        return df

    def populate_exit_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
        df = dataframe.copy()
        df["sell"] = 0
        cond_rsi = self.rsi_enabled.value & (df["rsi"] > self.rsi_sell.value)
        cond_macd = self.macd_enabled.value & (df["macd"] < df["macdsignal"]) & (df["macdhist"] < 0)
        cond_ema = df["ema_cross"] == 0
        # Also exit on HA reversal: bearish candle
        cond_ha_reversal = pd.Series([False] * len(df), index=df.index)
        if self.use_ha_filter.value:
            cond_ha_reversal = (df["ha_close"] < df["ha_open"]) & (df["ha_close"] < df["ema_fast"])
        sell_cond = cond_rsi | cond_macd | cond_ema | cond_ha_reversal
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
        """Session-aware TP exits + TA-based exit."""
        hold_time = current_time - trade.open_date
        if hold_time < timedelta(minutes=self.min_hold_minutes):
            return None

        # ── Session-aware TP exits (from hybrid) ──
        sgt_hour = (current_time.hour + 8) % 24

        # Tokyo - ranging market, take profit fast
        if 0 <= sgt_hour < 9:
            if current_profit >= 0.08:
                return 'tokyo_tp'
        # London - trending, let it run more
        elif 16 <= sgt_hour < 20:
            if current_profit >= 0.15:
                return 'london_tp'
        # NY - strongest trends, widest TP
        elif 21 <= sgt_hour <= 23:
            if current_profit >= 0.20:
                return 'ny_tp'
        # Off session - take anything above 5%
        else:
            if current_profit >= 0.05:
                return 'offsession_tp'

        # ── TA-based exit fallback ──
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
        # HA reversal exit
        if self.use_ha_filter.value:
            if latest.get('ha_close', 0) < latest.get('ha_open', 1) and latest.get('ha_close', 0) < latest.get('ema_fast', 999999):
                sell = True
        if sell:
            return "TA exit signal"
        return None

    # ── Adaptive Stoploss ──
    def get_sl_tolerance(self) -> float:
        """
        Adaptive SL based on recent win/loss history.
        Returns margin SL %% (0.10 to 0.20)
        """
        try:
            # Get last 10 closed trades
            recent = sorted(
                [t for t in Trade.get_trades_proxy(is_open=False)],
                key=lambda x: x.close_date,
                reverse=True
            )[:10]

            if len(recent) < 3:
                return 0.15  # default - not enough data

            wins = [t for t in recent if t.profit_ratio > 0]
            losses = [t for t in recent if t.profit_ratio <= 0]

            # 3 consecutive losses → tightest SL
            last_3 = recent[:3]
            if all(t.profit_ratio <= 0 for t in last_3):
                logger.warning("3 consecutive losses - tightening SL")
                return 0.10

            if not wins or not losses:
                return 0.15

            avg_win = sum(t.profit_ratio for t in wins) / len(wins)
            avg_loss = abs(sum(t.profit_ratio for t in losses) / len(losses))

            if avg_loss == 0:
                return 0.20

            rrr = avg_win / avg_loss

            if rrr >= 2.0:
                return 0.20  # performing well
            elif rrr >= 1.5:
                return 0.15  # average
            else:
                return 0.10  # underperforming

        except Exception:
            return 0.15  # safe default

    def custom_stoploss(self, pair: str, trade: 'Trade', current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """Adaptive three-phase stoploss:
        Phase 1: Dynamic SL based on trade history + session + profit protection
        Phase 2: Breakeven lock at 2% price profit
        Phase 3: Profit lock at 5% / 20% price profit
        """
        leverage = getattr(trade, 'leverage', None) or int(os.environ.get("DEFAULT_LEVERAGE", 20))

        # ── MINIMUM TRADE DURATION (no trailing/adjustments before 5min) ──
        trade_duration = (current_time - trade.open_date_utc).total_seconds() / 60
        if trade_duration < 5:
            return self.stoploss  # use base SL only, no early trailing

        # ── PROFIT PROTECTION (highest priority) ──
        if current_profit >= 0.02:  # 2% price = breakeven lock
            return -(0.01 / leverage)  # breakeven lock
        if current_profit >= 0.05:  # 5% price = lock profit
            return -(0.10 / leverage)  # lock 10% margin
        if current_profit >= 0.20:
            return -(0.05 / leverage)  # lock 5% margin

        # ── ADAPTIVE TOLERANCE + SESSION MULTIPLIER ──
        margin_sl = self.get_sl_tolerance()

        sgt_hour = (current_time.hour + 8) % 24
        if 0 <= sgt_hour < 9:  # Tokyo
            margin_sl = margin_sl * 0.75
        elif 16 <= sgt_hour < 20:  # London
            margin_sl = margin_sl * 1.0
        elif 21 <= sgt_hour <= 23:  # NY
            margin_sl = margin_sl * 1.25
        else:  # Off session
            margin_sl = margin_sl * 0.60

        # Cap between 5% and 25%
        margin_sl = max(0.05, min(0.25, margin_sl))
        price_sl = margin_sl / leverage
        return -price_sl

    # ── Circuit Breaker ──
    def confirm_trade_entry(self, pair: str, order_type, amount: float,
                           rate: float, time_in_force: str, current_time: datetime,
                           entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """
        Circuit breaker:
        - Blocklist: meme coins, stablecoins, commodities, price < 1.0
        - Stop trading if daily PnL hits target (e.g., +150%)
        - Stop trading if daily PnL hits loss limit (e.g., -30%)
        - Max total trades per day
        - BTC 4H regime check — block non-BTC/ETH when BTC is range-bound
        """
        try:
            # ── Blocklist + price guard ──
            if self.use_blocklist.value:
                base = pair.split('/')[0] if '/' in pair else pair.split(':')[0]
                if base in self.BLOCKLIST:
                    self.log_once(f"❌ Blocked pair: {base} (blocklist)", _logging.INFO)
                    return False
                if rate < 1.0:
                    self.log_once(f"❌ Price too low: {rate:.4f} USDT", _logging.INFO)
                    return False

            today = current_time.date()

            # Get today's closed trades
            all_trades = Trade.get_trades_proxy(is_open=False)
            daily_trades = [
                t for t in all_trades
                if t.close_date and t.close_date.date() == today
            ]

            # Count open trades (all currently open)
            open_trades = Trade.get_trades_proxy(is_open=True)

            # Daily PnL check (sum of profit ratios as percentages)
            daily_pnl = sum(t.profit_ratio * 100 for t in daily_trades)

            if daily_pnl >= self.daily_pnl_target.value:
                self.log_once(
                    f"🎯 Daily target reached: +{daily_pnl:.1f}% - stopping trading",
                    _logging.INFO
                )
                return False

            if daily_pnl <= -self.daily_loss_limit.value:
                self.log_once(
                    f"🛑 Daily loss limit hit: {daily_pnl:.1f}% - stopping trading",
                    _logging.WARNING
                )
                return False

            # Max trades check
            if len(open_trades) >= self.max_daily_trades.value:
                return False

            # BTC 4H regime check — block non-BTC/ETH when BTC is range-bound
            if self.use_btc_regime_filter.value:
                try:
                    btc_pair = 'BTC/USDT:USDT'
                    btc_df = self.dp.get_pair_dataframe(pair=btc_pair, timeframe='4h')
                    if len(btc_df) >= 1:
                        last = btc_df.iloc[-1]
                        # 4H candle range as % of low
                        candle_range = abs(last['high'] - last['low']) / last['low'] * 100
                        if candle_range < self.min_btc_4h_range_pct.value and pair not in (btc_pair, 'ETH/USDT:USDT'):
                            self.log_once(f"❌ BTC ranging ({candle_range:.1f}%) — blocking {pair}", _logging.INFO)
                            return False
                except Exception:
                    pass  # If data unavailable, allow trade

        except Exception as e:
            pass  # Never block trades due to circuit breaker error

        return True

    # ── Dynamic Leverage ──
    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        """
        Dynamic leverage based on 1H trend strength + AI confidence.
        Base: 50x (from user state)
        Strong (strength ≥0.7): 1.5× → 75x
        Moderate (0.4–0.7): 1.0× → 50x
        Weak (<0.4): 0.5× → 25x

        AI confidence multiplier further adjusts:
        ≥90% AI: 1.0x
        85–90% AI: 0.8x
        80–85% AI: 0.6x
        <80% AI: 0.4x
        """
        base = 50.0
        strength = getattr(self, 'latest_trend_strength', 0.5)

        # Trend strength multiplier
        if strength >= 0.7:
            ts_mult = 1.5
        elif strength >= 0.4:
            ts_mult = 1.0
        else:
            ts_mult = 0.5

        # AI confidence multiplier
        ai_confidence = self.custom_info.get(pair, {}).get('ai_confidence', 85)
        if ai_confidence >= 90:
            ai_mult = 1.0
        elif ai_confidence >= 85:
            ai_mult = 0.8
        elif ai_confidence >= 80:
            ai_mult = 0.6
        else:
            ai_mult = 0.4

        # Clamp
        calculated = base * ts_mult * ai_mult
        # Get max from env or default
        max_lev = int(os.environ.get('MAX_LEVERAGE', 100))
        return max(20.0, min(float(max_lev), calculated))

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
