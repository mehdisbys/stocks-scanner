"""Divergence engine with potential -> confirmed -> invalidated lifecycle
(section 3.2a; inspired by the public "(mab) Divergences" concept,
re-implemented from scratch).

A generic detector compares price swing pivots against an indicator's
value at those pivots:

- **Regular bullish** — price lower-low while indicator higher-low.
- **Regular bearish** — price higher-high while indicator lower-high.

Lifecycle (re-evaluated each bar after detection):

- **potential** — divergence detected at the second confirmed pivot.
- **confirmed** — price closes beyond the intervening pivot (the
  confirmation level: the swing high between the two lows for bullish,
  swing low between the two highs for bearish). The strong signal.
- **invalidated** — price closes beyond the divergence's own extreme
  (below low2 for bullish / above high2 for bearish) before confirming.

Runs over MACD, RSI, MFI, CMF, OBV, Williams %R and Squeeze Momentum and
aggregates. All indicators are computed from free OHLCV.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import core
from .pivots import swing_points

# (potential = early/weak, confirmed = strong, invalidated = dropped)
NONE, POTENTIAL, CONFIRMED, INVALIDATED = "none", "potential", "confirmed", "invalidated"


def _indicator_panel(df: pd.DataFrame) -> dict[str, pd.Series]:
    """The standard indicator set the detector runs divergences over."""
    m = core.macd(df["close"])
    sq = core.squeeze_momentum(df)
    return {
        "macd": m["hist"],
        "rsi": core.rsi(df["close"]),
        "mfi": core.mfi(df),          # (mab) MMF analogue — money-flow RSI
        "mvi": core.volume_rsi(df),   # (mab) MVI analogue — volume RSI
        "cmf": core.cmf(df),
        "obv": core.obv(df),
        "willr": core.williams_r(df),
        "squeeze": sq["momentum"],
    }


def divergence_states(
    df: pd.DataFrame,
    indicator: pd.Series,
    direction: str,
    left: int = 3,
    right: int = 3,
) -> pd.Series:
    """Per-bar lifecycle state (string) for one indicator + direction.

    ``direction`` is ``"bull"`` (uses swing lows) or ``"bear"`` (swing highs).
    """
    sp = swing_points(df, left, right)
    n = len(df)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    ind = indicator.to_numpy(float)
    state = np.array([NONE] * n, dtype=object)

    is_bull = direction == "bull"
    pivot_col = "swing_low" if is_bull else "swing_high"
    pivot_price = low if is_bull else high
    pivot_flags = sp[pivot_col].to_numpy()

    prev_piv: tuple[int, float, float] | None = None   # (idx, price, ind)
    active: dict | None = None                          # current divergence

    for i in range(n):
        # 1) resolve an active divergence on this bar — confirmation is on the
        #    INDICATOR (per the (mab) definition): the indicator crossing back
        #    above its interim peak (confirmation level), not a price break.
        if active is not None and not np.isnan(ind[i]):
            if is_bull:
                if ind[i] > active["confirm_level"]:
                    state[i] = CONFIRMED
                    active = None
                elif ind[i] < active["invalid_level"]:
                    state[i] = INVALIDATED
                    active = None
                else:
                    state[i] = POTENTIAL
            else:
                if ind[i] < active["confirm_level"]:
                    state[i] = CONFIRMED
                    active = None
                elif ind[i] > active["invalid_level"]:
                    state[i] = INVALIDATED
                    active = None
                else:
                    state[i] = POTENTIAL
        elif active is not None:
            state[i] = POTENTIAL

        # 2) a pivot confirmed `right` bars ago becomes known now
        p = i - right
        if p >= 0 and pivot_flags[p] and not np.isnan(ind[p]):
            cur = (p, float(pivot_price[p]), float(ind[p]))
            if prev_piv is not None:
                pi, pp, pind = prev_piv
                ind_seg = ind[pi:p + 1]
                if is_bull:
                    diverges = cur[1] < pp and cur[2] > pind   # LL price, HL ind
                    # confirmation level = indicator's interim peak between the
                    # two price lows; invalidation = the divergence's ind low
                    confirm_level = float(np.nanmax(ind_seg))
                    invalid_level = cur[2]
                else:
                    diverges = cur[1] > pp and cur[2] < pind   # HH price, LH ind
                    confirm_level = float(np.nanmin(ind_seg))
                    invalid_level = cur[2]
                if diverges:
                    active = {"confirm_level": confirm_level,
                              "invalid_level": invalid_level}
                    if state[i] == NONE:
                        state[i] = POTENTIAL
            prev_piv = cur

    return pd.Series(state, index=df.index, name=f"{direction}_div")


def divergence_signals(df: pd.DataFrame, left: int = 3, right: int = 3
                       ) -> pd.DataFrame:
    """Run divergences over the standard indicator panel and aggregate.

    Returns per-indicator state columns plus aggregate event booleans and
    counts that the scoring engine can weight directly.
    """
    panel = _indicator_panel(df)
    cols: dict[str, pd.Series] = {}
    for name, series in panel.items():
        bull = divergence_states(df, series, "bull", left, right)
        bear = divergence_states(df, series, "bear", left, right)
        cols[f"{name}_bull_div"] = bull
        cols[f"{name}_bear_div"] = bear
    states = pd.DataFrame(cols, index=df.index)

    bull_cols = [c for c in states.columns if c.endswith("bull_div")]
    bear_cols = [c for c in states.columns if c.endswith("bear_div")]

    def _count(frame_cols, value):
        return states[frame_cols].eq(value).sum(axis=1)

    agg = pd.DataFrame(index=df.index)
    agg["bull_div_potential_n"] = _count(bull_cols, POTENTIAL)
    agg["bull_div_confirmed_n"] = _count(bull_cols, CONFIRMED)
    agg["bear_div_potential_n"] = _count(bear_cols, POTENTIAL)
    agg["bear_div_confirmed_n"] = _count(bear_cols, CONFIRMED)
    # convenience booleans (entry = bullish, exit = bearish)
    agg["bull_div_confirmed_any"] = agg["bull_div_confirmed_n"] > 0
    agg["bear_div_confirmed_any"] = agg["bear_div_confirmed_n"] > 0

    return pd.concat([states, agg], axis=1)
