"""Inline Institutional Bias (IIB) — after tsmmob's TradingView script.

Higher-timeframe market state from the **9 EMA vs 18 EMA** relationship:
bias is bullish when 9 EMA > 18 EMA, bearish when 9 EMA < 18 EMA. A
**30 SMA** "reference" MA marks the preferred *trade location* — you enter
in the direction of the bias when price pulls back to that reference.

The original computes the MAs on the 1D timeframe regardless of the chart
timeframe. Our base series is already daily, so the MAs are computed
directly (set ``higher_tf=True`` to use weekly instead, resampled).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import core


def institutional_bias_signals(
    df: pd.DataFrame,
    fast: int = 9,
    slow: int = 18,
    ref: int = 30,
    ref_tol: float = 0.015,        # "at" the reference = within ±1.5%
    higher_tf: bool = False,
) -> pd.DataFrame:
    src = df
    if higher_tf:
        from ..data.base import Timeframe
        from ..data.resample import resample
        src = resample(df, Timeframe.W1)

    close = src["close"]
    ema_fast = core.ema(close, fast)
    ema_slow = core.ema(close, slow)
    sma_ref = core.sma(close, ref)

    bias = pd.Series(0, index=src.index, dtype=int)
    bias = bias.mask(ema_fast > ema_slow, 1).mask(ema_fast < ema_slow, -1)

    out = pd.DataFrame({
        "ib_fast": ema_fast,
        "ib_slow": ema_slow,
        "ib_ref": sma_ref,
        "ib_bias": bias,
    }, index=src.index)
    out["ib_bullish"] = bias == 1
    out["ib_bearish"] = bias == -1
    at_ref = (close - sma_ref).abs() / sma_ref <= ref_tol
    out["ib_at_ref"] = at_ref.fillna(False)
    # trade location: price at the reference MA, in the direction of bias
    out["ib_long_location"] = out["ib_bullish"] & out["ib_at_ref"]
    out["ib_short_location"] = out["ib_bearish"] & out["ib_at_ref"]

    if higher_tf:
        out = out.reindex(df.index, method="ffill")
        for c in ["ib_bullish", "ib_bearish", "ib_at_ref",
                  "ib_long_location", "ib_short_location"]:
            out[c] = out[c].fillna(False).astype(bool)
        out["ib_bias"] = out["ib_bias"].fillna(0).astype(int)
    return out
