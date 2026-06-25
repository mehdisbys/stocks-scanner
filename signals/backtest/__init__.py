"""Phase 3 — backtester.

Replays the scoring engine over historical OHLCV, simulates long-only
trades with realistic costs and no look-ahead (signals on bar close are
filled at the next bar's open), and reports performance. Supports a
train/test split and a threshold sweep for tuning the scoring config.
"""
