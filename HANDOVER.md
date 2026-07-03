# Session Handover — Crypto & Stock Scanner

_Last updated: 2026-07-02_

Paste this into a new session to pick up instantly. It records the **current
state, the non-obvious decisions, the gotchas, and what's pending** — the things
the code itself doesn't make obvious. It supersedes the 2026-06-29 handover
(that content is folded in below where still relevant).

---

## 1. Where the project stands

A Python base-consolidation + multi-indicator-divergence scanner for stocks and
crypto, with a config-driven scoring engine, a costed no-look-ahead backtester,
and a **self-contained HTML dashboard**. The engine, analytics, and test suites
are complete and passing.

Recent sessions built everything on top of the raw scan: the dashboard, the
enrichment columns (CANSLIM / WDB / AI / sector), SQLite signal-history with a
"new today" flag, weekly and **4h intraday** timeframes, a one-command refresh,
and a resumable full-universe intraday data puller. The 4h intraday cache has
now been populated for the **full ~618-symbol universe**, and the dashboard's 4h
tab reflects it (383 names).

**Status: feature-complete for the current scope and verified. Nothing new is
committed to git beyond the two original commits (see §10).**

---

## 2. What the recent sessions added (on top of the 2026-06-29 baseline)

1. **Self-contained HTML dashboard** — `build_dashboard.py` → `dashboard.html`.
   Single file, all data baked in as JSON, Chart.js from CDN, client-rendered
   sortable/filterable tables. No server, no live scan; it visualises the scan
   CSVs. Re-run `build_dashboard.py` anytime to refresh.

2. **Enrichment columns** wired directly into the scan (`signals/enrich.py`,
   `signals/sectors.py`): `--canslim`, `--wdb`, `--ai`, `--sector`, and
   `--enrich` (= all four). Details in §5.

3. **Signal history in SQLite** (`signals/history.py`) — tracks first/last-seen
   per `(scope, symbol)` and emits `new` / `first_seen` / `days_on_list`. Powers
   the dashboard's "New today" card, NEW badges, and "New only" filter. §6.

4. **Weekly + 4h timeframes.** `--timeframe weekly` and `--timeframe 4h` alongside
   `daily`. The dashboard grows a **Weekly** and **4h** tab automatically when the
   corresponding CSVs exist. 4h runs off Polygon intraday data. §7.

5. **One-command refresh** — `refresh.py` re-runs the scans and rebuilds the
   dashboard in one shot; flags forward enrichment, weekly, and 4h.

6. **Full-universe intraday puller** — `populate_4h.py` (resumable) fetches 1h→4h
   bars from Polygon for the whole universe. §7.

7. **Progress indicator** (`signals/progress.py`) — zero-dep counter on a TTY,
   uses tqdm if installed, silent when not a terminal.

8. **Tests** for all of the above in `tests/test_enrich.py` (CANSLIM/WDB/AI,
   progress, history, sectors, 4h routing, dashboard build). All suites pass.

---

## 3. File map (what to read first)

```
build_dashboard.py     Generates dashboard.html from the scan CSVs. Owns the
                       tab/column/filter layout and the fallback lookups.
refresh.py             One-command: run scans (+enrich/+weekly/+h4) → rebuild dashboard.
populate_4h.py         Resumable full-universe 1h→4h Polygon puller (run once, ~2h).

signals/
  scan_base_div.py     The scan CLI + run_scan(). _TF maps timeframe→(enum,min_bars,source).
  enrich.py            canslim_technical(), wdb_value(), ai_url()/AI_PROMPT.
  sectors.py           get_sectors() with a SQLite cache (sector_cache.sqlite).
  history.py           update_history() — SQLite signal_history, new/first_seen/days_on_list.
  progress.py          track() progress helper.
  data/
    service.py         DataService.get()/update_stock_live() — the single data entry point.
    base.py            Timeframe enum (H1/H4/D1/W1), OHLCV contract.
    polygon.py         Polygon fetcher (throttled ~5 calls/min on free tier).
    store.py           Parquet OHLCV cache read/upsert.
    universe.py        get_sp500(); broader list via scan_base_div.load_broader().
  indicators/          Full indicator suite incl. divergence.py, base_consolidation.py.

tests/                 test_indicators, test_scoring, test_backtest, test_enrich.
```

