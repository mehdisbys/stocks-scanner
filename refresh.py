#!/usr/bin/env python3
"""One-command refresh: re-run the scans and rebuild dashboard.html.

Runs the two scans the dashboard consumes — the base+divergence watchlist
(`base_div_sheet_daily.csv`) and the recent-divergence scan
(`recent_div_daily.csv`) — then regenerates `dashboard.html` from them.

Enrichment flags are forwarded to both scans:

    python refresh.py                 # plain scans + dashboard
    python refresh.py --canslim --ai  # add CANSLIM + AI columns (no network)
    python refresh.py --enrich        # CANSLIM + WDB + AI + sector
    python refresh.py --recent-days 30
    python refresh.py --weekly        # also weekly tabs
    python refresh.py --h4            # also a 4h tab (needs Polygon intraday cache)
    python refresh.py --crypto        # also Crypto tabs (needs Binance cache; see populate_crypto.py)

The dashboard reads CANSLIM/WDB straight from these CSVs when the columns are
present, so enriching here keeps the dashboard in sync automatically.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def _run(cmd: list[str]) -> None:
    print("→", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="refresh",
                                 description="Re-scan and rebuild dashboard.html")
    ap.add_argument("--canslim", action="store_true",
                    help="Trend column (price>SMA20/50/200 & RSI>50)")
    ap.add_argument("--canslim-real", action="store_true",
                    help="real CANSLIM column (C/A/N/L/I/M fundamentals); "
                         "stocks only, needs yfinance + internet")
    ap.add_argument("--wdb", action="store_true", help="needs yfinance + internet")
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--enrich", action="store_true",
                    help="shortcut for --canslim --canslim-real --wdb --ai")
    ap.add_argument("--recent-days", type=int, default=20,
                    help="window (trading bars) for the daily recent-divergence scan")
    ap.add_argument("--weekly", action="store_true",
                    help="also run the weekly scans (adds Weekly tabs to the dashboard)")
    ap.add_argument("--weekly-days", type=int, default=8,
                    help="window (weekly bars) for the weekly recent-divergence scan")
    ap.add_argument("--h4", action="store_true",
                    help="also run the 4h recent-divergence scan (adds a 4h tab); "
                         "needs the Polygon intraday cache — see README")
    ap.add_argument("--h4-days", type=int, default=30,
                    help="window (4h bars) for the 4h recent-divergence scan")
    ap.add_argument("--crypto", action="store_true",
                    help="also run the crypto recent-divergence scans (daily/weekly/4h) "
                         "over the top Binance pairs (adds Crypto tabs); needs the "
                         "binance cache — see populate_crypto.py")
    args = ap.parse_args(argv)

    enrich = [flag for flag, on in (
        ("--canslim", args.canslim or args.enrich),
        ("--canslim-real", args.canslim_real or args.enrich),
        ("--wdb", args.wdb or args.enrich),
        ("--ai", args.ai or args.enrich),
    ) if on]

    # --history is always on from refresh: each run is a data point for
    # first/last-seen tracking, which powers the "New today" flag.
    common = enrich + ["--history"]
    scan = [sys.executable, "-m", "signals.scan_base_div"]
    # --- daily ---
    # 1) base + divergence watchlist  -> base_div_sheet_daily.csv (the default --out)
    _run(scan + ["--out", "base_div_sheet_daily.csv"] + common)
    # 2) recent divergences (no base) -> recent_div_daily.csv
    _run(scan + ["--no-base", "--timeframe", "daily",
                 "--recent-days", str(args.recent_days),
                 "--out", "recent_div_daily.csv"] + common)
    # --- weekly (optional) ---
    if args.weekly:
        # 3) weekly base + divergence -> base_div_sheet.csv
        _run(scan + ["--timeframe", "weekly", "--recent-days", str(args.weekly_days),
                     "--out", "base_div_sheet.csv"] + common)
        # 4) weekly recent divergences -> recent_div_weekly.csv
        _run(scan + ["--no-base", "--timeframe", "weekly",
                     "--recent-days", str(args.weekly_days),
                     "--out", "recent_div_weekly.csv"] + common)
    # --- 4h intraday (optional) ---
    if args.h4:
        # 5) 4h recent divergences -> recent_div_4h.csv (base scan skipped:
        #    base thresholds are calibrated for daily bars)
        _run(scan + ["--no-base", "--timeframe", "4h",
                     "--recent-days", str(args.h4_days),
                     "--out", "recent_div_4h.csv"] + common)
    # --- crypto (optional) ---
    if args.crypto:
        # Crypto scans run off the Binance cache. WDB/sector are equity-only and
        # are silently ignored for crypto (CANSLIM/AI still apply).
        cbase = ["--universe", "crypto", "--no-base"] + common
        # 6) crypto daily recent -> recent_div_crypto_daily.csv
        _run(scan + cbase + ["--timeframe", "daily",
                             "--recent-days", str(args.recent_days),
                             "--out", "recent_div_crypto_daily.csv"])
        # 7) crypto weekly recent -> recent_div_crypto_weekly.csv
        _run(scan + cbase + ["--timeframe", "weekly",
                             "--recent-days", str(args.weekly_days),
                             "--out", "recent_div_crypto_weekly.csv"])
        # 8) crypto 4h recent -> recent_div_crypto_4h.csv
        _run(scan + cbase + ["--timeframe", "4h",
                             "--recent-days", str(args.h4_days),
                             "--out", "recent_div_crypto_4h.csv"])
    # rebuild the dashboard from the refreshed CSVs (weekly/4h/crypto tabs appear if present)
    _run([sys.executable, "build_dashboard.py"])
    print("\ndashboard.html refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
