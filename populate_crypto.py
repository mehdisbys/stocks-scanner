#!/usr/bin/env python3
"""Populate the crypto OHLCV cache from Binance for the whole crypto universe.

Fetches daily, weekly (resampled from daily), and 4h candles for the top
Binance USDT pairs (``signals.data.universe.TOP_CRYPTO``) so the base+div scan
can run with ``--universe crypto``. Binance's public endpoint is free and only
lightly rate-limited, so a full pull of the ~30-pair universe takes ~1 minute.

This script is **resumable**: a symbol/timeframe that already has enough cached
bars is skipped, so it's safe to Ctrl-C and re-run. Run it once, then scan with
``--universe crypto`` (or ``refresh.py --crypto``).

    python populate_crypto.py                     # full crypto universe, all TFs
    python populate_crypto.py --days 900          # deeper daily/4h history
    python populate_crypto.py --symbols BTCUSDT ETHUSDT
    python populate_crypto.py --timeframes daily 4h
    python populate_crypto.py --force             # re-fetch even if cached
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from signals.config import Config
from signals.data.base import AssetClass, Timeframe
from signals.data.service import DataService
from signals.data.universe import get_crypto_universe
from signals.progress import track

# A symbol/timeframe with at least this many cached bars counts as "done".
MIN_BARS = {"daily": 200, "weekly": 60, "4h": 120}
_TF = {"daily": Timeframe.D1, "weekly": Timeframe.W1, "4h": Timeframe.H4}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="populate_crypto",
        description="Fetch + cache Binance crypto candles (daily/weekly/4h) for the universe")
    ap.add_argument("--symbols", nargs="*",
                    help="explicit Binance pairs (e.g. BTCUSDT); overrides the universe")
    ap.add_argument("--timeframes", nargs="*", default=["daily", "weekly", "4h"],
                    choices=["daily", "weekly", "4h"],
                    help="which timeframes to populate (default: all three)")
    ap.add_argument("--days", type=int, default=900,
                    help="history depth to fetch for daily/4h (weekly is resampled from daily)")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if the symbol/timeframe is already cached")
    args = ap.parse_args(argv)

    svc = DataService(Config.load())
    syms = args.symbols or get_crypto_universe()
    syms = list(dict.fromkeys(syms))  # de-dupe, keep order

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=args.days)
    print(f"{len(syms)} pairs × {len(args.timeframes)} timeframes "
          f"({', '.join(args.timeframes)}) from Binance\n"
          f"(resumable: already-cached names are skipped — safe to stop and re-run)\n")

    done = skipped = failed = 0
    for sym in track(syms, desc="crypto pull", label=lambda s: s):
        for tf_name in args.timeframes:
            tf = _TF[tf_name]
            if not args.force:
                cached = svc.get(AssetClass.CRYPTO, sym, tf, source="binance")
                if len(cached) >= MIN_BARS[tf_name]:
                    skipped += 1
                    continue
            try:
                # Weekly needs the daily cache present first (it's resampled),
                # so seed daily before resampling when populating weekly alone.
                svc.update_crypto(sym, tf, start=start)
                done += 1
            except Exception as e:  # noqa: BLE001 — keep going, report at the end
                failed += 1
                print(f"  {sym}/{tf_name}: FAILED ({e})", file=sys.stderr)

    print(f"\ndone: {done} fetched · {skipped} already cached · {failed} failed")
    if done or skipped:
        print("next: python refresh.py --crypto   # runs the crypto scans + rebuilds dashboard.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
