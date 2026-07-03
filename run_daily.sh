#!/bin/bash
# Daily driver for the scanner: rescan + rebuild dashboard, then write the
# NEW-name alert digest. Called by the launchd job (see
# launchd/com.cryptostockscanner.daily.plist) but also runnable by hand:
#
#     ./run_daily.sh
#
# Edit the refresh flags below to taste. Kept light by default (daily stock +
# crypto scans, fast enrichment). Add --weekly --h4 for more stock tabs, or
# --canslim-real for the fundamental CANSLIM column (much slower — per-stock
# Yahoo fetches).

set -euo pipefail
cd "$(dirname "$0")"

# Prefer the repo virtualenv, fall back to system python3.
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

mkdir -p alerts
LOG="alerts/run.log"
echo "=== run $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

# 1) Top up the Binance cache with the latest bars (crypto trades 24/7, so the
#    cache goes stale daily). --force + a short --days re-fetches recent candles
#    and upserts them into the existing history; ~1-2 min for the ~30 pairs.
"$PY" populate_crypto.py --force --days 30 >> "$LOG" 2>&1

# 2) Rescan stocks + crypto and rebuild the dashboard. --crypto adds the Crypto
#    tabs and, because refresh always tracks history, gives the crypto CSVs the
#    `new` column so they feed the alert digest.
"$PY" refresh.py --canslim --ai --crypto >> "$LOG" 2>&1

# 3) Write today's NEW-name digest (stocks + crypto).
"$PY" alerts.py  >> "$LOG" 2>&1

echo "done $(date '+%H:%M:%S')" >> "$LOG"
