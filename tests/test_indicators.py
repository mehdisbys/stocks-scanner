"""Ground-truth tests for the indicator modules.

These use small, hand-crafted series where the correct answer is known,
so they verify *logic* (not just that code runs). Run with:

    python -m tests.test_indicators
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from signals.indicators import core, ma_cross, divergence, structure, trend


def _df(opens=None, highs=None, lows=None, closes=None, vols=None):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    idx.name = "ts"
    return pd.DataFrame(
        {
            "open": opens or closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols or [1000.0] * n,
        },
        index=idx,
    )


def check(name, cond):
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


# ---------------------------------------------------------------------------
def test_rsi_extremes():
    up = pd.Series(np.arange(1, 60, dtype=float))
    down = pd.Series(np.arange(60, 1, -1, dtype=float))
    check("RSI all-up -> 100", core.rsi(up).iloc[-1] == 100.0)
    check("RSI all-down -> 0", core.rsi(down).iloc[-1] == 0.0)


def test_ma_golden_cross():
    # Flat then up: fast EMA crosses ABOVE slow exactly once, no death cross.
    closes = [100, 100, 100, 100, 100, 100, 102, 105, 109, 114, 120, 127, 135]
    df = _df(highs=[c + 1 for c in closes], lows=[c - 1 for c in closes], closes=closes)
    mc = ma_cross.ma_cross_signals(df, pairs=[(3, 8)], price_mas=[], kind="ema")
    g = int(mc["golden_3_8"].sum())
    d = int(mc["death_3_8"].sum())
    check("MA golden cross fires exactly once on flat->up", g == 1)
    check("MA death cross does not fire on flat->up", d == 0)


def test_bullish_divergence_confirms():
    # price: lower low (10 -> 8); indicator: higher low (20 -> 26) => bull div.
    # indicator is a LOW at each price low and peaks (40) between them;
    # confirmation = indicator rising back above that interim peak.
    closes = [12, 10, 13, 15, 11, 8, 9, 14, 16]
    highs = [12.5, 10.5, 13.5, 15.5, 11.5, 8.5, 9.5, 14.5, 16.5]
    lows = [11.5, 10.0, 12.5, 14.5, 10.5, 8.0, 8.5, 13.5, 15.5]
    df = _df(highs=highs, lows=lows, closes=closes)
    ind = pd.Series([28, 20, 35, 40, 34, 26, 30, 45, 50], index=df.index, dtype=float)
    st = divergence.divergence_states(df, ind, "bull", left=1, right=1)
    check("bull div becomes potential after 2nd low confirms",
          divergence.POTENTIAL in st.tolist())
    check("bull div confirms when indicator exceeds interim peak",
          divergence.CONFIRMED in st.tolist())


def test_bullish_divergence_invalidates():
    # 2nd low forms as a valid pivot (bounce after it), divergence detected,
    # THEN the indicator falls below the divergence's indicator low -> invalid.
    closes = [12, 10, 13, 15, 11, 8, 10, 9, 7]
    highs = [12.5, 10.5, 13.5, 15.5, 11.5, 8.5, 10.5, 9.5, 7.0]
    lows = [11.5, 10.0, 12.5, 14.5, 10.5, 8.0, 9.5, 8.5, 6.5]
    df = _df(highs=highs, lows=lows, closes=closes)
    ind = pd.Series([28, 20, 35, 40, 34, 26, 24, 22, 18], index=df.index, dtype=float)
    st = divergence.divergence_states(df, ind, "bull", left=1, right=1)
    check("bull div invalidates when indicator drops below its divergence low",
          divergence.INVALIDATED in st.tolist())


def test_double_bottom_confirms():
    # two ~equal lows (10, 10.1) with a peak between, then close breaks neckline.
    closes = [11, 10, 12, 14, 12, 10.1, 11, 15, 16]
    highs = [11.5, 10.5, 12.5, 14.0, 12.5, 10.6, 11.5, 15.5, 16.5]
    lows = [10.8, 10.0, 11.5, 13.0, 11.0, 10.1, 10.9, 14.5, 15.5]
    df = _df(highs=highs, lows=lows, closes=closes)
    st = structure.structure_signals(df, left=1, right=1, level_tol=0.05,
                                     min_sep=2, max_sep=40)
    check("W (double bottom) reaches potential",
          structure.POTENTIAL in st["w_state"].tolist())
    check("W confirms on close above neckline", bool(st["w_confirmed"].any()))


def test_trend_conflict_multiplier():
    weekly = _df(highs=list(range(60, 1, -1)), lows=list(range(58, -1, -1)),
                 closes=list(range(59, 0, -1)))   # strictly down -> bearish
    daily = _df(highs=list(range(2, 61)), lows=list(range(0, 59)),
                closes=list(range(1, 60)))         # strictly up -> bullish
    ctx = trend.build_context(weekly, daily, daily, fast=5, slow=10)
    check("weekly classified bearish", ctx.weekly == trend.BEARISH)
    check("daily classified bullish", ctx.daily == trend.BULLISH)
    # bullish entry under a bearish weekly should be dampened
    check("conflict dampens bullish entry (<1.0)",
          ctx.alignment_multiplier(+1) < 1.0)


def test_squeeze_and_atr_finite():
    closes = list(np.cumsum(np.random.default_rng(1).normal(0, 1, 80)) + 100)
    df = _df(highs=[c + 1 for c in closes], lows=[c - 1 for c in closes], closes=closes)
    sq = core.squeeze_momentum(df)
    a = core.atr(df)
    check("squeeze momentum produces finite tail value",
          np.isfinite(sq["momentum"].iloc[-1]))
    check("ATR positive", a.dropna().gt(0).all())


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} ground-truth tests\n")
    for t in tests:
        t()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
