"""
Claw5MHybrid - MTF Surgical Scalper (EMA+HA + Volume + 1H/4H Filter)
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
    stoploss = -0.02
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True
    minimal_roi = {
        "0": 0.20,
        "15": 0.15,
        "30": 0.10,
        "60": 0.05,
        "120": 0.02,
    }

    # Use custom leverage() method
    use_custom_leverage = True

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

    # Per-pair dynamic confidence storage (set in init)
    custom_info: dict = {}

    def init(self, config):
        """Initialize strategy - called once at bot startup."""
        super().init(config)
        self.custom_info = {}

    def leverage(self, pair: str, current_time: datetime, current_rate: float,
                 proposed_leverage: float, max_leverage: float, entry_tag: str | None, side: str, **kwargs) -> float:
        """Dynamic leverage based on dual confidence systems:
        - AI confidence from StepFun (80-90%)
        - Internal trend strength from MTF filter (0.0-1.0)
        """
        import os

        # Retrieve stored confidence values from custom_info (populated by populate_indicators)
        ai_confidence = self.custom_info.get(pair, {}).get('ai_confidence', 85)
        trend_strength = self.custom_info.get(pair, {}).get('trend_strength', 0.6)

        # AI confidence multiplier
        if ai_confidence >= 90:
            ai_mult = 1.0
        elif ai_confidence >= 85:
            ai_mult = 0.8
        elif ai_confidence >= 80:
            ai_mult = 0.6
        else:
            ai_mult = 0.4

        # Trend strength multiplier
        if trend_strength >= 0.8:
            ts_mult = 1.0
        elif trend_strength >= 0.6:
            ts_mult = 0.7
        elif trend_strength >= 0.4:
            ts_mult = 0.5
        else:
            ts_mult = 0.3

        # Base leverage from env
        base_lev = int(os.getenv('DEFAULT_LEVERAGE', 50))
        max_lev = int(os.getenv('MAX_LEVERAGE', 100))

        # Calculate final leverage
        calculated = round(base_lev * ai_mult * ts_mult)
        final_leverage = max(5, min(max_lev, calculated))

        return float(final_leverage)

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

    def populate_entry_trend(self, dataframe: pd.DataFrame, metadata: dict) -> pd.DataFrame:
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

        # FIX 3: 1H EMA50 trend filter — only LONG above EMA50, SHORT below
        try:
            pair_1h = metadata.get('pair')
            if pair_1h:
                df_1h = self.dp.get_pair_dataframe(pair=pair_1h, timeframe='1h')
                if len(df_1h) > 0:
                    ema50_1h = df_1h['close'].ewm(span=50, adjust=False).mean().iloc[-1]
                    current_close = dataframe['close'].iloc[-1]
                    cond_ema50_1h = current_close >= ema50_1h
                    base_cond = base_cond & cond_ema50_1h
        except Exception:
            pass  # If 1H data unavailable, proceed without filter

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
        # Store confidence values at entry for leverage() and custom_stoploss()
        pair_key = metadata.get('pair') if metadata else None
        if pair_key:
            if pair_key not in self.custom_info:
                self.custom_info[pair_key] = {}
            self.custom_info[pair_key]['trend_strength'] = trend_strength
            # ai_confidence will be injected by UI via entry_tag or external; default 85
            self.custom_info[pair_key].setdefault('ai_confidence', 85)
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

    def get_sl_tolerance(self) -> float:
        """
        Adaptive SL based on recent win/loss history.
        Returns margin SL %% (0.10 to 0.20)
        """
        try:
            from freqtrade.persistence import Trade
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
        """
        Dynamic SL based on:
        1. Adaptive tolerance from recent trade history (get_sl_tolerance)
        2. Session multiplier (SGT timezone)
        3. Profit protection tiers
        """
        # Get actual leverage used for this trade
        leverage = getattr(trade, 'leverage', 50) or 50

        # ── MINIMUM TRADE DURATION (no trailing/adjustments before 5min) ──
        trade_duration = (current_time - trade.open_date_utc).total_seconds() / 60
        if trade_duration < 5:
            return self.stoploss  # use base SL only, no early trailing

        # ── PROFIT PROTECTION (highest priority) ──
        if current_profit >= 0.10:
            return -(0.01 / leverage)  # breakeven lock
        if current_profit >= 0.50:
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

    def confirm_trade_entry(self, pair: str, order_type, amount: float,
                           rate: float, time_in_force: str, current_time: datetime,
                           entry_tag: Optional[str], side: str, **kwargs) -> bool:
        """
        Circuit breaker:
        - Stop trading if daily PnL hits +150% (target reached)
        - Stop trading if daily PnL hits -30% (protect capital)
        - Max 7 total trades per day (3 session + 4 manual)
        - Blocklist: meme coins, stablecoins, commodities, price < 1.0
        """
        try:
            from freqtrade.persistence import Trade
            import logging as _logging
            _logging.basicConfig(level=_logging.INFO)
            logger = _logging.getLogger(__name__)

            # ── FIX 2: Extended blocklist + price guard ──
            BLOCKLIST = {
                'BABYDOGE','CHEEMS','MOG','FLOKI','CHIP','QUBIC',
                'SATS','RATS','ORDI','CL','GC','SI','NG','XAUT','PAXG'
            }
            base = pair.split('/')[0] if '/' in pair else pair.split(':')[0]
            if base in BLOCKLIST:
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

            if daily_pnl >= 150:
                self.log_once(
                    f"🎯 Daily target reached: +{daily_pnl:.1f}% - stopping trading",
                    _logging.INFO
                )
                return False

            if daily_pnl <= -30:
                self.log_once(
                    f"🛑 Daily loss limit hit: {daily_pnl:.1f}% - stopping trading",
                    _logging.WARNING
                )
                return False

            # Max trades check (7 total)
            if len(open_trades) >= 7:
                return False

            # FIX 4: BTC 4H regime check — block non-BTC/ETH when BTC is range-bound (<1.5% 4H candle)
            try:
                btc_pair = 'BTC/USDT:USDT'
                btc_df = self.dp.get_pair_dataframe(pair=btc_pair, timeframe='4h')
                if len(btc_df) >= 1:
                    last = btc_df.iloc[-1]
                    # 4H candle range as % of low
                    candle_range = abs(last['high'] - last['low']) / last['low'] * 100
                    if candle_range < 1.5 and pair not in (btc_pair, 'ETH/USDT:USDT'):
                        self.log_once(f"❌ BTC ranging ({candle_range:.1f}%) — blocking {pair}", _logging.INFO)
                        return False
            except Exception:
                pass  # If data unavailable, allow trade

        except Exception as e:
            pass  # Never block trades due to circuit breaker error

        return True

    def custom_exit(self, pair: str, trade: 'Trade', current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """
        Session-aware TP exits:
        - Tokyo (0-9 SGT): exit at 8% profit
        - London (16-20 SGT): exit at 15% profit
        - NY (21-23 SGT): exit at 20% profit
        - Off session: exit at 5% profit
        """
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
