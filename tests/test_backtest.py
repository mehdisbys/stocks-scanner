"""Ground-truth tests for the backtest simulation.

A dummy engine returns preset entry/exit signals so the trade timing,
next-open fills, cost application and PnL math have exact known answers —
independent of the indicators. Run: python -m tests.test_backtest
"""

from __future__ import annotations

import pandas as pd

from signals.backtest.engine import run_backtest


class DummyEngine:
    """Returns caller-supplied entry/exit signal arrays as score_series."""
    def __init__(self, entry, exit_):
        self.entry = entry
        self.exit_ = exit_

    def score_series(self, df):
        return pd.DataFrame(
            {"entry_score": [0.0] * len(df), "exit_score": [0.0] * len(df),
             "entry_signal": self.entry, "exit_signal": self.exit_},
            index=df.index,
        )


def _df(opens, closes=None):
    n = len(opens)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    idx.name = "ts"
    closes = closes or opens
    return pd.DataFrame(
        {"open": opens, "high": [x + 1 for x in opens], "low": [x - 1 for x in opens],
         "close": closes, "volume": [1.0] * n},
        index=idx,
    )


def check(name, cond):
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def test_single_trade_pnl_with_costs():
    # entry signal at i=1 -> fill at open[2]=100; exit signal at i=4 -> fill at open[5]=110
    opens = [100, 100, 100, 105, 108, 110, 110]
    entry = [False, True, False, False, False, False, False]
    exit_ = [False, False, False, False, True, False, False]
    df = _df(opens)
    res = run_backtest(df, DummyEngine(entry, exit_), fee_bps=10, slippage_bps=5)
    check("exactly one trade", res.metrics["n_trades"] == 1)
    t = res.trades[0]
    cost = 15 / 1e4
    exp_entry = 100 * (1 + cost)
    exp_exit = 110 * (1 - cost)
    check("entry filled at next open + cost", abs(t.entry_price - exp_entry) < 1e-9)
    check("exit filled at next open - cost", abs(t.exit_price - exp_exit) < 1e-9)
    check("return matches manual calc",
          abs(t.return_pct - (exp_exit / exp_entry - 1)) < 1e-12)
    check("winning trade -> win rate 100%", res.metrics["win_rate"] == 1.0)


def test_max_hold_forces_exit():
    opens = [100] * 10
    entry = [False, True] + [False] * 8
    exit_ = [False] * 10                      # never a signal exit
    df = _df(opens)
    res = run_backtest(df, DummyEngine(entry, exit_), fee_bps=0, slippage_bps=0,
                       max_hold=3)
    check("max_hold produced a trade", res.metrics["n_trades"] == 1)
    check("exit reason is max_hold", res.trades[0].reason == "max_hold")
    check("held ~3 bars", res.trades[0].bars_held == 3)


def test_stop_loss_triggers():
    # enter ~100, price falls hard -> 8% stop should fire
    opens = [100, 100, 100, 99, 95, 90, 88]
    closes = [100, 100, 100, 98, 91, 89, 88]
    entry = [False, True, False, False, False, False, False]
    exit_ = [False] * 7
    df = _df(opens, closes)
    res = run_backtest(df, DummyEngine(entry, exit_), fee_bps=0, slippage_bps=0,
                       stop_pct=0.08)
    check("stop produced a trade", res.metrics["n_trades"] == 1)
    check("exit reason is stop", res.trades[0].reason == "stop")
    check("losing trade -> negative return", res.trades[0].return_pct < 0)


def test_no_signals_no_trades():
    df = _df([100] * 6)
    res = run_backtest(df, DummyEngine([False] * 6, [False] * 6))
    check("no trades when no signals", res.metrics["n_trades"] == 0)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} backtest tests\n")
    for t in tests:
        t()
    print("\nALL BACKTEST TESTS PASSED")


if __name__ == "__main__":
    main()
