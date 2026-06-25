"""Scoring engine.

A *condition* references a column from an indicator module and fires when
that column meets a test (truthy, or a comparison). Each fired condition
adds its weight to the entry (bullish) or exit (bearish) score. The
summed scores get a multi-timeframe trend multiplier, then compare
against thresholds to produce entry/exit signals — with a full breakdown
of which conditions fired and by how much.

Everything (conditions, weights, thresholds, trend multipliers) is loaded
from YAML, so tuning never touches code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ..indicators.trend import TrendContext
from .bundle import IndicatorBundle

_OPS = {
    "truthy": lambda s, v: s.fillna(False).astype(bool) if s.dtype != object
    else s.notna() & (s != "none") & (s != False),  # noqa: E712
    "eq": lambda s, v: s == v,
    "ne": lambda s, v: s != v,
    "ge": lambda s, v: pd.to_numeric(s, errors="coerce") >= v,
    "gt": lambda s, v: pd.to_numeric(s, errors="coerce") > v,
    "le": lambda s, v: pd.to_numeric(s, errors="coerce") <= v,
    "lt": lambda s, v: pd.to_numeric(s, errors="coerce") < v,
}

ENTRY, EXIT = "entry", "exit"


@dataclass
class Condition:
    name: str
    module: str
    column: str
    side: str          # "entry" (bullish) or "exit" (bearish)
    weight: float
    op: str = "truthy"
    value: Any = None

    def fired(self, bundle: IndicatorBundle) -> pd.Series:
        s = bundle.column(self.module, self.column)
        return _OPS[self.op](s, self.value).fillna(False)


@dataclass
class ScoringConfig:
    entry_threshold: float = 6.0
    exit_threshold: float = 5.0
    trend_enabled: bool = True
    trend_full_align: float = 1.5
    trend_conflict: float = 0.5
    conditions: list[Condition] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScoringConfig":
        sc = d.get("scoring", d)
        tctx = sc.get("trend_context", {})
        # master on/off per indicator module (unlisted -> enabled)
        modules = sc.get("modules", {})
        # optional per-module weight multiplier (unlisted -> 1.0); lets you
        # scale a whole indicator group without editing each condition
        module_weights = sc.get("module_weights", {})
        conds = []
        for c in sc.get("conditions", []):
            # skip if the condition is individually disabled, or its module
            # is switched off in the `modules:` block
            if c.get("enabled", True) is False:
                continue
            if modules.get(c["module"], True) is False:
                continue
            match = c.get("match", "truthy")
            if isinstance(match, str):
                op, value = match, None
            else:  # {op: value}
                (op, value), = match.items()
            weight = float(c["weight"]) * float(module_weights.get(c["module"], 1.0))
            conds.append(Condition(
                name=c["name"], module=c["module"], column=c["column"],
                side=c.get("side", ENTRY), weight=weight,
                op=op, value=value,
            ))
        return cls(
            entry_threshold=float(sc.get("entry_threshold", 6.0)),
            exit_threshold=float(sc.get("exit_threshold", 5.0)),
            trend_enabled=bool(tctx.get("enabled", True)),
            trend_full_align=float(tctx.get("full_align", 1.5)),
            trend_conflict=float(tctx.get("conflict", 0.5)),
            conditions=conds,
        )

    @classmethod
    def load(cls, path: str | Path = "scoring.yaml") -> "ScoringConfig":
        p = Path(path)
        if not p.exists():
            return cls(conditions=_DEFAULT_CONDITIONS())
        data = yaml.safe_load(p.read_text()) or {}
        cfg = cls.from_dict(data)
        if not cfg.conditions:
            cfg.conditions = _DEFAULT_CONDITIONS()
        return cfg


@dataclass
class ScoreResult:
    timestamp: pd.Timestamp
    entry_score: float
    exit_score: float
    entry_signal: bool
    exit_signal: bool
    trend_multiplier: float
    trend_labels: dict[str, str]
    entry_breakdown: dict[str, float]
    exit_breakdown: dict[str, float]

    def summary(self) -> str:
        ec = ", ".join(f"{k}+{v:g}" for k, v in self.entry_breakdown.items()) or "—"
        xc = ", ".join(f"{k}+{v:g}" for k, v in self.exit_breakdown.items()) or "—"
        return (
            f"{self.timestamp:%Y-%m-%d} | ENTRY {self.entry_score:.1f}"
            f"{' SIGNAL' if self.entry_signal else ''} "
            f"| EXIT {self.exit_score:.1f}{' SIGNAL' if self.exit_signal else ''} "
            f"| trend x{self.trend_multiplier:g} {self.trend_labels}\n"
            f"   entry: {ec}\n   exit:  {xc}"
        )


class ScoringEngine:
    def __init__(self, config: ScoringConfig | None = None):
        self.cfg = config or ScoringConfig(conditions=_DEFAULT_CONDITIONS())

    # -- per-bar scores across the whole series (used by the backtester) ----

    def score_series(self, df: pd.DataFrame) -> pd.DataFrame:
        return self.score_frames(df)[0]

    def score_frames(self, df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return (scores, contributions).

        ``scores`` has entry_score/exit_score + entry_signal/exit_signal per
        bar. ``contributions`` has one column per condition holding its
        weighted contribution (0 when not fired) — used to annotate which
        conditions drove each trade.
        """
        bundle = IndicatorBundle(df)
        entry = pd.Series(0.0, index=df.index)
        exit_ = pd.Series(0.0, index=df.index)
        contribs: dict[str, pd.Series] = {}
        for c in self.cfg.conditions:
            contrib = c.fired(bundle).astype(float) * c.weight
            contribs[c.name] = contrib
            if c.side == ENTRY:
                entry = entry.add(contrib, fill_value=0.0)
            else:
                exit_ = exit_.add(contrib, fill_value=0.0)
        out = pd.DataFrame({"entry_score": entry, "exit_score": exit_})
        out["entry_signal"] = out["entry_score"] >= self.cfg.entry_threshold
        out["exit_signal"] = out["exit_score"] >= self.cfg.exit_threshold
        return out, pd.DataFrame(contribs, index=df.index)

    def entry_condition_names(self) -> list[str]:
        return [c.name for c in self.cfg.conditions if c.side == ENTRY]

    def exit_condition_names(self) -> list[str]:
        return [c.name for c in self.cfg.conditions if c.side == EXIT]

    # -- single-bar evaluation with trend multiplier (used live) ------------

    def evaluate(self, df: pd.DataFrame, trend: TrendContext | None = None,
                 at: int = -1) -> ScoreResult:
        bundle = IndicatorBundle(df)
        ts = df.index[at]
        entry_bd: dict[str, float] = {}
        exit_bd: dict[str, float] = {}
        for c in self.cfg.conditions:
            if bool(c.fired(bundle).iloc[at]):
                (entry_bd if c.side == ENTRY else exit_bd)[c.name] = c.weight

        entry_score = sum(entry_bd.values())
        exit_score = sum(exit_bd.values())

        mult_entry = mult_exit = 1.0
        labels: dict[str, str] = {}
        if self.cfg.trend_enabled and trend is not None:
            labels = trend.labels
            mult_entry = trend.alignment_multiplier(
                +1, self.cfg.trend_full_align, self.cfg.trend_conflict)
            mult_exit = trend.alignment_multiplier(
                -1, self.cfg.trend_full_align, self.cfg.trend_conflict)

        entry_score *= mult_entry
        exit_score *= mult_exit
        return ScoreResult(
            timestamp=ts,
            entry_score=entry_score,
            exit_score=exit_score,
            entry_signal=entry_score >= self.cfg.entry_threshold,
            exit_signal=exit_score >= self.cfg.exit_threshold,
            trend_multiplier=mult_entry,
            trend_labels=labels,
            entry_breakdown=entry_bd,
            exit_breakdown=exit_bd,
        )


