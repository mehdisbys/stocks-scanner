# Crypto & Stock Signals System

Alert-only signals system for crypto and US stocks, using a configurable
scoring engine (MACD, RSI, structure incl. W/M patterns, MA crosses,
multi-indicator divergences, volume momentum, multi-timeframe trend
confluence). See `Requirements.md` and `Architecture-and-Build-Plan.md`.

**Status: Phase 1 (data) + all indicators + Phase 2 (scoring engine) complete and tested.**

## Scoring engine (`signals/scoring/`, driven by `scoring.yaml`)

Declarative condition registry: each condition references an indicator
column, fires on a test (truthy / `eq` / `ge` …), and adds its weight to
the **entry** (bullish) or **exit** (bearish) score. Scores get the
multi-timeframe trend multiplier, then compare to thresholds.

```python
from signals.scoring.engine import ScoringEngine, ScoringConfig
eng = ScoringEngine(ScoringConfig.load("scoring.yaml"))
eng.score_series(df)             # entry/exit score + signal per bar (backtester)
eng.evaluate(df, trend=ctx)      # latest bar + trend multiplier + breakdown (live)
```

Tune weights/thresholds in `scoring.yaml` — no code changes. Verified on
10y AAPL and BTC; scoring math, thresholds and the trend multiplier
covered by `tests/test_scoring.py`.

**Turning indicators on/off — all in `scoring.yaml`:**

- `modules:` block — a master switch per indicator (`macd_rsi`, `ma_cross`,
  `structure`, `structure_weekly`, `divergence`, `volume`, `td`,
  `fibonacci`, `institutional_bias`). Set one `false` to drop *all* of its
  conditions at once. Unlisted = enabled.
- `enabled: false` on any individual condition for finer control.
- `module_weights:` block — a multiplier per module (unlisted = 1.0) that
  scales every condition in that group at once (final weight = condition
  weight × multiplier). e.g. `divergence: 1.5` boosts all divergence
  signals 50%. Per-condition `weight:` still sets the fine-grained values.

So you control which indicators participate without deleting anything —
e.g. `institutional_bias: false` keeps the module and its condition
definitions but excludes them from scoring.

**Weekly W/M structure** is included as its own conditions
(`structure_weekly`, resampled from daily) at **double the weight** of the
daily W/M — a confirmed weekly double bottom adds 6.0 (vs 3.0 daily),
potential 2.0 (vs 1.0). Higher-timeframe reversals carry more conviction.

## Local data cache (no repeat API calls)

OHLCV is cached as Parquet under `data/ohlcv/<asset>/<source>/` and reused
automatically — `signal`/`backtest` only hit the network if a symbol is
missing or you pass `--refresh`. The full S&P 500 + crypto cache (~80 MB,
504 symbols, 10y) lives in `data/` and persists between runs.

```bash
python -m signals.cli coverage          # show what's cached locally
python -m signals.cli fetch-stock-history --sp500   # refresh all history
```

The metadata DB is best-effort (SQLite); if it can't open on a synced
folder, the cache still works and `coverage` scans the Parquet files
directly.

## Indicators (all built & tested, `signals/indicators/`)

| Module | File | What it produces |
|---|---|---|
| Core library | `core.py` | RSI, MACD, ATR, ADX, OBV, MFI, CMF, Williams %R, Squeeze, ROC, RVOL, vol-oscillator |
| Swing pivots | `pivots.py` | fractal swing highs/lows (no-lookahead confirmed view) |
| TD Sequential | `td_sequential.py` | Setup 1–9 (+perfection), Countdown 1–13, TDST levels |
| MACD + RSI | `macd_rsi.py` | crossovers, histogram, oversold/overbought events |
| MA crosses | `ma_cross.py` | golden/death crosses (configurable pairs) + price/MA crosses |
| Divergences | `divergence.py` | bull/bear regular divergence with potential→confirmed→invalidated lifecycle over 7 indicators |
| W/M structure | `structure.py` | double bottom/top lifecycle, HH/HL trend, breakouts |
| Volume momentum | `volume_momentum.py` | RVOL, vol ROC/accel, OBV momentum, oscillator, up/down pressure |
| Multi-TF trend | `trend.py` | per-TF bull/bear/neutral classification + weekly/daily/4h alignment multiplier |

All are pure functions over the canonical OHLCV frame (no external TA
dependency), ready for the Phase 2 scoring engine to wrap as weighted
conditions.

## Phase 1 — what's built

A clean data layer with a single contract (`signals/data/base.py`): every
fetcher returns OHLCV as a UTC-indexed DataFrame with
`open, high, low, close, volume`.

