"""Train/test split and threshold sweep for tuning the scoring config.

The split holds out the most recent slice as out-of-sample so a config
tuned on the older (in-sample) period can be checked for overfitting on
data it never saw.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pandas as pd

from ..scoring.engine import ScoringConfig, ScoringEngine
from .engine import BacktestResult, run_backtest


def split_backtest(
    df: pd.DataFrame,
    config: ScoringConfig,
    split_date: str | pd.Timestamp,
    **bt_kwargs,
) -> tuple[BacktestResult, BacktestResult]:
    """Backtest in-sample (before split) and out-of-sample (from split)."""
    engine = ScoringEngine(config)
    scores = engine.score_series(df)            # compute once, reuse
    split = pd.Timestamp(split_date, tz="UTC") if not pd.Timestamp(split_date).tzinfo \
        else pd.Timestamp(split_date).tz_convert("UTC")
    in_s = run_backtest(df, engine, scores=scores, end=split - pd.Timedelta(days=1),
                        **bt_kwargs)
    out_s = run_backtest(df, engine, scores=scores, start=split, **bt_kwargs)
    return in_s, out_s


def sweep_thresholds(
    df: pd.DataFrame,
    config: ScoringConfig,
    entry_values: list[float],
    exit_values: list[float],
    **bt_kwargs,
) -> pd.DataFrame:
    """Grid over entry/exit thresholds; one metrics row per combination.

    Note: thresholds change which signals fire, so scores are re-evaluated
    per entry/exit combo (cheap — the indicator bundle is recomputed once
    per engine, dominated by the threshold comparison).
    """
    rows = []
    for et in entry_values:
        for xt in exit_values:
            cfg = replace(config, entry_threshold=et, exit_threshold=xt)
            res = run_backtest(df, ScoringEngine(cfg), **bt_kwargs)
            m = res.metrics
            rows.append({
                "entry_thr": et, "exit_thr": xt,
                "n_trades": m["n_trades"], "win_rate": m["win_rate"],
                "profit_factor": m["profit_factor"],
                "expectancy": m["expectancy"],
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
            })
    return pd.DataFrame(rows)
