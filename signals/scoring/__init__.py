"""Phase 2 — the scoring engine.

Turns the indicator modules into weighted, configurable entry/exit
conditions, summed into a score and compared against thresholds, with a
multi-timeframe trend multiplier applied. Driven entirely by YAML so
weights/thresholds can be tuned in the backtest without code changes.
"""
