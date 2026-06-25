"""Volume momentum (section 3.2e).

Measures whether volume is *building and accelerating* behind a move —
confirmation that a breakout/trend has real participation. Distinct from
volume *divergence* (handled in divergence.py), which warns when volume
disagrees with price.
"""

from __future__ import annotations

import pandas as pd

from . import core


def volume_momentum_signals(
    df: pd.DataFrame,
    rvol_n: int = 20,
    rvol_high: float = 1.5,
    vol_roc_n: int = 5,
    obv_slope_n: int = 10,
    vol_osc_fast: int = 5,
    vol_osc_slow: int = 20,
    pressure_n: int = 10,
) -> pd.DataFrame:
    vol = df["volume"]
    close = df["close"]

    rv = core.rvol(df, rvol_n)
    vol_roc = core.roc(vol.replace(0, float("nan")), vol_roc_n)
    vol_accel = vol_roc.diff()                       # rate-of-change of the ROC

    obv = core.obv(df)
    obv_slope = obv.diff(obv_slope_n)
    obv_new_high = obv >= obv.rolling(obv_slope_n, min_periods=obv_slope_n).max()

    vol_osc = core.volume_oscillator(df, vol_osc_fast, vol_osc_slow)

    up_vol = vol.where(close.diff() > 0, 0.0)
    down_vol = vol.where(close.diff() < 0, 0.0)
    up_sum = up_vol.rolling(pressure_n, min_periods=pressure_n).sum()
    down_sum = down_vol.rolling(pressure_n, min_periods=pressure_n).sum()
    net_pressure = (up_sum - down_sum) / (up_sum + down_sum).replace(0.0, pd.NA)

    high_rvol = rv >= rvol_high
    up_day = close.diff() > 0

    return pd.DataFrame(
        {
            "rvol": rv,
            "vol_roc": vol_roc,
            "vol_accel": vol_accel,
            "obv_slope": obv_slope,
            "vol_oscillator": vol_osc,
            "net_volume_pressure": net_pressure,
            # bullish / confirmation events
            "high_rvol": high_rvol.fillna(False),
            "rvol_up_day": (high_rvol & up_day).fillna(False),
            "vol_expanding": (vol_osc > 0).fillna(False),
            "obv_rising": (obv_slope > 0).fillna(False),
            "obv_confirming_high": obv_new_high.fillna(False),
            "buying_pressure": (net_pressure > 0).fillna(False),
            # bearish / exit events
            "selling_pressure": (net_pressure < 0).fillna(False),
            "vol_contracting": (vol_osc < 0).fillna(False),
        },
        index=df.index,
    )


def breakout_volume_confirmed(df: pd.DataFrame, rvol_n: int = 20,
                              rvol_high: float = 1.5) -> pd.Series:
    """Boolean flag usable to gate structure/MA-cross entries.

    True when the current bar has expanding volume (high RVOL) — i.e. a
    breakout occurring here has real participation behind it.
    """
    return (core.rvol(df, rvol_n) >= rvol_high).fillna(False)
