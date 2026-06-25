# Architecture & Build Plan — Crypto & Stock Signals System

*Companion to Requirements.md. Drafted 17 June 2026.*

## 1. Guiding principles

- **Alert-only, single-user, self-hosted.** No order execution, no multi-tenant concerns. Keep it simple.
- **Modular rules.** Each indicator/condition is a small, self-contained unit that returns a score contribution. Adding a new condition = adding one file, no engine changes.
- **One codebase, two run modes.** The same scoring engine powers both the backtester (historical) and the live scanner (recent data). This guarantees backtest results reflect live behaviour.
- **Cheap and boring tech.** Python, SQLite, a tiny web framework, a cron-style scheduler. Nothing that needs a managed database or paid add-ons.

## 2. High-level architecture

```
            ┌─────────────────────────────────────────────┐
            │                 VPS (~£4/mo)                  │
            │                                               │
  Crypto ───┤  ┌────────────┐   ┌──────────────────┐       │
  (free API)│  │ Data layer │──▶│  OHLCV store     │       │
            │  │  fetchers  │   │  (SQLite/Parquet)│       │
  Stocks ───┤  └────────────┘   └────────┬─────────┘       │
  (Polygon) │                            │                 │
            │                   ┌────────▼─────────┐       │
            │                   │  Scoring engine  │       │
            │                   │ (modular rules)  │       │
            │                   └────┬────────┬────┘       │
            │                        │        │            │
            │              ┌─────────▼──┐  ┌──▼──────────┐ │
            │              │ Backtester │  │Live scanner │ │
            │              │ (one-off)  │  │ (2×/day cron)│ │
            │              └─────────┬──┘  └──┬──────────┘ │
            │                        │        │            │
            │                   ┌────▼────────▼────┐       │
            │                   │  Signals store   │       │
            │                   └────────┬─────────┘       │
            │                            │                 │
            │                   ┌────────▼─────────┐       │
            │                   │  Web dashboard   │◀───── you (browser)
            │                   └──────────────────┘       │
            └─────────────────────────────────────────────┘
```

## 3. Components

### 3.1 Data layer

Pluggable fetchers behind a common interface (`get_ohlcv(symbol, timeframe, start, end)`):

- **Crypto fetcher** — Binance/Coinbase public REST. Free, no key needed for OHLCV. Daily + 4h candles for the top ~50–100 coins (weekly resampled from daily).
- **Stock fetcher (live)** — Polygon.io Starter. Daily + intraday aggregates for the S&P 500, 15-min delayed (fine for twice-daily scans).
- **Stock fetcher (backtest history)** — Stooq (free, ~decades of daily data) with Yahoo Finance as fallback. Used only to seed the 10-year backtest.

Data is cached locally so repeat scans and backtests don't re-download. Storage: **SQLite** for signals + metadata, **Parquet files** for bulk OHLCV (compact, fast to scan with pandas).

### 3.2 Scoring engine (the core)

A registry of **condition functions**. Each takes a price series and returns `(score_contribution, detail)`:

```python
@register(weight=2.0, group="momentum")
def rsi_oversold_reversal(df, cfg):
    # returns (points, "RSI 28 crossing up from oversold")
    ...
```

- The engine runs every registered condition over a symbol, sums `weight × points`, applies the **multi-timeframe trend modifier** (see 3.2d), and fires an **entry signal** if the total ≥ `entry_threshold`.
- **Exit signals** are a parallel set of conditions (e.g. RSI overbought, MACD bearish cross, trend filter flips, structure break) evaluated for instruments currently in an "active signal" state.
- All weights and thresholds live in a single **config file** (YAML), so tuning never touches code.
- Indicator maths via the `ta`/`pandas-ta` library (free) — MACD, RSI, ADX, EMAs, ATR.

Starting condition set (defaults, tuned later via backtest):

| Group | Conditions |
|---|---|
| MACD + RSI | MACD bullish cross, MACD histogram rising, RSI rising from oversold, RSI bullish divergence |
| Structure | Higher-high/higher-low sequence, breakout above recent swing high, **W / M patterns** — see 3.2c |
| Momentum + volume | ADX > 20 (trending), positive rate-of-change, volume spike on up-day, **volume momentum** — see 3.2e |
| **Exhaustion** | TD Sequential — Setup 9 (+ perfection) and Countdown 13, plus TDST level breaks — see 3.2f |
| Trend filter | Price above 50 EMA, 50 EMA above 200 EMA |
| **MA crosses** | Fast/slow MA crossovers + price/MA crosses — see 3.2b |
| **Divergences** | Multi-indicator divergence engine — see 3.2a |

### 3.2f TD Sequential (exhaustion) — implemented

