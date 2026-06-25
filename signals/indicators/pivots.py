"""Swing pivot (fractal) detection.

A swing high at bar i is a local maximum: its high is strictly greater
than the highs of the ``left`` bars before and >= the ``right`` bars
after. Swing lows mirror this on lows. Because confirmation needs
``right`` future bars, a pivot at i is only *known* at bar ``i+right`` —
the ``confirmed_*`` helpers expose that no-lookahead view, which the
divergence and structure engines rely on to avoid repainting.

Shared by :mod:`signals.indicators.divergence` and
:mod:`signals.indicators.structure`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def swing_points(df: pd.DataFrame, left: int = 3, right: int = 3) -> pd.DataFrame:
    """Return boolean columns ``swing_high`` / ``swing_low`` at the pivot bar.

    Note: a pivot is marked at its actual bar i (not the confirmation bar).
    Use :func:`confirmed_pivot_index` for the no-lookahead timestamp.
    """
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    n = len(df)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)

    for i in range(left, n - right):
        hwin_l = high[i - left:i]
        hwin_r = high[i + 1:i + right + 1]
        if high[i] > hwin_l.max() and high[i] >= hwin_r.max():
            sh[i] = True
        lwin_l = low[i - left:i]
        lwin_r = low[i + 1:i + right + 1]
        if low[i] < lwin_l.min() and low[i] <= lwin_r.min():
            sl[i] = True

    return pd.DataFrame({"swing_high": sh, "swing_low": sl}, index=df.index)


def pivot_list(df: pd.DataFrame, kind: str, left: int = 3, right: int = 3
               ) -> list[tuple[int, float]]:
    """Return [(bar_index, price)] for swing highs or lows in chronological order.

    ``kind`` is ``"high"`` or ``"low"``. Price is the high/low at the pivot.
    """
    sp = swing_points(df, left, right)
    col = "swing_high" if kind == "high" else "swing_low"
    price_col = "high" if kind == "high" else "low"
    prices = df[price_col].to_numpy(float)
    idxs = np.flatnonzero(sp[col].to_numpy())
    return [(int(i), float(prices[i])) for i in idxs]


def confirmation_bar(pivot_index: int, right: int) -> int:
    """The bar index at which a pivot at ``pivot_index`` becomes confirmed."""
    return pivot_index + right
