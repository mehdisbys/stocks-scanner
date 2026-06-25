"""MACD + RSI condition signals (the core momentum group).

Produces boolean event columns the scoring engine will weight. Entry-side
events are bullish; exit-side events are bearish. Divergence for MACD/RSI
is handled separately by :mod:`signals.indicators.divergence`.
"""

from __future__ import annotations

import pandas as pd

from . import core


def macd_rsi_signals(
    df: pd.DataFrame,
    rsi_n: int = 14,
    rsi_os: float = 30.0,
    rsi_ob: float = 70.0,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> pd.DataFrame:
    close = df["close"]
    r = core.rsi(close, rsi_n)
    m = core.macd(close, macd_fast, macd_slow, macd_signal)
    macd_line, sig, hist = m["macd"], m["signal"], m["hist"]

    macd_cross_up = (macd_line > sig) & (macd_line.shift(1) <= sig.shift(1))
    macd_cross_down = (macd_line < sig) & (macd_line.shift(1) >= sig.shift(1))
    hist_rising = hist.diff() > 0
    hist_falling = hist.diff() < 0

    rsi_oversold = r < rsi_os
    rsi_overbought = r > rsi_ob
    rsi_rising_from_os = (r > r.shift(1)) & (r.shift(1) < rsi_os)
    rsi_falling_from_ob = (r < r.shift(1)) & (r.shift(1) > rsi_ob)
    rsi_cross_50_up = (r > 50) & (r.shift(1) <= 50)
    rsi_cross_50_down = (r < 50) & (r.shift(1) >= 50)

    return pd.DataFrame(
        {
            "rsi": r,
            "macd": macd_line,
            "macd_signal": sig,
            "macd_hist": hist,
            # bullish / entry events
            "macd_cross_up": macd_cross_up,
            "macd_hist_rising": hist_rising,
            "rsi_oversold": rsi_oversold,
            "rsi_rising_from_oversold": rsi_rising_from_os,
            "rsi_cross_50_up": rsi_cross_50_up,
            # bearish / exit events
            "macd_cross_down": macd_cross_down,
            "macd_hist_falling": hist_falling,
            "rsi_overbought": rsi_overbought,
            "rsi_falling_from_overbought": rsi_falling_from_ob,
            "rsi_cross_50_down": rsi_cross_50_down,
        },
        index=df.index,
    )
