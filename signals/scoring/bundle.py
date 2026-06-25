"""Indicator bundle — compute every indicator output once per DataFrame.

The scoring engine references indicator columns by ``module`` name; this
bundle maps each module name to its compute function and caches the
resulting DataFrame so a module is never recomputed within one evaluation.
"""

from __future__ import annotations

import pandas as pd

from ..indicators import (
    base_consolidation,
    divergence,
    fibonacci,
    institutional_bias,
    ma_cross,
    macd_rsi,
    structure,
    td_sequential,
    volume_momentum,
)

# module name (used in scoring.yaml) -> function(df) -> DataFrame
MODULES = {
    "macd_rsi": macd_rsi.macd_rsi_signals,
    "ma_cross": ma_cross.ma_cross_signals,
    "divergence": divergence.divergence_signals,
    "structure": structure.structure_signals,
    "structure_weekly": structure.structure_weekly_signals,
    "volume": volume_momentum.volume_momentum_signals,
    "td": td_sequential.td_sequential,
    "fibonacci": fibonacci.fibonacci_signals,
    "institutional_bias": institutional_bias.institutional_bias_signals,
    "base": base_consolidation.base_consolidation_signals,
}


class IndicatorBundle:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self._cache: dict[str, pd.DataFrame] = {}

    def get(self, module: str) -> pd.DataFrame:
        if module not in MODULES:
            raise KeyError(f"unknown indicator module: {module!r} "
                           f"(known: {list(MODULES)})")
        if module not in self._cache:
            self._cache[module] = MODULES[module](self.df)
        return self._cache[module]

    def column(self, module: str, column: str) -> pd.Series:
        frame = self.get(module)
        if column not in frame.columns:
            raise KeyError(f"{module!r} has no column {column!r} "
                           f"(has: {list(frame.columns)})")
        return frame[column]
