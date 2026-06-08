from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

from src.features.indicators import MarketRegime


class Signal(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ExitReason(StrEnum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    REGIME_FLIP = "REGIME_FLIP"
    TIME_EXIT = "TIME_EXIT"
    MEAN_REVERSION = "MEAN_REVERSION"


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    # --- regime detection ---
    adx_trend_threshold: float = 20.0

    # --- range (mean-reversion) thresholds ---
    range_rsi_oversold: float = 32.0
    range_rsi_overbought: float = 68.0
    range_bb_near_pct: float = 0.25

    # --- trend-following thresholds ---
    trend_ema_touch_pct: float = 0.01  # 1% of EMA

    # --- exit ---
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 3.0
    trail_activate_atr: float = 2.0
    trail_atr_mult: float = 1.0
    max_bars: int = 30

    # --- filters ---
    cooldown_bars: int = 2
    volume_ma_period: int = 20
    volume_min_mult: float = 0.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _trough(series: pd.Series) -> pd.Series:
    """True where series has local minimum (stopped falling, starting to rise)."""
    return (series > series.shift(1)) & (series.shift(1) <= series.shift(2))


def _near_ema(df: pd.DataFrame, ema_col: str, pct: float) -> pd.Series:
    return ((df["close"] - df[ema_col]).abs() / df[ema_col]) <= pct


def _near_bb_band(df: pd.DataFrame, band_col: str, width_pct: float) -> pd.Series:
    bb_width = df["bb_upper"] - df["bb_lower"]
    return ((df["close"] - df[band_col]).abs() / bb_width) <= width_pct


def _volume_above_ma(df: pd.DataFrame, period: int, min_mult: float) -> pd.Series:
    vol_ma = df["volume"].rolling(window=period, min_periods=period).mean()
    return df["volume"] >= (vol_ma * min_mult)


# ---------------------------------------------------------------------------
# Regime filter
# ---------------------------------------------------------------------------

def is_trending(df: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    return df["adx"] >= cfg.adx_trend_threshold


def is_ranging(df: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    return df["adx"] < cfg.adx_trend_threshold


# ---------------------------------------------------------------------------
# Entry logic
#
# Design rationale:
#   Range  → mean-reversion: buy oversold near BB lower
#   Trend  → trend-following: buy pullbacks in uptrend
#
# Each entry requires 3-of-4 conditions (RSI, location, MACD inflection, volume)
# so no single weak signal triggers a trade.
#
# Long-only system. Exits handled exclusively by check_exit().
# ---------------------------------------------------------------------------

def _range_buy(df: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    regime_ok = is_ranging(df, cfg)
    rsi_ok = df["rsi"] <= cfg.range_rsi_oversold
    near_bb = _near_bb_band(df, "bb_lower", cfg.range_bb_near_pct)
    macd_ok = _trough(df["macd_hist"])
    vol_ok = _volume_above_ma(df, cfg.volume_ma_period, cfg.volume_min_mult)
    # 3 of 4: RSI is mandatory, need 2 of (near BB, MACD turning, volume)
    confirm = (near_bb.astype(int) + macd_ok.astype(int) + vol_ok.astype(int)) >= 2
    return regime_ok & rsi_ok & confirm


def _trend_buy(df: pd.DataFrame, cfg: StrategyConfig) -> pd.Series:
    """Buy pullback in uptrend: price near EMA, MACD trough, volume OK."""
    regime_ok = df["regime"] == MarketRegime.TREND_UP
    near_ema = _near_ema(df, "ema_20", cfg.trend_ema_touch_pct)
    macd_ok = _trough(df["macd_hist"])
    vol_ok = _volume_above_ma(df, cfg.volume_ma_period, cfg.volume_min_mult)
    confirm = (near_ema.astype(int) + macd_ok.astype(int) + vol_ok.astype(int)) >= 2
    return regime_ok & confirm


def _apply_cooldown(signals: pd.Series, bars: int) -> pd.Series:
    """After each non-HOLD signal, suppress signals for `bars` periods."""
    result = signals.copy()
    last_signal = -bars - 1
    for i, idx in enumerate(signals.index):
        if signals.iloc[i] != Signal.HOLD and (i - last_signal) >= bars:
            last_signal = i
        elif signals.iloc[i] != Signal.HOLD and (i - last_signal) < bars:
            result.iloc[i] = Signal.HOLD
    return result


# ---------------------------------------------------------------------------
# Main entry signal generator
# ---------------------------------------------------------------------------

def generate_signals(
    df: pd.DataFrame,
    cfg: StrategyConfig | None = None,
) -> pd.Series:
    if cfg is None:
        cfg = StrategyConfig()

    buy = _trend_buy(df, cfg) | _range_buy(df, cfg)

    signal = pd.Series(Signal.HOLD, index=df.index)
    signal[buy] = Signal.BUY

    signal = _apply_cooldown(signal, cfg.cooldown_bars)
    return signal


# ---------------------------------------------------------------------------
# Exit logic (per-position, per-bar)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ExitCheckInput:
    """Snapshot of a single bar for an open position."""
    ts: pd.Timestamp
    close: float
    high: float
    low: float
    atr: float
    rsi: float
    regime: str   # MarketRegime value
    bars_held: int


def check_exit(
    entry_price: float,
    row: ExitCheckInput,
    direction: str = "long",
    extreme_since_entry: float | None = None,
    cfg: StrategyConfig | None = None,
) -> ExitReason | None:
    """Check if an open position should be closed on this bar.

    Args:
        entry_price: Position entry price.
        row: Current bar snapshot.
        direction: "long" or "short".
        extreme_since_entry: Best price seen since entry
            (highest high for long, lowest low for short).
        cfg: Strategy config.
    """
    if cfg is None:
        cfg = StrategyConfig()

    atr = row.atr
    if atr <= 0:
        atr = row.close * 0.002

    if direction == "long":
        return _check_exit_long(entry_price, row, atr, extreme_since_entry, cfg)
    else:
        return _check_exit_short(entry_price, row, atr, extreme_since_entry, cfg)


def _check_exit_long(
    entry_price: float,
    row: ExitCheckInput,
    atr: float,
    highest: float | None,
    cfg: StrategyConfig,
) -> ExitReason | None:
    high_water = max(highest or entry_price, row.high)

    sl_level = entry_price - cfg.sl_atr_mult * atr
    if row.low <= sl_level:
        return ExitReason.STOP_LOSS

    tp_level = entry_price + cfg.tp_atr_mult * atr
    if row.high >= tp_level:
        return ExitReason.TAKE_PROFIT

    trail_activate = cfg.trail_activate_atr * atr
    if high_water - entry_price >= trail_activate:
        trail_level = high_water - cfg.trail_atr_mult * atr
        if row.low <= trail_level:
            return ExitReason.TRAILING_STOP

    if row.regime == MarketRegime.RANGE and row.rsi >= cfg.range_rsi_overbought:
        return ExitReason.MEAN_REVERSION

    if row.regime == MarketRegime.TREND_DOWN:
        return ExitReason.REGIME_FLIP

    if row.bars_held >= cfg.max_bars:
        return ExitReason.TIME_EXIT

    return None


def _check_exit_short(
    entry_price: float,
    row: ExitCheckInput,
    atr: float,
    lowest: float | None,
    cfg: StrategyConfig,
) -> ExitReason | None:
    low_water = min(lowest or entry_price, row.low)

    sl_level = entry_price + cfg.sl_atr_mult * atr
    if row.high >= sl_level:
        return ExitReason.STOP_LOSS

    tp_level = entry_price - cfg.tp_atr_mult * atr
    if row.low <= tp_level:
        return ExitReason.TAKE_PROFIT

    trail_activate = cfg.trail_activate_atr * atr
    if entry_price - low_water >= trail_activate:
        trail_level = low_water + cfg.trail_atr_mult * atr
        if row.high >= trail_level:
            return ExitReason.TRAILING_STOP

    if row.regime == MarketRegime.TREND_UP:
        return ExitReason.REGIME_FLIP

    if row.bars_held >= cfg.max_bars:
        return ExitReason.TIME_EXIT

    return None
