"""Base / consolidation-at-lows detector.

Targets the setup: a stock that fell hard, then spent a long time
consolidating near the bottom of its multi-year range ("not hot"), where
quiet accumulation often precedes a big move. Quantified from OHLCV:

- **drawdown_from_high** — how far below the multi-year high (beaten down).
- **range_position** — where price sits in its multi-year high/low range
  (low = near the bottom of the range).
- **flat_trend** — roughly sideways over the last year (small 1y change and
  a flat long MA): consolidating rather than still crashing or ripping.
- **vol_contraction** — recent realised volatility below its own median
  (the range is coiling/quiet).
- **accumulation** — OBV turning up off the lows.

``base_setup`` is the AND of beaten-down + near-lows + consolidating.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import core


def base_consolidation_signals(
    df: pd.DataFrame,
    range_lookback: int = 0,       # 0 = expanding (full-history major high)
    base_window: int = 252,        # ~1y window for "consolidating"
    dd_min: float = 0.55,          # >=55% off the multi-year high
    range_pos_max: float = 0.40,   # bottom 40% of the range
    yr_change_max: float = 0.60,   # |1y change| <= 60% (sideways-ish)
    slope_flat: float = 0.12,      # |200d MA change over 60d| <= 12%
) -> pd.DataFrame:
    close = df["close"]
    high, low = df["high"], df["low"]
    mp = min(base_window, len(df))

    # Drawdown/range measured against the major (multi-year) high. Expanding
    # captures the true peak of a long decline; a finite window can lose it.
    if range_lookback and range_lookback > 0:
        hi = high.rolling(range_lookback, min_periods=mp).max()
        lo = low.rolling(range_lookback, min_periods=mp).min()
    else:
        hi = high.expanding(min_periods=mp).max()
        lo = low.expanding(min_periods=mp).min()
    rng = (hi - lo).replace(0, np.nan)
    range_position = (close - lo) / rng
    drawdown = close / hi - 1.0

    yr_change = close / close.shift(base_window) - 1.0
    sma200 = core.sma(close, 200)
    sma_slope = sma200 / sma200.shift(60) - 1.0

    rets = close.pct_change()
    vol = rets.rolling(63, min_periods=30).std()
    vol_med = vol.rolling(base_window, min_periods=mp).median()

    obv = core.obv(df)
    obv_slope = obv.diff(63)

    deep_drawdown = drawdown <= -dd_min
    near_lows = range_position <= range_pos_max
    flat_trend = (yr_change.abs() <= yr_change_max) & (sma_slope.abs() <= slope_flat)
    vol_contraction = vol <= vol_med
    accumulation = obv_slope > 0
    consolidating = flat_trend & vol_contraction

    out = pd.DataFrame({
        "range_position": range_position,
        "drawdown_from_high": drawdown,
        "yr_change": yr_change,
        "deep_drawdown": deep_drawdown.fillna(False),
        "near_lows": near_lows.fillna(False),
        "flat_trend": flat_trend.fillna(False),
        "vol_contraction": vol_contraction.fillna(False),
        "consolidating": consolidating.fillna(False),
        "accumulation": accumulation.fillna(False),
    }, index=df.index)
    out["base_setup"] = (out["deep_drawdown"] & out["near_lows"]
                         & out["consolidating"])
    # a softer "base + turning up" entry: base present and OBV accumulating
    out["base_accumulating"] = (out["deep_drawdown"] & out["near_lows"]
                                & out["accumulation"])
    return out