Scan CSV outputs (project root; consumed by the dashboard):
`base_div_sheet_daily.csv` (daily base+div), `recent_div_daily.csv` (daily recent),
`base_div_sheet.csv` (weekly base+div), `recent_div_weekly.csv` (weekly recent),
`recent_div_4h.csv` (4h recent), `SP500_per_symbol_summary.csv` (backtest).
Fallback enrichment lookups: `canslim.csv`, `wdb.csv`, `sectors.csv`.

---

## 4. The dashboard

`build_dashboard.py` builds `dashboard.html`. Structure:

- **Tabs** (rendered only when their CSV is present/non-empty):
  Base+Div (Daily), Recent Div (Daily), Base+Div (Weekly), Recent Div (Weekly),
  Recent Div (4h), S&P 500 Backtest. Gated by `has_weekly` / `has_h4`.
- The four+ watchlist tabs share ONE renderer (`initWatch(key, style)`); backtest
  has its own (`initBacktest()`).
- **Column order** (watchlist tabs): Symbol · New · Univ · Sector · Close ·
  Off High · Range Pos · Base Type · Div # · CANSLIM · WDB · Last Conf. · Chart ·
  AI · **Indicators** (Indicators is deliberately last — it's the widest/chip
  column).
- **Filters** per tab: symbol search, universe dropdown, **sector dropdown**,
  base-type dropdown (base tabs only), and a **"New only"** checkbox (auto-hidden
  when the tab has no history data).
- **Cards**: Names, SP500/Broader split, a strength stat, and **New today**
  (shown only once history exists).
