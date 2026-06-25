"""Explicit AND screens (hard filters), as opposed to the weighted score.

A screen requires *all* of its conditions to hold on the same bar, which
is the right tool for a specific high-conviction setup rather than a
tunable score.
"""

from __future__ import annotations

import pandas as pd

from .indicators.base_consolidation import base_consolidation_signals
from .indicators.divergence import divergence_signals
from .indicators.fibonacci import fibonacci_signals
from .indicators.institutional_bias import institutional_bias_signals
from .indicators.structure import structure_weekly_signals

_ACTIVE_DIV = ("potential", "confirmed")
# "volume" divergence = the volume/money-flow indicators (MFI, CMF, OBV).
_DIV_MAP = {"rsi": "rsi_bull_div", "macd": "macd_bull_div",
            "obv": "obv_bull_div", "mfi": "mfi_bull_div", "cmf": "cmf_bull_div"}


def fib_weeklyW_divergence(
    df: pd.DataFrame,
    div_indicators: tuple[str, ...] = ("rsi", "macd", "obv", "mfi", "cmf"),
    require_ib_bull: bool = False,   # off by default: IB (momentum) hurts this
                                     # reversal setup. Flip True to re-enable.
) -> pd.DataFrame:
    """Setup = price in 0.786 retracement (daily) AND a weekly W present
    AND at least one bullish divergence among the chosen indicators AND
    (optionally) bullish institutional bias (9>18 EMA daily).

    Returns per-bar columns: near_fib_786, weekly_w, div_present, div_list,
    ib_bull, and ``setup`` (the AND of all enabled conditions).
    """
    fib = fibonacci_signals(df)["near_fib_786"]
    wk = structure_weekly_signals(df)["wk_w_state"].isin(["potential", "confirmed"])
    dv = divergence_signals(df)
    ib = institutional_bias_signals(df)["ib_bullish"]

    cols = {name: _DIV_MAP[name] for name in div_indicators if name in _DIV_MAP}
    active = pd.DataFrame(index=df.index)
    for name, col in cols.items():
        active[name] = dv[col].isin(_ACTIVE_DIV) if col in dv.columns else False

    div_present = active.any(axis=1)
    div_list = active.apply(lambda r: "|".join(n for n in active.columns if r[n]), axis=1)

    out = pd.DataFrame({
        "near_fib_786": fib.fillna(False),
        "weekly_w": wk.reindex(df.index).fillna(False),
        "div_present": div_present,
        "div_list": div_list,
        "ib_bull": ib.reindex(df.index).fillna(False),
    })
    setup = out["near_fib_786"] & out["weekly_w"] & out["div_present"]
    if require_ib_bull:
        setup = setup & out["ib_bull"]
    out["setup"] = setup
    return out


def bottom_base(df: pd.DataFrame) -> pd.DataFrame:
    """Beaten-down base near multi-year lows ("not hot" consolidations).

    setup = deep drawdown from the major high AND price near the bottom of
    its multi-year range AND (consolidating OR quietly accumulating).
    """
    b = base_consolidation_signals(df)
    out = b[["range_position", "drawdown_from_high", "yr_change",
             "deep_drawdown", "near_lows", "consolidating", "accumulation"]].copy()
    out["setup"] = (b["deep_drawdown"] & b["near_lows"]
                    & (b["consolidating"] | b["accumulation"]))
    return out
