"""Ground-truth tests for the scoring engine.

Uses a controlled series (a clean 9-bar TD buy setup) and a minimal
config so the score, threshold crossing and trend multiplier have known
answers. Run with:  python -m tests.test_scoring
"""

from __future__ import annotations

import pandas as pd

from signals.indicators.trend import TrendContext
from signals.scoring.engine import Condition, ScoringConfig, ScoringEngine, ENTRY


def _df(closes):
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="D", tz="UTC")
    idx.name = "ts"
    return pd.DataFrame(
        {"open": closes, "high": [c + 1 for c in closes],
         "low": [c - 1 for c in closes], "close": closes,
         "volume": [1000.0] * len(closes)},
        index=idx,
    )


def check(name, cond):
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


# A clean declining run -> TD buy_setup reaches 9 at index 12.
CLOSES = [100, 100, 100, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91]


def test_condition_fires_and_crosses_threshold():
    df = _df(CLOSES)
    cfg = ScoringConfig(
        entry_threshold=6.0, exit_threshold=5.0, trend_enabled=False,
        conditions=[Condition("td9", "td", "buy_setup", ENTRY, 7.0, "ge", 9)],
    )
    eng = ScoringEngine(cfg)
    res = eng.evaluate(df, at=12)  # the bar where buy_setup == 9
    check("condition fires at setup-9 bar", "td9" in res.entry_breakdown)
    check("entry score equals weight (7.0)", res.entry_score == 7.0)
    check("entry signal true above threshold", res.entry_signal is True)


def test_below_threshold_no_signal():
    df = _df(CLOSES)
    cfg = ScoringConfig(
        entry_threshold=6.0, trend_enabled=False,
        conditions=[Condition("td9", "td", "buy_setup", ENTRY, 4.0, "ge", 9)],
    )
    res = ScoringEngine(cfg).evaluate(df, at=12)
    check("score below threshold -> no signal", res.entry_signal is False)


def test_trend_conflict_dampens_signal():
    df = _df(CLOSES)
    cfg = ScoringConfig(
        entry_threshold=6.0, trend_enabled=True,
        trend_full_align=1.5, trend_conflict=0.5,
        conditions=[Condition("td9", "td", "buy_setup", ENTRY, 7.0, "ge", 9)],
    )
    eng = ScoringEngine(cfg)
    # weekly bearish vs a bullish entry -> x0.5 -> 3.5 < 6 -> suppressed
    conflict = TrendContext(weekly=-1, daily=1, h4=1)
    res = eng.evaluate(df, trend=conflict, at=12)
    check("conflict multiplier applied (x0.5)", res.trend_multiplier == 0.5)
    check("counter-trend entry suppressed", res.entry_signal is False)
    # full alignment -> x1.5 -> 10.5 -> signal stands
    aligned = TrendContext(weekly=1, daily=1, h4=1)
    res2 = eng.evaluate(df, trend=aligned, at=12)
    check("aligned multiplier boosts (x1.5)", res2.trend_multiplier == 1.5)
    check("aligned entry signal holds", res2.entry_signal is True)


def test_score_series_shape():
    df = _df(CLOSES)
    eng = ScoringEngine(ScoringConfig.load("scoring.yaml"))
    ss = eng.score_series(df)
    check("score_series has expected columns",
          set(ss.columns) == {"entry_score", "exit_score", "entry_signal", "exit_signal"})
    check("score_series aligned to input", len(ss) == len(df))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} scoring tests\n")
    for t in tests:
        t()
    print("\nALL SCORING TESTS PASSED")


if __name__ == "__main__":
    main()
