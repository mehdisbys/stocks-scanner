"""Core technical indicators — pure pandas/numpy, no external TA library.

Self-contained so the system has no dependency on a specific TA package
version. Every function takes an OHLCV DataFrame (canonical contract) or
a price Series and returns Series/DataFrame aligned to the input index.

Wilder-smoothed indicators (RSI, ATR, ADX) use ``ewm(alpha=1/n)`` which
is the standard Wilder RMA.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# -- moving averages --------------------------------------------------------

def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder's RMA smoothing (used by RSI/ATR/ADX)."""
    return s.ewm(alpha=1.0 / n, adjust=False).mean()


# -- momentum / oscillators -------------------------------------------------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = _wilder(gain, n)
    avg_loss = _wilder(loss, n)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    # when avg_loss==0 -> RSI 100; when avg_gain==0 -> RSI 0
    out = out.where(avg_loss != 0, 100.0)
    out = out.where(avg_gain != 0, 0.0)
    return out


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
         ) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist}
    )


def roc(close: pd.Series, n: int = 10) -> pd.Series:
    return 100.0 * (close / close.shift(n) - 1.0)


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    hh = df["high"].rolling(n, min_periods=n).max()
    ll = df["low"].rolling(n, min_periods=n).min()
    return -100.0 * (hh - df["close"]) / (hh - ll).replace(0.0, np.nan)


# -- volatility / trend strength -------------------------------------------

def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return _wilder(true_range(df), n)


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = ((up > down) & (up > 0)) * up
    minus_dm = ((down > up) & (down > 0)) * down
    tr_n = _wilder(true_range(df), n)
    plus_di = 100.0 * _wilder(plus_dm, n) / tr_n.replace(0.0, np.nan)
    minus_di = 100.0 * _wilder(minus_dm, n) / tr_n.replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    adx_line = _wilder(dx, n)
    return pd.DataFrame({"adx": adx_line, "plus_di": plus_di, "minus_di": minus_di})


# -- volume indicators ------------------------------------------------------

def obv(df: pd.DataFrame) -> pd.Series:
    sign = np.sign(df["close"].diff()).fillna(0.0)
    return (sign * df["volume"]).cumsum()


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    rmf = tp * df["volume"]
    tp_change = tp.diff()
    pos = rmf.where(tp_change > 0, 0.0)
    neg = rmf.where(tp_change < 0, 0.0)
    pos_sum = pos.rolling(n, min_periods=n).sum()
    neg_sum = neg.rolling(n, min_periods=n).sum()
    mfr = pos_sum / neg_sum.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + mfr)
    return out.where(neg_sum != 0, 100.0)


def cmf(df: pd.DataFrame, n: int = 20) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0.0, np.nan)
    mult = ((df["close"] - df["low"]) - (df["high"] - df["close"])) / rng
    mfv = (mult * df["volume"]).fillna(0.0)
    return mfv.rolling(n, min_periods=n).sum() / df["volume"].rolling(
        n, min_periods=n).sum().replace(0.0, np.nan)


def volume_rsi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """MVI-style 'volume index' — Wilder RSI applied to the volume series.

    Approximates the (mab) MVI ("volume index using a formula similar to
    RSI"). Used for divergence detection alongside price-based indicators.
    """
    return rsi(df["volume"].astype(float), n)


def rvol(df: pd.DataFrame, n: int = 20) -> pd.Series:
    """Relative volume: current volume vs its N-period average."""
    return df["volume"] / df["volume"].rolling(n, min_periods=n).mean()


def volume_oscillator(df: pd.DataFrame, fast: int = 5, slow: int = 20) -> pd.Series:
    vf = ema(df["volume"], fast)
    vs = ema(df["volume"], slow)
    return 100.0 * (vf - vs) / vs.replace(0.0, np.nan)


# -- squeeze momentum (Carter / LazyBear) ----------------------------------

def squeeze_momentum(df: pd.DataFrame, n: int = 20, mult_bb: float = 2.0,
                     mult_kc: float = 1.5) -> pd.DataFrame:
    """Squeeze Momentum: histogram value + squeeze on/off flag.

    ``momentum`` is the linear-regression value of price minus the mean of
    the Donchian midline and the SMA (the LazyBear formulation).
    ``squeeze_on`` is true when Bollinger Bands sit inside Keltner Channels.
    """
    close, high, low = df["close"], df["high"], df["low"]
    basis = sma(close, n)
    dev = mult_bb * close.rolling(n, min_periods=n).std(ddof=0)
    upper_bb, lower_bb = basis + dev, basis - dev

    rng = _wilder(true_range(df), n)  # ATR-like for KC
    upper_kc = basis + mult_kc * rng
    lower_kc = basis - mult_kc * rng
    squeeze_on = (lower_bb > lower_kc) & (upper_bb < upper_kc)

    hh = high.rolling(n, min_periods=n).max()
    ll = low.rolling(n, min_periods=n).min()
    donchian_mid = (hh + ll) / 2.0
    ref = (donchian_mid + basis) / 2.0
    val = _linreg(close - ref, n)
    return pd.DataFrame({"momentum": val, "squeeze_on": squeeze_on})


def _linreg(s: pd.Series, n: int) -> pd.Series:
    """Rolling linear-regression endpoint value (slope*  (n-1) + intercept)."""
    x = np.arange(n)
    x_mean = x.mean()
    denom = ((x - x_mean) ** 2).sum()

    def _f(window: np.ndarray) -> float:
        y_mean = window.mean()
        slope = ((x - x_mean) * (window - y_mean)).sum() / denom
        intercept = y_mean - slope * x_mean
        return slope * (n - 1) + intercept

    return s.rolling(n, min_periods=n).apply(_f, raw=True)
