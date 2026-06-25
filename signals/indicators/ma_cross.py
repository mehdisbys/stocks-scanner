"""Moving-average cross engine (section 3.2b).

Fires on the bar a cross happens (not just the resulting state):

- **MA/MA crosses** — a fast MA crossing a slow MA. Bullish "golden cross"
  (fast crosses above slow) feeds entries; bearish "death cross" feeds exits.
- **Price/MA crosses** — close crossing a single MA.

MA pairs, type (SMA/EMA) and periods are configurable. Optional filters:
require alignment with a longer-term trend, and a minimum separation slope
to suppress flat-market whipsaws.
"""

from __future__ import annotations

import pandas as pd

from . import core

# Default pairs (fast, slow). 50/200 is the classic golden/death cross.
DEFAULT_PAIRS = [(9, 21), (20, 50), (50, 200)]
DEFAULT_PRICE_MAS = [50, 200]


def _ma(close: pd.Series, period: int, kind: str) -> pd.Series:
    return core.ema(close, period) if kind == "ema" else core.sma(close, period)


def ma_cross_signals(
    df: pd.DataFrame,
    pairs: list[tuple[int, int]] | None = None,
    price_mas: list[int] | None = None,
    kind: str = "ema",
    min_slope_pct: float = 0.0,
) -> pd.DataFrame:
    """Return cross-event columns for each configured pair / price-MA.

    Column names: ``golden_<f>_<s>`` / ``death_<f>_<s>`` for MA/MA crosses,
    ``price_above_<p>`` / ``price_below_<p>`` for price/MA crosses.
    ``min_slope_pct`` (e.g. 0.1) requires the slow MA's 1-bar change to
    exceed that % of its value, filtering flat-market whipsaw.
    """
    pairs = pairs or DEFAULT_PAIRS
    price_mas = price_mas or DEFAULT_PRICE_MAS
    close = df["close"]
    out: dict[str, pd.Series] = {}

    for fast, slow in pairs:
        mf = _ma(close, fast, kind)
        ms = _ma(close, slow, kind)
        up = (mf > ms) & (mf.shift(1) <= ms.shift(1))
        down = (mf < ms) & (mf.shift(1) >= ms.shift(1))
        if min_slope_pct > 0:
            slope_ok = (ms.diff().abs() / ms) * 100.0 >= min_slope_pct
            up = up & slope_ok
            down = down & slope_ok
        out[f"golden_{fast}_{slow}"] = up.fillna(False)
        out[f"death_{fast}_{slow}"] = down.fillna(False)
        out[f"ma{fast}"] = mf
        out[f"ma{slow}"] = ms

    for p in price_mas:
        mp = _ma(close, p, kind)
        out[f"price_above_{p}"] = ((close > mp) & (close.shift(1) <= mp.shift(1))).fillna(False)
        out[f"price_below_{p}"] = ((close < mp) & (close.shift(1) >= mp.shift(1))).fillna(False)

    return pd.DataFrame(out, index=df.index)