| Piece | File | Notes |
|---|---|---|
| Fetcher interface + models | `data/base.py` | `Timeframe`, `OHLCVFetcher`, validation |
| Crypto fetcher | `data/binance.py` | Binance public klines, **keyless**, paginated |
| Stock history (backtest) | `data/yahoo.py` | Yahoo chart API, **keyless**, ~10y daily — default |
| Stock history fallback | `data/stooq.py` | Stooq CSV (often blocks server IPs — see below) |
| Stock live/intraday | `data/polygon.py` | Polygon aggregates, **needs API key** |
| Store | `data/store.py` | Parquet candles + SQLite metadata, idempotent upsert |
| Resampling | `data/resample.py` | weekly←daily, 4h←1h (no extra data feed) |
| Universes | `data/universe.py` | full S&P 500 (cached) + top crypto |
| Service (entry point) | `data/service.py` | wires fetchers + store + resampling |
| CLI | `cli.py` | fetch / coverage commands |
| Config | `config.py`, `config.yaml` | sources, paths, timeframes |

## Setup

```bash
pip install -r requirements.txt
# Optional, for live stock scans later (Phase 4):
export POLYGON_API_KEY=your_key_here
```

## Usage

```bash
# What's cached?
python -m signals.cli coverage

# Crypto (keyless) — one symbol or the whole top list
python -m signals.cli fetch-crypto --symbol BTCUSDT --timeframe 1d
python -m signals.cli fetch-crypto --top --timeframe 4h

# Stock 10-year daily history for the backtest (keyless, Yahoo)
python -m signals.cli fetch-stock-history --symbol AAPL
python -m signals.cli fetch-stock-history --sp500

# Live/intraday stock data (needs Polygon key)
python -m signals.cli fetch-stock-live --symbol AAPL --timeframe 4h

# Score a symbol and show recent signals + latest-bar breakdown
python -m signals.cli signal --symbol AAPL
python -m signals.cli signal --symbol AAPL --days 60 --refresh
python -m signals.cli signal --asset crypto --symbol BTCUSDT

# Backtest the scoring engine (Phase 3) — see "Backtesting" below
python -m signals.cli backtest --symbol AAPL
python -m signals.cli backtest --sp500 --out sp500_results.csv
```

## Watchlist scan (`signals/scan_base_div.py`)

Produces the "bottom base + divergence" watchlist (CSV always written; add
`--gsheet TITLE` to also push to Google Sheets).

```bash
# Daily base+divergence, all universes
python -m signals.scan_base_div

# Recent divergences only (no base filter), tighter window
python -m signals.scan_base_div --no-base --timeframe daily --recent-days 20
```

### Enrichment columns (opt-in)

Add screener columns straight into the output so the CSV/Sheet is ready to use
— no separate post-processing step:

| Flag | Column | What it is | Needs |
| --- | --- | --- | --- |
| `--canslim` | `canslim` | CAN SLIM **technical** proxy: price > SMA20/50/200 and RSI(14) > 50, scored `0/4`..`4/4 PASS`. Always computed from *daily* bars, even on `--timeframe weekly`. | price cache only |
| `--wdb` | `wdb` | Deep-value screen: P/E < 10, P/B < 1, Price/Cash < 3, scored `0/3`..`3/3 PASS` (`n/a` when no fundamentals, e.g. ETFs). | `yfinance` + internet |
| `--ai` | `ai_analysis` | One-click Google AI Mode (Gemini) URL running a structured equity-research prompt for the ticker. | none |
| `--enrich` | all three | Shortcut for `--canslim --wdb --ai`. | as above |

```bash
# Fully enriched daily watchlist, pushed to a Google Sheet
python -m signals.scan_base_div --enrich \
  --out recent_div_daily.csv \
  --gsheet "Recent Divergences — DAILY" \
  --gsheet-cred scanner-500915-42346172c631.json
```

Notes: `--wdb` adds one Yahoo fundamentals fetch per matched symbol (slower,
needs network); WDB reflects *current* fundamentals, not the scan date. The
enrichment helpers live in `signals/enrich.py` and degrade gracefully (a
missing dependency or data gap yields `n/a`, never a crash).

## Backtesting

