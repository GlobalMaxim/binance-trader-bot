from __future__ import annotations

from enum import StrEnum

import pandas as pd

from src.collector.ohlcv import Candle


class MarketRegime(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    RANGE = "RANGE"


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "ts": c.ts,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    )
    df["ts"] = pd.to_datetime(df["ts"])
    df.sort_values("ts", inplace=True)
    df.set_index("ts", inplace=True)
    return df


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_ema(df: pd.DataFrame, period: int) -> pd.Series:
    return df["close"].ewm(span=period, adjust=False).mean()


def compute_macd(
    df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    ema_fast = compute_ema(df, fast)
    ema_slow = compute_ema(df, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "macd_signal": signal_line, "macd_hist": histogram},
        index=df.index,
    )


def compute_bollinger_bands(
    df: pd.DataFrame, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    middle = df["close"].rolling(window=period, min_periods=period).mean()
    std = df["close"].rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return pd.DataFrame(
        {"bb_upper": upper, "bb_middle": middle, "bb_lower": lower},
        index=df.index,
    )


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - close).abs(),
            (low - close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def _directional_movement(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Approximate ADX using smoothed +DI / -DI."""
    high, low = df["high"], df["low"]
    prev_high, prev_low = high.shift(1), low.shift(1)

    up_move = high - prev_high
    down_move = prev_low - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    mask_plus = (up_move > down_move) & (up_move > 0)
    mask_minus = (down_move > up_move) & (down_move > 0)
    plus_dm[mask_plus] = up_move[mask_plus].clip(lower=0)
    minus_dm[mask_minus] = down_move[mask_minus].clip(lower=0)

    tr = compute_atr(df, period) * period
    atr_raw = tr.replace(0, pd.NA)

    plus_di = 100.0 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_raw
    minus_di = 100.0 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_raw

    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)) * 100.0
    adx = dx.ewm(alpha=1 / period, min_periods=period * 2, adjust=False).mean()

    return pd.DataFrame(
        {"adx": adx, "plus_di": plus_di, "minus_di": minus_di}, index=df.index
    )


def detect_regime(
    df: pd.DataFrame,
    adx_col: str = "adx",
    plus_di_col: str = "plus_di",
    minus_di_col: str = "minus_di",
    ema_fast: str = "ema_20",
    ema_slow: str = "ema_50",
    adx_threshold: float = 20.0,
) -> pd.Series:
    adx = df[adx_col]
    regime = pd.Series(MarketRegime.RANGE, index=df.index)

    # trend conditions
    trend_strength = adx >= adx_threshold
    di_bull = df[plus_di_col] > df[minus_di_col]
    di_bear = df[minus_di_col] > df[plus_di_col]
    ema_bull = df[ema_fast] > df[ema_slow]
    ema_bear = df[ema_fast] < df[ema_slow]

    regime[trend_strength & di_bull & ema_bull] = MarketRegime.TREND_UP
    regime[trend_strength & di_bear & ema_bear] = MarketRegime.TREND_DOWN

    return regime


def compute_all_indicators(
    df: pd.DataFrame,
    rsi_period: int = 14,
    ema_periods: tuple[int, ...] = (20, 50),
    macd_params: tuple[int, int, int] = (12, 26, 9),
    bb_period: int = 20,
    bb_std: float = 2.0,
    atr_period: int = 14,
    adx_period: int = 14,
) -> pd.DataFrame:
    result = df.copy()
    result["rsi"] = compute_rsi(df, rsi_period)
    for p in ema_periods:
        result[f"ema_{p}"] = compute_ema(df, p)
    macd = compute_macd(df, *macd_params)
    result["macd"] = macd["macd"]
    result["macd_signal"] = macd["macd_signal"]
    result["macd_hist"] = macd["macd_hist"]
    bb = compute_bollinger_bands(df, bb_period, bb_std)
    result["bb_upper"] = bb["bb_upper"]
    result["bb_middle"] = bb["bb_middle"]
    result["bb_lower"] = bb["bb_lower"]
    result["atr"] = compute_atr(df, atr_period)
    dm = _directional_movement(df, adx_period)
    for col in dm.columns:
        result[col] = dm[col]
    result["regime"] = detect_regime(result)
    return result