Tom DeMark's TD Sequential, reproduced from the public algorithm in
`signals/indicators/td_sequential.py`. The trader's repeated "TD7 / TD9"
references are the **Setup** count at 7 (warning) and 9 (completed), and
his "13" is the **Countdown**.

- **Setup (1–9)** after a price flip; bar-9 = potential reversal. *Perfection*
  (low of bar 8/9 ≤ lows of 6/7, mirror for sells) marks a stronger 9.
- **Countdown (1–13)** begins on a completed setup; non-consecutive, with
  the standard **bar-8 qualifier** on bar 13. A completed 13 is the primary
  exhaustion signal. Opposite setups cancel an active countdown.
- **TDST levels** — the setup extreme acts as standing support/resistance;
  a break of it is itself a scored condition.

Scored as: buy setup-9 / buy countdown-13 → entry contributions (downside
exhaustion); sell setup-9 / sell countdown-13 → exit contributions.
Perfected 9s and completed 13s carry more weight than in-progress counts
(7/8), echoing the divergence engine's potential→confirmed escalation.

*Validation (10y AAPL daily): buy Countdown-13 fired at the Dec-2018,
23-Mar-2020 (COVID bottom) and Sep-2022 lows — i.e. it correctly marks
major exhaustion points.*

### 3.2e Volume momentum

Distinct from the volume *divergence* checks (3.2a), this measures whether **volume is building and accelerating behind the price move** — the confirmation that a breakout or trend has real participation rather than being a low-volume fakeout. All computable from free OHLCV. Registered conditions include:

- **Relative volume (RVOL)** — current volume vs its N-period average. A breakout on high RVOL scores; on weak volume it doesn't.
- **Volume rate-of-change / acceleration** — is volume rising over recent bars (and is the *rate* of increase itself increasing)?
- **OBV momentum** — slope of On-Balance Volume and OBV making new highs in line with price (confirmation) — the directional, non-divergence use of OBV.
- **Volume Oscillator** — fast vs slow volume EMA spread, positive and rising = expanding participation.
- **Up/down volume pressure** — net of up-day vs down-day volume over a window (buying vs selling intensity).
- **Breakout volume confirmation** — a flag that gates structure/MA-cross signals: a W-confirmation or golden cross on expanding volume scores higher than one on flat volume.

Each is its own weighted, scored condition (windows and thresholds in YAML), and the breakout-confirmation flag can optionally be required for structure/cross entries. Bullish volume momentum supports entries; collapsing volume momentum under price can support exits.

### 3.2d Multi-timeframe trend context

Signals don't live on one timeframe. The engine classifies the prevailing **trend on weekly, daily, and 4H** and uses their **alignment** to scale a signal's weight.

**Trend classification (per timeframe).** Each of weekly / daily / 4H is labelled **bullish, bearish, or neutral** using a small composite (configurable): e.g. price vs 50/200 EMA, 50-vs-200 EMA relationship, EMA slope, and recent structure (higher-highs/lows vs lower-highs/lows). A confidence/strength value comes with the label.

**How it affects scoring.** A signal is generated on a **base timeframe** (daily or 4H), then modified by the higher-timeframe context:

- **Full alignment** — all three timeframes agree with the signal direction (e.g. bullish entry with weekly + daily + 4H all bullish) → **score boosted** (configurable multiplier, e.g. ×1.5). Highest-conviction setups.
- **Partial alignment** — base timeframe agrees, one higher timeframe neutral → roughly neutral modifier.
- **Conflict** — a higher timeframe opposes the signal (e.g. bullish daily entry under a **bearish weekly**) → **score dampened** (e.g. ×0.5), flagged as *counter-trend / likely short-lived*. Optionally suppressed entirely below the entry threshold via config.

The dashboard shows the three trend labels next to each signal, so you can see at a glance whether a setup is with or against the bigger picture. All multipliers and the classification rules live in the YAML config and are tuned in the backtest.

> Data note: **weekly candles are resampled from daily** and **4H from intraday** — no extra data feed or cost. The store just keeps daily + intraday OHLCV and aggregates up on demand.

### 3.2c W / M structure engine (double bottoms & double tops)

Detects the two key reversal structures off the same swing-pivot data the divergence engine uses, with a **potential → confirmed** lifecycle.

**W structure — double bottom (bullish).** Geometry over consecutive pivots:

```
   neckline ────●────  (the swing high B between the two lows)
        \      / \      /
         ●    /   \    /     ← confirmation: close breaks ABOVE neckline B
       (A)low    (C)low
```