- **Robustness**: charts are guarded — a missing/blocked Chart.js hides the chart
  boxes but never breaks the tables. (Historical bug: a JS temporal-dead-zone from
  section IIFEs left the page blank; fixed by converting to named functions called
  at the very end. Don't reintroduce top-level `const` referenced before init.)

**How enrichment reaches the dashboard:** each watchlist row prefers the enriched
column emitted by the scan (`canslim`/`wdb`/`sector`); if absent it falls back to
the `canslim.csv` / `wdb.csv` / `sectors.csv` lookup files keyed by symbol. This
is why the dashboard can show sectors even for a scan run without `--sector`.

Placeholders in the HTML template: `<!--__TABS__-->`, `<!--__PANELS__-->`,
`/*__BOOT__*/`, `/*__DATA__*/`.

---

## 5. Enrichment columns

| Flag | Column | Dashboard label | What it is | Needs |
| --- | --- | --- | --- | --- |
| `--canslim` | `canslim` | **Trend** | Trend/momentum proxy: price > SMA20/50/200 and Wilder RSI(14) > 50, scored `0/4`..`4/4 PASS`. Always from **daily** bars, even on weekly/4h/crypto scans. Needs ≥200 daily bars else `n/a`. **Not** real CANSLIM — just chart health. | daily price cache only |
| `--canslim-real` | `canslim_real` | **CANSLIM** | The **real** O'Neil CANSLIM, scored `0/6`..`6/6 PASS` over **C** (quarterly EPS growth ≥25%), **A** (annual earnings growth ≥25%), **N** (within 15% of 52wk high), **L** (52wk return beats S&P), **I** (institutions ≥30%), **M** (market above rising 50/200 MAs, fetched once via `^GSPC`). Label carries the passed letters, e.g. `4/6 CANL`. **S** (supply) is deliberately omitted — no reliable free share-count trend. Stocks only; `n/a` for ETFs. | `yfinance` + internet (info + income_stmt per matched symbol) |
| `--wdb` | `wdb` | WDB | Deep-value screen (finviz-style): P/E < 10, P/B < 1, Price/Cash < 3, scored `0/3`..`3/3 PASS`; `n/a` for ETFs/no fundamentals. | `yfinance` + internet (1 fetch/matched symbol) |
| `--ai` | `ai_analysis` | AI | One-click **Google AI Mode** (Gemini) URL — `https://www.google.com/search?udm=50&q=<encoded equity-research prompt>`. Native, no browser extension. | none |
| `--sector` | `sector` | Sector | GICS-style sector (Healthcare, Technology, …). Cached in `sector_cache.sqlite`; only the first fetch per symbol hits the network. Blank for ETFs. | `yfinance` + internet (first fetch only) |
| `--enrich` | all five | — | Shortcut for `--canslim --canslim-real --wdb --ai --sector`. | as above |

- **The `canslim` column is a trend proxy, not CANSLIM** — that's why the dashboard
  labels it **Trend** on every tab. The genuine fundamental CANSLIM is the separate
  `--canslim-real` / **CANSLIM** column (added 2026-07-02), stocks only. Fallback
  lookup file: `canslim_real.csv` (like `canslim.csv`/`wdb.csv`).
- Real CANSLIM adds a per-symbol earnings-statement fetch on top of `.info`, so it's
  the slowest enrichment; it's opt-in and only worth running on the daily stock scans.
- `enrich.py` degrades gracefully — a missing dep or data gap yields `n/a`, never
  a crash. Crypto scans auto-drop `wdb`, `sector`, and `canslim_real` (equity-only).

---

## 6. Signal history (SQLite)

`signals/history.py` — state in **`signal_history.sqlite`**, table
`signal_history(scope, symbol, first_seen, last_seen, seen_count, last_div_count,
PRIMARY KEY(scope, symbol))`. `scope` is e.g. `daily:base`, `daily:recent`,
`weekly:recent`, `4h:recent`.

`update_history(df, scope, path)` upserts the current hits (`ON CONFLICT … DO
UPDATE`, preserving the original `first_seen`) and returns the frame with `new`
('NEW' the first day a name appears in that scope, else ''), `first_seen`, and
`days_on_list`. **Idempotent within a day** — re-running on the same date won't
re-flag or double-count.

`refresh.py` always passes `--history`, so every refresh is a data point. The
first run flags everything NEW (no prior state); from the second run on, only
genuinely new names light up. DB default path `signal_history.sqlite`, git-ignored.

---

## 7. Timeframes & the 4h intraday pipeline

`scan_base_div._TF` maps timeframe → `(Timeframe enum, min_bars, store source)`:

```
daily  → (D1, 252, "history")     weekly → (W1, 60, "history")     4h → (H4, 120, "polygon")
```

- **daily / weekly** run off the free long-history cache (weekly is resampled from
  daily). No extra setup.
- **4h** runs off **intraday** data that must be populated first: Polygon 1h bars,
  resampled to 4h, stored under `source="polygon"`. You **cannot** derive 4h from
  the daily cache.

**Populating 4h (already done for the full universe):**

```bash
python populate_4h.py            # full universe, ~120 days back, ~2h, RESUMABLE
python populate_4h.py --days 180 # deeper history
python populate_4h.py --symbols AAPL MSFT NVDA
python populate_4h.py --force    # re-fetch even if cached
```

Resumable: symbols with ≥120 cached 4h bars are skipped, so Ctrl-C and re-run is
safe. Free Polygon tier is throttled to ~5 calls/min (`polygon.py` `_throttle`),
so a full pull is ~2h; a paid plan removes the limit.

**Scanning 4h** (base scan is daily-calibrated, so use `--no-base`):

```bash
python -m signals.scan_base_div --no-base --timeframe 4h --recent-days 30 \
    --out recent_div_4h.csv --enrich
python build_dashboard.py
# or in one shot:
python refresh.py --h4 --enrich
```

---

## 8. Canonical commands

```bash
# Full refresh: daily + weekly + 4h scans, all enrichment, rebuild dashboard
python refresh.py --enrich --weekly --h4

# Lighter refresh (daily only, no network enrichment)
python refresh.py --canslim --ai

# Individual scans
python -m signals.scan_base_div                                   # daily base+div, all universes
python -m signals.scan_base_div --no-base --timeframe daily  --recent-days 20
python -m signals.scan_base_div --no-base --timeframe weekly --recent-days 8
python -m signals.scan_base_div --no-base --timeframe 4h     --recent-days 30 --enrich

# Backtests
python -m signals.cli backtest --symbol AAPL --split 2024-06-01 --sweep
python -m signals.cli backtest --sp500 --out sp500_results.csv

# Tests (all pass)
python -m tests.test_indicators && python -m tests.test_scoring \
  && python -m tests.test_backtest && python -m tests.test_enrich

# Rebuild just the dashboard from existing CSVs
python build_dashboard.py
```

`refresh.py` flags: `--canslim/--wdb/--ai/--enrich`, `--recent-days` (20),
`--weekly` + `--weekly-days` (8), `--h4` + `--h4-days` (30). History is always on.

---

## 9. Data coverage snapshot (2026-07-02)

- Stock **daily**: 619 · **weekly**: 619 · **4h**: 618 · **1h**: 618 (Polygon).
- Crypto: BTCUSDT 4h + a few daily (minimal — crypto scanning not wired to the
  base+div scan yet).
- `data/universe/sp500.csv`: 503 · `data/universe/broader.csv`: 115 (recovered
  subset — see gotcha).
- Dashboard tab row counts: base 103 · recent 302 · wbase 22 · wrecent 150 ·
  **h4 383** · backtest 503.

---

## 10. Gotchas & decisions (read this before touching things)

- **SQLite fails on the cloud-synced / mounted folder.** `signal_history.sqlite`,
  `sector_cache.sqlite`, and `meta.sqlite` can throw `disk I/O error` when the
  project folder is network/cloud-synced, and **cannot be written from the Linux
  sandbox at all** on the mounted path. Consequences:
  - Locally, keep those DBs on a local disk if you hit the error.
  - From a sandbox/agent session, point `--history-file` / `--sector-file` at
    `/tmp/…`, or skip `--history`/`--sector` and rely on the `sectors.csv`
    fallback (plain CSV writes fine). Parquet writes to the mounted folder are OK.

- **The sandbox cannot `git commit`** (stale `.git/index.lock`, `Operation not
  permitted` on the mounted `.git`). All commits must be run on the user's
  machine: `cd ~/claude/Projects/"Crypto and Stock Scanner" && git add -A &&
  git commit -m "…"`.

- **Nothing since the initial two commits is committed.** `git log`:
  `bfe4d07 Save progress`, `b4f9a53 Initial commit`. Everything from the dashboard
  onward (build_dashboard.py, refresh.py, populate_4h.py, enrich/history/sectors/
  progress, the 4h wiring, tests, README/HANDOVER updates, and the scan CSVs) is
  **uncommitted**.

- **Polygon free tier = ~5 calls/min**, and intraday has no bulk endpoint (one
  call per symbol). Hence the ~2h full 4h pull. `populate_4h.py` is resumable to
  make that painless.

- **Base detector is daily-calibrated** (252-bar window, 200-bar MA, 60-bar
  slope). On weekly/4h the `off_high`/`range_position` ratios stay meaningful but
  `base_type` is unreliable — that's why 4h/weekly recent scans use `--no-base`.

- **`recent-days` = N trading bars of the selected timeframe** (`df.index[-N:]`),
  not calendar days. Weekly 8 ≈ 2 months; daily 20 ≈ 1 month; 4h 30 ≈ ~1.5 weeks.

- **sectors.csv coverage is partial on the 4h tab** (≈243/383). `sectors.csv` was
  built from the daily+weekly symbol union; some broader-universe names that only
  surface on 4h aren't in it. Fix: run a 4h scan with `--sector` (populates
  `sector_cache.sqlite` locally), or regenerate `sectors.csv` from the full
  universe.

