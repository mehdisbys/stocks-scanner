"""Market structure (section 3.2c): W / M patterns, HH/HL trend, breakouts.

- **W (double bottom, bullish)** — two swing lows at a similar level with
  a swing high (neckline) between them. *Potential* when the second low
  confirms near the first; *confirmed* on a close above the neckline;
  *invalidated* on a close below the lower of the two bottoms.
- **M (double top, bearish)** — the mirror, neckline = swing low between
  two similar highs; confirmed on a close below it.
- **HH/HL trend** — uptrend when the last two swing highs and lows are
  both rising; downtrend when both falling.
- **Breakouts** — close beyond the most recent confirmed swing high/low.

Built on confirmed swing pivots so patterns do not repaint (confirmation
arrives ``right`` bars after the visual pivot — a deliberate
reliability-over-immediacy trade-off).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .pivots import swing_points

NONE, POTENTIAL, CONFIRMED, INVALIDATED = "none", "potential", "confirmed", "invalidated"


def structure_signals(
    df: pd.DataFrame,
    left: int = 3,
    right: int = 3,
    level_tol: float = 0.03,      # two lows/highs within ±3% = "similar"
    min_sep: int = 5,             # min bars between the two pivots
    max_sep: int = 60,            # max bars between the two pivots
) -> pd.DataFrame:
    sp = swing_points(df, left, right)
    n = len(df)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    close = df["close"].to_numpy(float)
    sh = sp["swing_high"].to_numpy()
    sl = sp["swing_low"].to_numpy()

    w_state = np.array([NONE] * n, dtype=object)
    m_state = np.array([NONE] * n, dtype=object)
    trend = np.zeros(n, dtype=int)
    breakout_up = np.zeros(n, dtype=bool)
    breakout_dn = np.zeros(n, dtype=bool)

    lows: list[tuple[int, float]] = []
    highs: list[tuple[int, float]] = []
    w_active: dict | None = None
    m_active: dict | None = None
    last_conf_high: float | None = None
    last_conf_low: float | None = None

    for i in range(n):
        # ---- resolve active patterns ----
        if w_active is not None:
            if close[i] > w_active["neckline"]:
                w_state[i] = CONFIRMED
                w_active = None
            elif close[i] < w_active["invalid"]:
                w_state[i] = INVALIDATED
                w_active = None
            else:
                w_state[i] = POTENTIAL
        if m_active is not None:
            if close[i] < m_active["neckline"]:
                m_state[i] = CONFIRMED
                m_active = None
            elif close[i] > m_active["invalid"]:
                m_state[i] = INVALIDATED
                m_active = None
            else:
                m_state[i] = POTENTIAL

        # ---- breakouts of last confirmed pivots ----
        if last_conf_high is not None and close[i] > last_conf_high:
            breakout_up[i] = True
        if last_conf_low is not None and close[i] < last_conf_low:
            breakout_dn[i] = True

        # ---- a pivot confirmed `right` bars ago ----
        p = i - right
        if p >= 0 and sl[p]:
            lows.append((p, float(low[p])))
            last_conf_low = float(low[p])
            if len(lows) >= 2:
                (i1, l1), (i2, l2) = lows[-2], lows[-1]
                sep = i2 - i1
                similar = abs(l2 - l1) / l1 <= level_tol
                if similar and min_sep <= sep <= max_sep:
                    neckline = float(high[i1:i2 + 1].max())
                    w_active = {"neckline": neckline, "invalid": min(l1, l2)}
                    if w_state[i] == NONE:
                        w_state[i] = POTENTIAL
        if p >= 0 and sh[p]:
            highs.append((p, float(high[p])))
            last_conf_high = float(high[p])
            if len(highs) >= 2:
                (i1, h1), (i2, h2) = highs[-2], highs[-1]
                sep = i2 - i1
                similar = abs(h2 - h1) / h1 <= level_tol
                if similar and min_sep <= sep <= max_sep:
                    neckline = float(low[i1:i2 + 1].min())
                    m_active = {"neckline": neckline, "invalid": max(h1, h2)}
                    if m_state[i] == NONE:
                        m_state[i] = POTENTIAL

        # ---- HH/HL trend from last two pivots of each kind ----
        t = 0
        if len(highs) >= 2 and len(lows) >= 2:
            hh = highs[-1][1] > highs[-2][1]
            hl = lows[-1][1] > lows[-2][1]
            lh = highs[-1][1] < highs[-2][1]
            ll = lows[-1][1] < lows[-2][1]
            if hh and hl:
                t = 1
            elif lh and ll:
                t = -1
        trend[i] = t

    return pd.DataFrame(
        {
            "w_state": w_state,        # double bottom (bullish)
            "m_state": m_state,        # double top (bearish)
            "structure_trend": trend,  # 1 up / -1 down / 0 mixed
            "breakout_up": breakout_up,
            "breakout_down": breakout_dn,
            "w_confirmed": w_state == CONFIRMED,
            "m_confirmed": m_state == CONFIRMED,
        },
        index=df.index,
    )


def structure_weekly_signals(df: pd.DataFrame, **kw) -> pd.DataFrame:
    """W/M structure detected on the WEEKLY timeframe, mapped to the daily
    index (forward-filled) so weekly patterns can feed daily-bar scoring.

    Weekly candles are resampled from the input (daily) data — no extra
    feed. Columns are the same as ``structure_signals`` but reflect the
    weekly chart, prefixed with ``wk_`` to avoid clashing with daily.
    """
    from ..data.base import Timeframe
    from ..data.resample import resample

    weekly = resample(df, Timeframe.W1)
    if len(weekly) < 10:
        # not enough weekly history; return an all-"none" frame
        empty = pd.DataFrame(index=df.index)
        for c in ["w_state", "m_state"]:
            empty[c] = "none"
        for c in ["breakout_up", "breakout_down", "w_confirmed", "m_confirmed"]:
            empty[c] = False
        empty["structure_trend"] = 0
        return empty.add_prefix("wk_")

    st = structure_signals(weekly, **kw)
    st = st.reindex(df.index, method="ffill")
    for c in ["w_state", "m_state"]:
        st[c] = st[c].fillna("none")
    for c in ["breakout_up", "breakout_down", "w_confirmed", "m_confirmed"]:
        st[c] = st[c].fillna(False).astype(bool)
    st["structure_trend"] = st["structure_trend"].fillna(0).astype(int)
    return st.add_prefix("wk_")
