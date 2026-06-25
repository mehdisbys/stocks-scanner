"""Multi-timeframe trend context (section 3.2d).

Classifies the prevailing trend on a timeframe as bullish / bearish /
neutral from a small composite (EMA stack, slope, structure), then scores
the *alignment* of weekly / daily / 4h so a signal can be weighted up when
all agree and down when a higher timeframe conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import core

BULLISH, BEARISH, NEUTRAL = 1, -1, 0
_LABEL = {1: "bullish", -1: "bearish", 0: "neutral"}


def classify_trend(
    df: pd.DataFrame,
    fast: int = 50,
    slow: int = 200,
    slope_n: int = 20,
) -> pd.Series:
    """Per-bar trend label (1 / 0 / -1) for one timeframe.

    Bullish needs: price above fast EMA, fast EMA above slow EMA, and a
    rising fast EMA. Bearish is the mirror. Anything else is neutral.
    For short series where ``slow`` EMA is unavailable, falls back to the
    price-vs-fast-EMA + slope read.
    """
    close = df["close"]
    ef = core.ema(close, fast)
    es = core.ema(close, slow)
    slope_up = ef.diff(slope_n) > 0
    slope_dn = ef.diff(slope_n) < 0

    have_slow = es.notna()
    bull = (close > ef) & ((ef > es) | ~have_slow) & slope_up
    bear = (close < ef) & ((ef < es) | ~have_slow) & slope_dn

    out = pd.Series(NEUTRAL, index=df.index, dtype=int)
    out = out.mask(bull, BULLISH).mask(bear, BEARISH)
    return out


def latest_trend(df: pd.DataFrame, **kw) -> int:
    s = classify_trend(df, **kw)
    return int(s.iloc[-1]) if len(s) else NEUTRAL


@dataclass
class TrendContext:
    weekly: int
    daily: int
    h4: int

    @property
    def labels(self) -> dict[str, str]:
        return {"weekly": _LABEL[self.weekly], "daily": _LABEL[self.daily],
                "4h": _LABEL[self.h4]}

    def alignment_multiplier(
        self,
        direction: int,
        full_align: float = 1.5,
        conflict: float = 0.5,
        neutral: float = 1.0,
    ) -> float:
        """Score multiplier for a signal of the given ``direction`` (+1/-1).

        - all three timeframes agree with direction -> ``full_align``
        - a higher timeframe opposes the direction  -> ``conflict``
        - otherwise                                 -> ``neutral``
        """
        tfs = [self.weekly, self.daily, self.h4]
        if all(t == direction for t in tfs):
            return full_align
        # weekly/daily are the "higher" context for a 4h/daily signal
        if any(t == -direction for t in (self.weekly, self.daily)):
            return conflict
        return neutral


def build_context(weekly: pd.DataFrame, daily: pd.DataFrame, h4: pd.DataFrame,
                  **kw) -> TrendContext:
    return TrendContext(
        weekly=latest_trend(weekly, **kw),
        daily=latest_trend(daily, **kw),
        h4=latest_trend(h4, **kw),
    )
