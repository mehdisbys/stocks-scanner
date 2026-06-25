"""Indicator implementations (pure functions over OHLCV DataFrames).

Each module computes an indicator and returns a DataFrame aligned to the
input index. The Phase-2 scoring engine will wrap these as scored
conditions; keeping them pure and standalone makes them easy to test.
"""