- Two swing lows (A and C) at **similar price** (within a configurable tolerance, e.g. C within ±X% of A), separated by a swing high B (the "neckline").
- **Potential W** — the second low (C) has formed at a comparable level to A and is holding. Early/weak → small score.
- **Confirmed W** — price **closes above the neckline (B)**. Strong reversal signal → large score. Feeds **entries**.
- Optional invalidation: price closes decisively below the lower of the two bottoms → pattern dropped.

**M structure — double top (bearish).** The mirror image:

- Two swing highs (A and C) at similar price, separated by a swing low B (the neckline).
- **Potential M** — second high formed near the first.
- **Confirmed M** — price **closes below the neckline (B)**. Feeds **exits** (and shorts later, if added).
- Optional invalidation: close decisively above the higher of the two tops.

**Configurable parameters (YAML):** pivot lookback (how swings are identified), peak-equality tolerance, min/max spacing between the two lows/highs, neckline-break confirmation buffer, and whether a volume confirmation on the breakout is required. As with divergences, each (pattern × lifecycle-state) is a separately weighted scored condition, so a *confirmed* W can score well above a *potential* one.

> Note: detection runs on **confirmed pivots**, so a pattern is only recognised once the swing points are locked in. This avoids repainting but means confirmation arrives a bar or two after the visual low — a deliberate trade-off for signal reliability over a tight-budget twice-daily scan.

### 3.2b Moving-average cross engine

A generic crossover detector that fires on the **bar where the cross happens** (not just the resulting state). It covers two cross types, each with configurable MA periods and type (SMA or EMA) in the YAML config:

- **MA/MA crosses** — a fast MA crossing a slow MA. Bullish "golden cross" (fast crosses **above** slow) → entry contribution; bearish "death cross" (fast crosses **below** slow) → exit contribution. Default pairs: 9/21, 20/50, 50/200 — any pairs can be added in config.
- **Price/MA crosses** — close crossing a single MA (e.g. price reclaiming the 50 EMA, or losing the 200 EMA).

Each configured cross is registered as its own scored condition, so faster crosses (e.g. 9/21) can carry a smaller weight and the major 50/200 a larger one. Optional refinements available via config: require the cross to align with the broader trend filter, and a minimum separation/slope to filter out flat-market whipsaw crosses.

### 3.2a Divergence engine (inspired by the "(mab) Divergences" TradingView script)

The referenced TradingView script is **closed-source**, so none of its code is used. What is reused is the **documented concept**, which is a standard, public technical-analysis technique: detecting divergences between price and a range of indicators, with a confirmation/invalidation lifecycle. We re-implement it from scratch.

**Generic detector.** One reusable function finds divergences between price pivots and *any* indicator's pivots:

- **Regular bullish** — price makes a lower low while the indicator makes a higher low (downtrend likely exhausting).
- **Regular bearish** — price makes a higher high while the indicator makes a lower high (uptrend likely exhausting).
- (Optionally hidden divergences later — continuation signals.)

**Lifecycle state machine** (the valuable part — re-evaluated on every confirmed candle):

- **Potential** — divergence first detected at the latest pivot. A weak/early signal → small score.
- **Confirmed** — the indicator value crosses back through the prior pivot level (the "confirmation level"). A strong signal → large score.
- **Invalidated** — the indicator pushes beyond the divergence's extreme (the "invalidation level"); the signal is dropped and scores nothing.

So a divergence contributes an *escalating* score as it moves potential → confirmed, and disappears if invalidated. This is what makes it better than a one-shot divergence flag.

**Indicators the detector runs over** (all computable from free OHLCV):

- MACD, RSI — already in the core set.
- MFI (Money Flow Index), CMF (Chaikin Money Flow), OBV — volume-based.
- Williams %R, Squeeze Momentum (Carter) — momentum-based.

> The script's two **proprietary** indicators ("MMF" / "MVI") are not reproduced; standard **MFI** and **CMF** serve the same price-volume-divergence purpose with public, documented formulas.

Each (indicator × divergence-direction × lifecycle-state) is registered as a scored condition, so the engine treats them exactly like every other rule — same config file controls their weights, and they feed both entries (bullish) and exits (bearish). Volume-based divergences require volume data, which crypto exchanges and Polygon both provide.

### 3.3 Backtester

- Replays history bar-by-bar through the **same** scoring engine.
- Simulates: enter when entry signal fires, exit when an exit signal fires (or a max-hold / stop rule).
- Reports per strategy-config: **win rate** (primary go-live metric), average win/loss, profit factor, max drawdown, number of trades, equity curve.
- Lets you sweep threshold/weights to find a good default before going live.
- Runs on 10 years of stock history (Stooq/Yahoo) and full-available crypto history.

### 3.4 Live scanner

- Triggered **twice a day** by cron (e.g. one mid US-session run, one after close).
- Pulls latest candles, runs the engine across the full universe, writes any new entry/exit signals to the signals store with timestamp, score, and the contributing conditions.
- Idempotent: re-running won't duplicate a signal already recorded for that bar.