The backtester (`signals/backtest/`) simulates long-only trades with
realistic costs and **no look-ahead** (signals on a bar's close fill at
the next bar's open). It runs in two modes that share the same engine and
cost model:

- **Single symbol** (`--symbol`) — full per-trade report, with optional
  `--split` (in-sample vs out-of-sample) and `--sweep` (entry/exit
  threshold grid).
- **Portfolio** (`--symbols`, `--sp500`, `--crypto-top`) — runs every
  symbol and aggregates: pooled trade stats (win rate, profit factor,
  expectancy) plus a per-symbol distribution (% profitable, % that beat
  buy-&-hold, median/avg return). `--out FILE.csv` writes the per-symbol
  table.

### One stock

```bash
python -m signals.cli backtest --symbol AAPL
# train/test split + threshold sweep + risk controls
python -m signals.cli backtest --symbol AAPL --split 2024-06-01 --sweep \
    --max-hold 60 --stop-pct 0.10
```

### One crypto pair

```bash
python -m signals.cli backtest --asset crypto --symbol BTCUSDT
python -m signals.cli backtest --asset crypto --symbol ETHUSDT --split 2024-06-01
```

### Multiple symbols (portfolio)

```bash
python -m signals.cli backtest --symbols AAPL MSFT NVDA
python -m signals.cli backtest --symbols AAPL MSFT NVDA --out tech_results.csv
# a basket of crypto pairs
python -m signals.cli backtest --asset crypto --symbols BTCUSDT ETHUSDT SOLUSDT
```

### Full S&P 500

```bash
python -m signals.cli backtest --sp500
python -m signals.cli backtest --sp500 --out sp500_results.csv   # save per-symbol CSV
```

### All crypto top pairs

```bash
python -m signals.cli backtest --crypto-top --out crypto_results.csv
```

### Flags (all modes)

| Flag | Effect | Default |
|---|---|---|
| `--scoring FILE` | scoring config to use | `scoring.yaml` |
| `--fee-bps N` | per-side fee, basis points | 10 |
| `--slippage-bps N` | per-side slippage, basis points | 5 |
| `--stop-pct X` | hard stop (e.g. `0.08` = 8%) | none |
| `--max-hold N` | force-exit after N bars | none |
| `--refresh` | re-fetch latest data before running | off |
| `--out FILE.csv` | per-symbol results (portfolio modes only) | — |
| `--split DATE` | in-sample vs out-of-sample (single-symbol only) | — |
| `--sweep` | grid entry/exit thresholds (single-symbol only) | off |

`--symbol`, `--symbols`, `--sp500`, and `--crypto-top` are mutually
exclusive — pick one. `--split`/`--sweep` apply to single-symbol runs and
are ignored in portfolio mode. Backtests read from the local Parquet
cache (run the matching `fetch-*` command first, or pass `--refresh`).
Metrics: win rate (primary), profit factor, expectancy, max drawdown,
CAGR, vs buy-&-hold. Simulation math is covered by
`tests/test_backtest.py` (next-open fills, costs, stop, max-hold).

Weekly candles are derived automatically from daily; 4h stock candles
from Polygon 1h. So the multi-timeframe trend context (weekly/daily/4h)
costs no extra data.

## Verified in live testing (18 Jun 2026)

- **Binance** ✔ pulled BTCUSDT daily/4h and resampled weekly.
- **Yahoo** ✔ pulled 2,513 daily AAPL candles (2016→2026, full 10 years).
- **Store** ✔ Parquet round-trip + idempotent re-fetch (no duplicate rows).
- **Resampling** ✔ 4h aggregation and weekly (~5 trading days/bar) correct.
- **S&P 500** ✔ 503 symbols fetched from Wikipedia and cached.

### Real-world notes / gotchas

- **Stooq blocks datacentre IPs** — it served an anti-bot HTML page from
  the sandbox. Yahoo is therefore the default history source, with Stooq
  as a fallback. On a residential IP Stooq may work fine.
- **Yahoo adjustment** — adjusted close is applied to the *whole* OHLC bar
  (open/high/low scaled by the same factor), so close always stays within
  [low, high]. Without this, range-based indicators (Williams %R, CMF,
  ATR) break. Verified bounded on 10y AAPL after the fix.
- **Wikipedia** needs a browser `User-Agent` (else HTTP 403) — handled.
- **SQLite on networked/FUSE mounts** can throw `disk I/O error`. On the
  VPS (normal disk) this is a non-issue. If you run locally against a
  synced/cloud folder, point `data_dir` at a local path in `config.yaml`.

## Tests

```bash
python -m tests.test_indicators
python -m tests.test_scoring
```

`tests/test_indicators.py` holds **ground-truth** tests (hand-crafted
series with known answers): RSI extremes, MA golden-cross firing once,
bullish divergence reaching potential → confirmed and separately
invalidating, W double-bottom confirming, and the trend-conflict
multiplier dampening a counter-trend entry. All engines are additionally
smoke-tested on real BTC (daily + 4h) and 10y AAPL with state/bounds
validation.

**Tested:** all indicator logic (ground-truth) · data fetchers (Binance,
Yahoo, Wikipedia) live · TD Sequential vs the Pine reference (0 diffs) ·
every engine on crypto daily+4h and stock daily.
**Not yet tested:** the dashboard/scanner (not built yet).

### Polygon free plan — validated & strategy

Live path tested with a real key: daily (494 bars / ~2y), 1h intraday,
and **grouped-daily** (12,299 tickers in ONE call, covering 501/503 S&P
500). Constraints and how we handle them:

- **5 calls/min** — the fetcher has a built-in rate limiter; and the
  daily stock scan uses `get_grouped_daily` (1 call covers the whole
  universe) rather than 500 per-symbol calls.
- **2-year history** — fine for live scanning; the 10-year backtest uses
  Yahoo, not Polygon.
- **Per-symbol intraday (4h/1h)** is impractical for 500 stocks on the
  free tier; the stock scanner is daily anyway (crypto carries 4h).

## Next: Phase 2 — scoring engine

Condition registry, YAML-driven weights/threshold, entry+exit
evaluation, then the divergence / MA-cross / structure / volume-momentum
/ trend-context engines (Phases 2b–2c).
