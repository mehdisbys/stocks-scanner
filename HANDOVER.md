# Session Handover — Crypto & Stock Scanner

_Last updated: 2026-06-29_

Paste this into a new session to pick up instantly. It records the **non-obvious**
state — decisions, gotchas, and what's pending — not things the code already
documents.

---

## 1. Where the project stands

The engine and analytics are complete and tested. Built and validated: the full
data layer (crypto + stocks, local Parquet cache), the complete indicator suite
(TD Sequential, MACD/RSI, MA crosses, multi-indicator divergence with mab-style
confirmation, daily+weekly W/M structure, volume momentum, multi-timeframe trend,
Fibonacci 0.786, institutional bias, and the base/consolidation-at-lows detector),
the config-driven scoring engine, the backtester (costs, no look-ahead, train/test,
sweeps), and ground-truth test suites that pass.

This session added the **portfolio backtest CLI**, the **daily base+divergence scan**
(`signals/scan_base_div.py`) with timeframe/no-base/Google-Sheets options, recovered
and persisted the broader universe, and produced refreshed daily watchlists.

## 2. What was done THIS session (2026-06-29)

1. **Portfolio backtest wired into the CLI** (`signals/cli.py`).
   `run_portfolio`/`report_portfolio` already existed but weren't exposed. The
   `backtest` command now takes one of `--symbol` / `--symbols A B C` / `--sp500`
   / `--crypto-top` (mutually exclusive), plus `--out FILE.csv` for the per-symbol
   table in portfolio mode. Single-symbol keeps `--split`/`--sweep`.
   - Fix applied: the "X/Y symbols" message now reports symbols with `>= 250` bars
     (matching `run_portfolio`'s internal skip), not just non-empty ones.
   - README gained a full **Backtesting** section (one stock / multiple / S&P 500 /
     crypto / flags table).

2. **Daily base+divergence scan** — `signals/scan_base_div.py` (new, reusable).
   Reproduces the original weekly "bottom base + divergence" sheet but detects
   divergences on the chosen timeframe. Flags:
   - `--universe all|sp500|broader` (default `all`)
   - `--timeframe daily|weekly` (default `daily`)
   - `--recent-days N` — window in **bars of that timeframe** (fixed this session;
     it previously used `calendar_days * 2`, ~40% too wide)
   - `--no-base` — report every recent divergence, not only base names
   - `--include-potential` — also count unconfirmed divergences
   - `--out FILE.csv` (always writes CSV; defaults to `base_div_sheet_daily.csv`)
   - `--gsheet TITLE` / `--gsheet-cred PATH` / `--gsheet-share EMAIL` — optional
     push to Google Sheets via `gspread` (lazy import; clean error if missing).

3. **Broader universe recovered & persisted** → `data/universe/broader.csv`
   (115 names). See the gotcha in §5.

4. **`.gitignore` hardened** — now ignores `*.json` / `scanner-*.json` (the
   service-account key) and `_*.py` temp scripts.

## 3. Key outputs produced

- `base_div_sheet_daily.csv` — daily base+divergence watchlist, 103 names
  (16 S&P 500, 87 broader), 60-bar window.
- `recent_div_daily.csv` — daily recent-divergence scan (`--no-base`).
- Google Sheets in the user's Drive:
  - "Base + Divergence Watchlist — DAILY (60-bar window, corrected)" ← current
  - "Base + Divergence Watchlist — DAILY (2026-06-25)" ← stale (wider window); can delete
- Pre-existing from earlier sessions: `SP500_trade_ledger_10yr.csv`,
  `Backtest_Top100_10yr.xlsx`, `Scanner_*` and `Setup_*` CSVs.

## 4. How to run the common things

```bash
# Backtests
python -m signals.cli backtest --symbol AAPL --split 2024-06-01 --sweep
python -m signals.cli backtest --sp500 --out sp500_results.csv

# Scans (CSV always written; add --gsheet to also push to Sheets)
python -m signals.scan_base_div                                   # daily base+div, all universes
python -m signals.scan_base_div --no-base --timeframe daily  --recent-days 20
python -m signals.scan_base_div --no-base --timeframe weekly --recent-days 8

# Tests
python -m tests.test_indicators && python -m tests.test_scoring && python -m tests.test_backtest
```

## 5. Gotchas & decisions (the important part)

- **Broader universe is partial.** The original "broader" candidate list (the few
  hundred small/mid-cap + popular tickers the first session scanned) was never
  saved and is **lost**. `data/universe/broader.csv` holds only the **115 names
  that previously passed the base filter** (recovered from
  `Scanner_bottom_base_matches.csv`). `signals/data/universe.py` still only defines
  S&P 500 + crypto top. To scan a true broader universe you must define a fresh list.

- **`recent-days` semantics.** Now means N *trading bars of the selected timeframe*
  (last `df.index[-N:]`). So weekly `8` ≈ 2 months; daily `20` ≈ 1 month. The old
  calendar-day logic was a bug and is fixed.

- **Base detector is calibrated for daily bars** (252-day window, 200-day MA,
  60-day slope). On `--timeframe weekly` the `off_high`/`range_position` ratios are
  still valid, but `base_type` is unreliable — only trust it on daily.

- **Divergence `CONFIRMED` is a one-bar transition event** (not a persisted state),
  so "most recent confirmed bar in window" correctly matches the original sheet's
  `last_confirm`. Verified against the state machine.

- **Service-account key present in repo:** `scanner-500915-42346172c631.json` is a
  **live Google credential**. It's now git-ignored, but do NOT commit or share it.
  Point `--gsheet-cred` (or `$GSPREAD_SERVICE_ACCOUNT`) at it. A sheet the service
  account *creates* lives in the SA's Drive and is shared to the user — use
  `--gsheet-share <email>` once, or pre-create the sheet and share it to the SA email.

- **Sandbox vs. local venv.** The repo `.venv` is a macOS env and won't run in the
  Linux sandbox (broken symlinks). In the sandbox use system `python3` and install
  `pyarrow` (`pip install pyarrow --break-system-packages`) to read the Parquet cache.

- **Temp files** `_fetch_broader.py` and `_retry.py` are leftover scratch scripts in
  the project root (couldn't delete from sandbox — permission). Safe to delete
  manually; now git-ignored.

- **Nothing is committed beyond the initial commit.** All this session's work
  (`scan_base_div.py`, `cli.py`, README, requirements, `.gitignore`) is uncommitted.

## 6. Known code-review items still open (from this session's review)

Reviewed; fixed #1 (recent-days window) and #3 (portfolio count message). Still open:
- **#2 No de-duplication across universes** — if a symbol is in both S&P 500 and
  `broader.csv`, `--universe all` emits it twice. No overlap today; latent bug.
- **#4–5 `load_broader` robustness** — always drops line 1 as header; relative path
  silently returns `[]` if cwd is wrong.
- **#6 Wasted compute** — `divergence_signals` also computes unused bear divergences
  for all 8 indicators each symbol (~2x work); fine at 618 symbols, won't scale.
- **#7 Two entry points** — scan is `python -m signals.scan_base_div`, separate from
  `signals.cli`. Folding it in as a `scan` subcommand is the natural Phase 4 step.
- **#8 No tests** for the new scan logic or the portfolio CLI branch.

## 7. What's left (roadmap)

- **Phase 4 — Live scanner:** automated `scan` subcommand in `signals.cli` + signal
  persistence + de-duplication + twice-daily scheduling.
- **Phase 5 — Dashboard:** FastAPI page (active signals, breakdowns, history,
  last-scan time).
- **Crypto scanning:** extend the scan to crypto pairs (only 3 crypto files cached
  now; run `fetch-crypto --top` first).
- **Persist a real broader universe** (define a fresh list; current file is the
  recovered 115 only).
- **VPS → Drive chart-upload pipeline.**
- **Weight tuning / forward testing** (tune on train split, validate on held-out
  recent window).

## 8. Data coverage snapshot (2026-06-29)

- Stock daily: 618 symbols · Stock weekly: 618 · Crypto: ~3 files (minimal).
- `data/universe/broader.csv`: 115 names. `data/universe/sp500.csv`: 503.