### 3.5 Web dashboard

- Lightweight server (**FastAPI** or **Flask**) serving a single page.
- Shows: current active signals, score and the breakdown of which conditions fired, recent signal history, and last-scan timestamp.
- Read-only; no auth needed beyond the VPS being private (or a single basic-auth password). Plenty for one user.
- Optional later: a "turn this into a live page" upgrade or a Telegram push when a new signal lands.

## 4. Technology choices

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Best ecosystem for TA + data |
| Indicators | pandas-ta | Free, covers MACD/RSI/ADX/EMA/ATR |
| Data store | SQLite + Parquet | Zero-admin, file-based, fits a small VPS |
| Scheduler | cron / systemd timer | Built into the VPS, no extra cost |
| Web | FastAPI + a static template | Tiny, fast, easy |
| Config | YAML | Human-editable weights/thresholds |
| Hosting | Hetzner CX22 (~€4/mo) or Netcup | Cheapest reliable always-on EU VPS |

## 5. Phased build plan

**Phase 1 — Data layer & storage**
Fetchers for crypto (Binance) and stocks (Polygon + Stooq), common interface, local caching, OHLCV store. *Done when: I can pull and cache 10 years of daily + recent 4h data for the full universe.*

**Phase 2 — Scoring engine**
Condition registry, the starting condition set above, YAML config for weights/threshold, entry + exit evaluation. *Done when: given a symbol I get a score, a fired/not-fired verdict, and a per-condition breakdown.*

**Phase 2b — Divergence, MA-cross & structure engines**
(1) Generic pivot-based divergence detector + potential/confirmed/invalidated lifecycle, run over MACD, RSI, MFI, CMF, OBV, Williams %R and Squeeze Momentum. (2) Generic MA-cross detector for configurable MA/MA pairs (golden/death cross) and price/MA crosses. (3) W/M structure detector (double bottom/top) with potential → confirmed neckline-break lifecycle. All registered as scored conditions. *Done when: the breakdown shows live divergence states, MA-cross events, and W/M pattern states, and they contribute to the score.*

**Phase 2bb — Volume momentum**
RVOL, volume rate-of-change/acceleration, OBV momentum, volume oscillator, up/down volume pressure, and a breakout-volume-confirmation flag — all registered as scored conditions. *Done when: volume-momentum conditions appear in the breakdown and can gate structure/cross entries.*

**Phase 2c — Multi-timeframe trend context**
Trend classifier (bullish/bearish/neutral) for weekly, daily and 4H; alignment modifier applied to the signal score (boost when aligned, dampen on conflict). Weekly/4H resampled from stored daily/intraday data. *Done when: each signal carries its three timeframe trend labels and the score reflects alignment.*

**Phase 3 — Backtester**
Bar-by-bar replay through the engine, trade simulation, win-rate + drawdown + profit-factor report, config sweep. *Done when: I get a credible 10-year win-rate report and a recommended default config.*

**Phase 4 — Live scanner**
Twice-daily cron job, universe scan, signal persistence, de-duplication. *Done when: signals appear in the store automatically twice a day.*

**Phase 5 — Dashboard**
FastAPI page showing active signals, breakdowns, history, last-scan time. *Done when: I can open a URL and see current signals with rationale.*

**Phase 6 — Polish (optional)**
Telegram/Discord push, short setups, wider universe, more conditions.

## 6. Cost recap

| Item | £/mo |
|---|---|
| Polygon.io Starter (stock data) | ~23 |
| VPS | ~4 |
| Crypto data, dashboard, scheduler | 0 |
| **Total** | **~27** |

## 7. Risks & mitigations

- **Polygon 15-min delay** — fine for twice-daily swing signals; not for intraday precision. Accepted.
- **Backtest ≠ live data source** — using Stooq/Yahoo for 10-yr history and Polygon live could introduce small inconsistencies (adjustments, splits). Mitigation: normalise to adjusted close in both, spot-check overlap on the 5-year window where both exist.
- **Overfitting the config** — sweeping weights to maximise historical win rate can overfit. Mitigation: hold out the most recent 1–2 years as a validation period not used for tuning.
- **Survivorship bias** — backtesting today's S&P 500 over 10 years ignores delisted names. Mitigation: note it as a known optimistic bias; optionally add a point-in-time constituent list later.
- **VPS reliability** — a missed cron run misses a scan. Mitigation: alert if a scan hasn't completed; cheap to add.

## 8. Next step

Confirm the stack (Python / SQLite / FastAPI / Hetzner) and I can begin **Phase 1**, or adjust any choice first.
