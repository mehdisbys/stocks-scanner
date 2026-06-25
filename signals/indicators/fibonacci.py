"""Fibonacci retracement entry zone (0.786).

For a bullish pullback entry, we track the most recent *up-leg* — a
confirmed swing low followed by a higher confirmed swing high — and
compute its retracement levels measured down from the high:

    level(r) = high - r * (high - low)

The 0.786 retracement sits deep in the leg (just above the prior low) and
is a common pullback-entry zone: price has given back most of the move
but the structure (the swing low) still holds. ``near_fib_786`` fires when
the close is within a tolerance band of that level.

Swing pivots are confirmed (``right`` bars after the fact), so the level
does not repaint.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .pivots import swing_points

FIB = 0.786


def fibonacci_signals(
    df: pd.DataFrame,
    left: int = 6,
    right: int = 6,            # 6-bar daily swings -> retrace off significant legs
    tol: float = 0.012,        # "around" = within ±1.2% of the level
    ratio: float = FIB,
) -> pd.DataFrame:
    sp = swing_points(df, left, right)
    sh = sp["swing_high"].to_numpy()
    sl = sp["swing_low"].to_numpy()
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    n = len(df)

    level_arr = np.full(n, np.nan)
    near = np.zeros(n, dtype=bool)

    last_low: tuple[int, float] | None = None
    leg_low = leg_high = None     # prices of the active up-leg
    level = np.nan

    for i in range(n):
        # update the active leg from a pivot confirmed `right` bars ago
        p = i - right
        if p >= 0:
            if sl[p]:
                last_low = (p, float(low[p]))
            if sh[p] and last_low is not None and high[p] > last_low[1]:
                leg_low = last_low[1]
                leg_high = float(high[p])
                level = leg_high - ratio * (leg_high - leg_low)

        # flag this bar against the current level
        if not np.isnan(level):
            level_arr[i] = level
            if level > 0 and abs(close[i] - level) / level <= tol \
                    and close[i] <= leg_high:
                near[i] = True

    return pd.DataFrame(
        {"fib_786_level": level_arr, "near_fib_786": near},
        index=df.index,
    )