- **Service-account key `scanner-500915-42346172c631.json` is a LIVE Google
  credential.** Git-ignored (`*.json`). **Never commit or share it.**

- **`--gsheet` service-account push fails**: `APIError [403] storage quota
  exceeded` — service accounts have zero Drive quota. Workarounds: (a) upload the
  CSV via a connected Google Drive (auto-converts to a native Sheet in the user's
  own Drive), or (b) switch to OAuth (user-owned Drive) — the recommended real
  fix. Some enriched Sheets were created in the user's Drive in earlier sessions;
  treat them as possibly stale.

- **Gemini/AI links** use Google AI Mode (`udm=50`) — native, one-click, no
  extension. In Google **Sheets** the clickable version is per-row
  `=HYPERLINK(url,label)`; `ARRAYFORMULA(HYPERLINK(...))` renders `#NAME?`. To
  drive links from one editable prompt cell use
  `ENCODEURL(SUBSTITUTE($cell,"{T}",<ticker>))`.

- **Broader universe is a recovered subset** (115 names that previously passed the
  base filter). The original full broader candidate list is lost;
  `data/universe.py` only defines S&P 500 + crypto top. Define a fresh list for a
  true broader scan.

- **Sandbox venv**: the repo `.venv` is a macOS env; in the Linux sandbox use
  system `python3` (pandas/pyarrow/yfinance/jsdom already available there).

