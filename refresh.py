#!/usr/bin/env python3
"""One-command refresh: re-run the scans and rebuild dashboard.html.

Runs the two scans the dashboard consumes — the base+divergence watchlist
(`base_div_sheet_daily.csv`) and the recent-divergence scan
(`recent_div_daily.csv`) — then regenerates `dashboard.html` from them.

Enrichment flags are forwarded to both scans:

    python refresh.py                 # plain scans + dashboard
    python refresh.py --canslim --ai  # add CANSLIM + AI columns (no network)
    python refresh.py --enrich        # CANSLIM + WDB + AI (WDB needs internet)
    python refresh.py --recent-days 30

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
    ap.add_argument("--canslim", action="store_true")
    ap.add_argument("--wdb", action="store_true", help="needs yfinance + internet")
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--enrich", action="store_true",
                    help="shortcut for --canslim --wdb --ai")
    ap.add_argument("--recent-days", type=int, default=20,
                    help="window (trading bars) for the daily recent-divergence scan")
    ap.add_argument("--weekly", action="store_true",
                    help="also run the weekly scans (adds Weekly tabs to the dashboard)")
    ap.add_argument("--weekly-days", type=int, default=8,
                    help="window (weekly bars) for the weekly recent-divergence scan")
    args = ap.parse_args(argv)

    enrich = [flag for flag, on in (
        ("--canslim", args.canslim or args.enrich),
        ("--wdb", args.wdb or args.enrich),
        ("--ai", args.ai or args.enrich),
    ) if on]

    scan = [sys.executable, "-m", "signals.scan_base_div"]
    # --- daily ---
    # 1) base + divergence watchlist  -> base_div_sheet_daily.csv (the default --out)
    _run(scan + ["--out", "base_div_sheet_daily.csv"] + enrich)
    # 2) recent divergences (no base) -> recent_div_daily.csv
    _run(scan + ["--no-base", "--timeframe", "daily",
                 "--recent-days", str(args.recent_days),
                 "--out", "recent_div_daily.csv"] + enrich)
    # --- weekly (optional) ---
    if args.weekly:
        # 3) weekly base + divergence -> base_div_sheet.csv
        _run(scan + ["--timeframe", "weekly", "--recent-days", str(args.weekly_days),
                     "--out", "base_div_sheet.csv"] + enrich)
        # 4) weekly recent divergences -> recent_div_weekly.csv
        _run(scan + ["--no-base", "--timeframe", "weekly",
                     "--recent-days", str(args.weekly_days),
                     "--out", "recent_div_weekly.csv"] + enrich)
    # rebuild the dashboard from the refreshed CSVs (weekly tabs appear if present)
    _run([sys.executable, "build_dashboard.py"])
    print("\ndashboard.html refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
