"""Portfolio (multi-symbol) backtest aggregation.

Runs the scoring engine across many symbols and aggregates the results
two ways:

1. **Pooled trades** — treat every trade from every symbol as one sample.
   This directly answers "does the strategy have a positive edge across
   the universe" (pooled win rate, profit factor, expectancy).
2. **Per-symbol distribution** — median strategy return, fraction of
   symbols profitable, and fraction that beat their own buy-&-hold.

A scanner is used by taking individual signals, so pooled-trade stats are
the natural headline; a fully capital-constrained portfolio equity curve
(concurrent positions, sizing) is a later refinement.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..scoring.engine import ScoringConfig, ScoringEngine
from .engine import run_backtest


def run_portfolio(
    data: dict[str, pd.DataFrame],
    config: ScoringConfig,
    **bt_kwargs,
) -> dict:
    engine = ScoringEngine(config)
    pooled_returns: list[float] = []
    per_symbol: list[dict] = []

    for sym, df in data.items():
        if df is None or len(df) < 250:
            continue
        res = run_backtest(df, engine, **bt_kwargs)
        rets = [t.return_pct for t in res.trades]
        pooled_returns.extend(rets)
        per_symbol.append({
            "symbol": sym,
            "n_trades": res.metrics["n_trades"],
            "win_rate": res.metrics["win_rate"],
            "total_return": res.metrics["total_return"],
            "max_drawdown": res.metrics["max_drawdown"],
            "buy_hold": res.buy_hold_return,
            "beat_bh": res.metrics["total_return"] > res.buy_hold_return,
        })

    pooled = np.array(pooled_returns)
    wins = pooled[pooled > 0]
    losses = pooled[pooled <= 0]
    psym = pd.DataFrame(per_symbol)

    agg = {
        "symbols": len(psym),
        "pooled_trades": int(pooled.size),
        "pooled_win_rate": float((pooled > 0).mean()) if pooled.size else 0.0,
        "pooled_profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "pooled_expectancy": float(pooled.mean()) if pooled.size else 0.0,
        "avg_win": float(wins.mean()) if wins.size else 0.0,
        "avg_loss": float(losses.mean()) if losses.size else 0.0,
        "median_symbol_return": float(psym["total_return"].median()) if len(psym) else 0.0,
        "pct_symbols_profitable": float((psym["total_return"] > 0).mean()) if len(psym) else 0.0,
        "pct_symbols_beat_bh": float(psym["beat_bh"].mean()) if len(psym) else 0.0,
        "avg_symbol_return": float(psym["total_return"].mean()) if len(psym) else 0.0,
        "avg_buy_hold": float(psym["buy_hold"].mean()) if len(psym) else 0.0,
    }
    return {"aggregate": agg, "per_symbol": psym}


def report_portfolio(result: dict, title: str = "") -> str:
    a = result["aggregate"]
    return (
        f"Portfolio backtest {title}".strip() + "\n"
        f"  symbols:              {a['symbols']}\n"
        f"  pooled trades:        {a['pooled_trades']}\n"
        f"  pooled win rate:      {a['pooled_win_rate']:.1%}\n"
        f"  pooled profit factor: {a['pooled_profit_factor']:.2f}\n"
        f"  pooled expectancy:    {a['pooled_expectancy']:+.2%} per trade\n"
        f"  avg win / avg loss:   {a['avg_win']:+.2%} / {a['avg_loss']:+.2%}\n"
        f"  symbols profitable:   {a['pct_symbols_profitable']:.0%}\n"
        f"  symbols beat B&H:     {a['pct_symbols_beat_bh']:.0%}\n"
        f"  median symbol return: {a['median_symbol_return']:+.1%}\n"
        f"  avg symbol return:    {a['avg_symbol_return']:+.1%}  "
        f"(avg buy & hold {a['avg_buy_hold']:+.1%})"
    )