def _DEFAULT_CONDITIONS() -> list[Condition]:
    """Starter weights (tuned later in the backtest). C(...) shorthand."""
    def C(name, module, column, side, weight, op="truthy", value=None):
        return Condition(name, module, column, side, weight, op, value)

    return [
        # --- ENTRY (bullish) ---
        C("macd_cross_up", "macd_rsi", "macd_cross_up", ENTRY, 2.0),
        C("macd_hist_rising", "macd_rsi", "macd_hist_rising", ENTRY, 0.5),
        C("rsi_rising_from_oversold", "macd_rsi", "rsi_rising_from_oversold", ENTRY, 1.5),
        C("rsi_cross_50_up", "macd_rsi", "rsi_cross_50_up", ENTRY, 1.0),
        C("golden_50_200", "ma_cross", "golden_50_200", ENTRY, 2.5),
        C("golden_20_50", "ma_cross", "golden_20_50", ENTRY, 1.5),
        C("price_reclaims_200", "ma_cross", "price_above_200", ENTRY, 1.0),
        C("w_confirmed", "structure", "w_state", ENTRY, 3.0, "eq", "confirmed"),
        C("w_potential", "structure", "w_state", ENTRY, 1.0, "eq", "potential"),
        # Weekly W (double bottom) — DOUBLE the weight of daily structure.
        C("weekly_w_confirmed", "structure_weekly", "wk_w_state", ENTRY, 6.0, "eq", "confirmed"),
        C("weekly_w_potential", "structure_weekly", "wk_w_state", ENTRY, 2.0, "eq", "potential"),
        C("breakout_up", "structure", "breakout_up", ENTRY, 1.5),
        C("uptrend_structure", "structure", "structure_trend", ENTRY, 0.5, "ge", 1),
        C("td_buy_setup_9", "td", "buy_setup", ENTRY, 2.0, "ge", 9),
        C("td_buy_countdown_13", "td", "buy_countdown", ENTRY, 3.0, "ge", 13),
        C("bull_div_confirmed", "divergence", "bull_div_confirmed_any", ENTRY, 2.5),
        C("bull_div_potential", "divergence", "bull_div_potential_n", ENTRY, 1.0, "ge", 1),
        C("fib_786_pullback", "fibonacci", "near_fib_786", ENTRY, 1.0),
        # Beaten-down base near multi-year lows (consolidating / accumulating)
        C("base_consolidating_low", "base", "base_setup", ENTRY, 2.5),
        C("base_accumulating_low", "base", "base_accumulating", ENTRY, 1.5),
        C("near_multiyear_lows", "base", "near_lows", ENTRY, 1.0),
        C("institutional_bias_bull", "institutional_bias", "ib_bullish", ENTRY, 1.0),
        C("ib_long_location", "institutional_bias", "ib_long_location", ENTRY, 2.0),
        C("rvol_up_day", "volume", "rvol_up_day", ENTRY, 1.0),
        C("obv_rising", "volume", "obv_rising", ENTRY, 0.5),
        C("buying_pressure", "volume", "buying_pressure", ENTRY, 0.5),
        # --- EXIT (bearish) ---
        C("macd_cross_down", "macd_rsi", "macd_cross_down", EXIT, 2.0),
        C("rsi_falling_from_overbought", "macd_rsi", "rsi_falling_from_overbought", EXIT, 1.5),
        C("rsi_cross_50_down", "macd_rsi", "rsi_cross_50_down", EXIT, 1.0),
        C("death_50_200", "ma_cross", "death_50_200", EXIT, 2.5),
        C("death_20_50", "ma_cross", "death_20_50", EXIT, 1.5),
        C("price_loses_200", "ma_cross", "price_below_200", EXIT, 1.0),
        C("m_confirmed", "structure", "m_state", EXIT, 3.0, "eq", "confirmed"),
        # Weekly M (double top) — DOUBLE the weight of daily structure.
        C("weekly_m_confirmed", "structure_weekly", "wk_m_state", EXIT, 6.0, "eq", "confirmed"),
        C("weekly_m_potential", "structure_weekly", "wk_m_state", EXIT, 2.0, "eq", "potential"),
        C("breakout_down", "structure", "breakout_down", EXIT, 1.5),
        C("td_sell_setup_9", "td", "sell_setup", EXIT, 2.0, "ge", 9),
        C("td_sell_countdown_13", "td", "sell_countdown", EXIT, 3.0, "ge", 13),
        C("bear_div_confirmed", "divergence", "bear_div_confirmed_any", EXIT, 2.5),
        C("selling_pressure", "volume", "selling_pressure", EXIT, 0.5),
        C("institutional_bias_bear", "institutional_bias", "ib_bearish", EXIT, 1.0),
        C("ib_short_location", "institutional_bias", "ib_short_location", EXIT, 2.0),
    ]