- **Temp scripts** `_fetch_broader.py`, `_retry.py` are leftover scratch (git-
  ignored via `_*.py`); safe to delete.

---

## 11. Tests

`tests/` has ground-truth suites (each prints PASS/FAIL and asserts):
`test_indicators`, `test_scoring`, `test_backtest`, and `test_enrich`. The last
covers CANSLIM/WDB/AI helpers, the progress indicator, SQLite history
(NEW→persist→drop, same-day idempotence, independent scopes), the sector cache
(cache-hit without network), 4h source routing (`run_scan` asks the polygon
source for H4), crypto routing (`_TF_CRYPTO` map, `run_scan` uses the CRYPTO asset
class + binance source, CRYPTO tag, BINANCE: links, equity-only WDB/sector dropped
while CANSLIM/AI stay), and the dashboard build (tabs, columns, weekly/4h/crypto
gating). **All pass.** Run them after any change to the scan/enrichment/dashboard.

---

## 12. What's pending / roadmap

- **Commit the work** on the user's machine (see §10) — the single most important
  open item.
- ~~**Alerts**~~ — **DONE (2026-07-03).** `alerts.py` reads the scan CSVs, collects
  every `new == 'NEW'` row per scope (stocks + crypto), and writes a dated Markdown
  digest to `alerts/alert_<date>.md` + `alerts/latest.md` (no email, no network).
  `run_daily.sh` runs `refresh.py` then `alerts.py`; `launchd/com.cryptostockscanner
  .daily.plist` schedules it once a day (18:00 local) — `cp` it to
  `~/Library/LaunchAgents/` and `launchctl load` it (instructions in the plist).
  The `alerts/` output dir is git-ignored. First run flags everything NEW; steady
  state is a short list. To feed crypto into alerts, include `--crypto` in the
  refresh so the crypto CSVs get the `new` column.
- **Dashboard "History" view** — a tab reading `signal_history.sqlite` directly:
  per-symbol first-seen, appearance count, last-seen streak.
- **Schedule** the refresh (cron/launchd or the scheduled-tasks tool) — e.g. a 4h
  scan during market hours, a daily EOD refresh.
- **Fill 4h sectors** (run `--sector` on the full 4h universe, or rebuild
  `sectors.csv`).
- ~~**Crypto scanning**~~ — **DONE (2026-07-02).** Base+div scan runs on crypto via
  `--universe crypto` (top Binance USDT pairs; `binance` cache; daily/weekly/4h).
  `populate_crypto.py` (resumable) fills the cache; `refresh.py --crypto` runs the
  three scans and the dashboard grows **Crypto (Daily/Weekly/4h)** tabs. WDB/sector
  are equity-only and auto-dropped for crypto; CANSLIM (on crypto daily bars) + AI
  links still apply. History scope is prefixed `crypto:` so crypto/stock histories
  never collide; chart links use `BINANCE:<pair>`. Widen the list in
  `data/universe.py::TOP_CRYPTO`. Tests in `test_enrich.py` cover the routing.
- **OAuth for Google Sheets** to replace the dead service-account push.
- **Open code-review items** (latent, non-blocking): no de-dup across universes on
  `--universe all`; `load_broader` drops line 1 as header and returns `[]` on wrong
  cwd; `divergence_signals` computes unused bear divergences (~2× work, fine at 618
  but won't scale); two entry points (`scan_base_div` vs `signals.cli`) — folding
  the scan in as a `scan` subcommand is the natural next step.

---

## 13. One-paragraph "resume here"

The scanner is feature-complete and verified: daily/weekly/4h base+divergence
scans with CANSLIM/WDB/AI/sector enrichment and SQLite signal-history feed a
single self-contained `dashboard.html` (tabs auto-appear per available CSV;
Indicators is the rightmost column; sector has a column + filter). The full 4h
intraday cache (~618 symbols) is populated and the 4h tab shows 383 names. Run
`python refresh.py --enrich --weekly --h4` to regenerate everything, or
`python build_dashboard.py` to just rebuild the HTML. All four test suites pass.
**The main open action is committing the work on the user's machine** (the sandbox
can't), and the natural next features are alerts off the NEW flag and a scheduled
refresh. Mind the SQLite-on-mounted-folder and Polygon-rate-limit gotchas in §10.
```
