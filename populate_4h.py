#!/usr/bin/env python3
"""Populate the intraday (4h) cache from Polygon for the whole scan universe.

4h bars are resampled from Polygon 1h data and can't be derived from the daily
cache, so they must be fetched once per symbol. The free Polygon tier is
rate-limited (~5 calls/min), so a full-universe pull takes ~1.5-2h.

This script is **resumable**: symbols that already have enough fresh 4h bars are
skipped, so you can stop it (Ctrl-C) and re-run anytime and it picks up where it
left off. Run this once, then scan with `--timeframe 4h` (or `refresh.py --h4`).

    python populate_4h.py                 # full universe, ~120 days back (~2h)
    python populate_4h.py --days 180      # deeper history
    python populate_4h.py --universe sp500
    python populate_4h.py --symbols AAPL MSFT NVDA
    python populate_4h.py --force         # re-fetch even if already cached
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from signals.config import Config
from signals.data.base import AssetClass, Timeframe
from signals.data.service import DataService
from signals.data.universe import get_sp500
from signals.progress import track
from signals.scan_base_div import load_broader

MIN_BARS = 120  # a symbol with at least this many cached 4h bars is "done"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="populate_4h",
        description="Fetch + cache 4h intraday bars (Polygon 1h -> 4h) for the universe")
    ap.add_argument("--universe", default="all", choices=["all", "sp500", "broader"])
    ap.add_argument("--symbols", nargs="*",
                    help="explicit symbol list (overrides --universe)")
    ap.add_argument("--days", type=int, default=120, help="history depth to fetch")
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even if the symbol is already cached")
    args = ap.parse_args(argv)

    svc = DataService(Config.load())

    if args.symbols:
        syms = args.symbols
    else:
        syms = []
        if args.universe in ("all", "sp500"):
            syms += get_sp500()
        if args.universe in ("all", "broader"):
            syms += load_broader()
        syms = list(dict.fromkeys(syms))  # de-dupe, keep order

    start = pd.Timestamp.utcnow() - pd.Timedelta(days=args.days)
    interval = getattr(svc.polygon, "_min_interval", 12.0)
    eta_min = len(syms) * interval / 60.0
    print(f"{len(syms)} symbols · up to ~{eta_min:.0f} min at Polygon's rate limit\n"
          f"(resumable: already-cached names are skipped — safe to stop and re-run)\n")

    done = skipped = failed = 0
    for sym in track(syms, desc="4h pull", label=lambda s: s):
        if not args.force:
            cached = svc.get(AssetClass.STOCK, sym, Timeframe.H4, source="polygon")
            if len(cached) >= MIN_BARS:
                skipped += 1
                continue
        try:
            svc.update_stock_live(sym, Timeframe.H4, start=start)
            done += 1
        except Exception as e:  # noqa: BLE001 — keep going, report at the end
            failed += 1
            print(f"  {sym}: FAILED ({e})", file=sys.stderr)

    print(f"\ndone: {done} fetched · {skipped} already cached · {failed} failed")
    if done or skipped:
        print("next: python refresh.py --h4      # runs the 4h scan + rebuilds dashboard.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
