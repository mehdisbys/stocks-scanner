"""Backtest simulation and performance metrics.

Model (long-only, one position at a time):

- The scoring engine produces entry/exit signals per bar from data up to
  and including that bar's close.
- To avoid look-ahead, a signal on bar *i* is executed at the **open of
  bar i+1**.
- Costs (fee + slippage, in basis points) are charged on every fill.
- Optional risk exits: a percentage **stop loss** and a **max holding**
  period, in addition to the engine's exit signals.

`win rate` is the primary go-live metric (per the requirements), reported
alongside profit factor, expectancy, max drawdown, CAGR and a buy-&-hold
comparison over the same window.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    bars_held: int
    return_pct: float
    reason: str  # "signal" | "stop" | "max_hold" | "eod"
    # optional per-trade detail (populated when a scoring engine is used)
    entry_score: float = 0.0
    exit_score: float = 0.0
    entry_conditions: str = ""
    exit_conditions: str = ""
    entry_trend_daily: str = ""
    entry_trend_weekly: str = ""


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: pd.Series
    metrics: dict
    buy_hold_return: float
    start: pd.Timestamp
    end: pd.Timestamp

    def report(self, title: str = "") -> str:
        m = self.metrics
        head = f"Backtest {title}".strip()
        return (
            f"{head}\n"
            f"  window:        {self.start.date()} -> {self.end.date()}\n"
            f"  trades:        {m['n_trades']}\n"
            f"  win rate:      {m['win_rate']:.1%}\n"
            f"  profit factor: {m['profit_factor']:.2f}\n"
            f"  expectancy:    {m['expectancy']:+.2%} per trade\n"
            f"  avg win/loss:  {m['avg_win']:+.2%} / {m['avg_loss']:+.2%}\n"
            f"  total return:  {m['total_return']:+.1%}  (CAGR {m['cagr']:+.1%})\n"
            f"  max drawdown:  {m['max_drawdown']:.1%}\n"
            f"  avg hold:      {m['avg_bars_held']:.0f} bars\n"
            f"  buy & hold:    {self.buy_hold_return:+.1%}"
        )


def run_backtest(
    df: pd.DataFrame,
    engine,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    stop_pct: float | None = None,
    max_hold: int | None = None,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    scores: pd.DataFrame | None = None,
    entry_override: pd.Series | None = None,
) -> BacktestResult:
    """Run a long-only backtest of ``engine`` over ``df``.

    Indicators/scores are computed on the FULL series so warm-up history
    is available; trades are only opened within [start, end].
    """
    contrib = None
    if scores is None:
        if hasattr(engine, "score_frames"):
            scores, contrib = engine.score_frames(df)
        else:
            scores = engine.score_series(df)
    o = df["open"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index
    if entry_override is not None:
        entry_sig = entry_override.reindex(idx).fillna(False).to_numpy(bool)
    else:
        entry_sig = scores["entry_signal"].to_numpy(bool)
    exit_sig = scores["exit_signal"].to_numpy(bool)
    entry_score_arr = scores["entry_score"].to_numpy(float)
    exit_score_arr = scores["exit_score"].to_numpy(float)
    cost = (fee_bps + slippage_bps) / 1e4

    # per-trade annotation helpers (no-ops if no engine detail available)
    entry_names = getattr(engine, "entry_condition_names", lambda: [])()
    exit_names = getattr(engine, "exit_condition_names", lambda: [])()

    def _fired_at(i: int, names: list[str]) -> str:
        if contrib is None or not names:
            return ""
        row = contrib.iloc[i]
        return "|".join(n for n in names if n in row.index and row[n] > 0)

    # cheap per-bar trend labels (daily from df, weekly resampled + ffilled)
    from ..indicators.trend import classify_trend, _LABEL
    from ..data.resample import resample as _resample
    from ..data.base import Timeframe as _TF
    trend_d = classify_trend(df).map(_LABEL)
    wk = classify_trend(_resample(df, _TF.W1)).map(_LABEL)
    trend_w = wk.reindex(df.index, method="ffill").fillna("neutral")

    start = pd.Timestamp(start).tz_convert("UTC") if start is not None and pd.Timestamp(start).tzinfo \
        else (pd.Timestamp(start, tz="UTC") if start is not None else idx[0])
    end = pd.Timestamp(end).tz_convert("UTC") if end is not None and pd.Timestamp(end).tzinfo \
        else (pd.Timestamp(end, tz="UTC") if end is not None else idx[-1])

    trades: list[Trade] = []
    position = False
    entry_px = 0.0
    entry_i = 0

    for i in range(len(df) - 1):
        in_window = (idx[i] >= start) and (idx[i] <= end)
        if not position:
            if in_window and entry_sig[i]:
                entry_px = o[i + 1] * (1 + cost)
                entry_i = i + 1
                position = True
                _e_score = float(entry_score_arr[i])
                _e_conds = _fired_at(i, entry_names)
                _e_td = str(trend_d.iloc[i]) if trend_d is not None else ""
                _e_tw = str(trend_w.iloc[i]) if trend_w is not None else ""
        else:
            # exit fills at open[i+1]; that exit would make the hold
            # (i+1 - entry_i) bars, so cap there to honour max_hold exactly.
            stop_hit = stop_pct is not None and c[i] <= entry_px * (1 - stop_pct)
            max_hit = max_hold is not None and (i + 1 - entry_i) >= max_hold
            if exit_sig[i] or stop_hit or max_hit:
                exit_px = o[i + 1] * (1 - cost)
                reason = "stop" if stop_hit else "max_hold" if max_hit else "signal"
                trades.append(Trade(
                    idx[entry_i], idx[i + 1], entry_px, exit_px,
                    i + 1 - entry_i, exit_px / entry_px - 1.0, reason,
                    entry_score=_e_score, exit_score=float(exit_score_arr[i]),
                    entry_conditions=_e_conds,
                    exit_conditions=_fired_at(i, exit_names) if reason == "signal" else reason,
                    entry_trend_daily=_e_td, entry_trend_weekly=_e_tw))
                position = False
    if position:  # mark out any open position at the last close
        exit_px = c[-1] * (1 - cost)
        trades.append(Trade(
            idx[entry_i], idx[-1], entry_px, exit_px,
            len(df) - 1 - entry_i, exit_px / entry_px - 1.0, "eod",
            entry_score=_e_score, entry_conditions=_e_conds,
            exit_conditions="eod", entry_trend_daily=_e_td, entry_trend_weekly=_e_tw))

    metrics, equity = _metrics(trades, idx, start, end)
    bh = float(c[idx.get_indexer([end], method="ffill")[0]] /
               c[idx.get_indexer([start], method="bfill")[0]] - 1.0)
    return BacktestResult(trades, equity, metrics, bh, start, end)


def _metrics(trades: list[Trade], idx: pd.DatetimeIndex,
             start: pd.Timestamp, end: pd.Timestamp) -> tuple[dict, pd.Series]:
    if not trades:
        empty = pd.Series(dtype=float)
        return (
            {"n_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
             "expectancy": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
             "total_return": 0.0, "cagr": 0.0, "max_drawdown": 0.0,
             "avg_bars_held": 0.0},
            empty,
        )
    rets = np.array([t.return_pct for t in trades])
    wins = rets[rets > 0]
    losses = rets[rets <= 0]
    gross_win = wins.sum()
    gross_loss = -losses.sum()
    equity = pd.Series(np.cumprod(1 + rets),
                       index=[t.exit_date for t in trades])
    total_return = float(equity.iloc[-1] - 1.0)
    years = max((end - start).days / 365.25, 1e-9)
    cagr = float((1 + total_return) ** (1 / years) - 1) if total_return > -1 else -1.0
    running_max = equity.cummax()
    max_dd = float(((equity - running_max) / running_max).min())

    return (
        {
            "n_trades": len(trades),
            "win_rate": float(len(wins) / len(trades)),
            "profit_factor": float(gross_win / gross_loss) if gross_loss > 0 else float("inf"),
            "expectancy": float(rets.mean()),
            "avg_win": float(wins.mean()) if len(wins) else 0.0,
            "avg_loss": float(losses.mean()) if len(losses) else 0.0,
            "total_return": total_return,
            "cagr": cagr,
            "max_drawdown": max_dd,
            "avg_bars_held": float(np.mean([t.bars_held for t in trades])),
        },
        equity,
    )
