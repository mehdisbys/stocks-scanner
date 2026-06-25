# Crypto & Stock Signals System — Requirements

*Drafted 17 June 2026 from requirements interview. Budget: £30/month.*

## 1. Purpose

A signals system that scans crypto and US stocks and alerts when instruments meet a configurable set of technical criteria (MACD, RSI, market structure, momentum). It is an **alert-only** tool — it never places trades. The user reviews each signal and decides manually.

## 2. Scope

**In scope**

- Scanning crypto (top coins by market cap) and US stocks/ETFs.
- A **scoring-based** signal engine combining multiple indicators.
- **Entry and exit** signals (take-profit / setup-breakdown alerts as well as entries).
- A **web dashboard** as the primary way to view current and recent signals.
- **Backtesting** of the strategy on historical data before relying on it live.
- An **extensible rule framework** so new conditions can be added easily over time.

**Out of scope (for now)**

- Automated order execution / broker integration.
- Real-time / sub-minute scalping signals.
- Non-US equities (UK/EU stocks excluded for v1).

## 3. Universe

- **Crypto:** top ~50–100 coins by market cap. Data is free via exchange APIs (Binance, Coinbase, etc.).
- **US stocks/ETFs:** the **full S&P 500** (~500 symbols). Polygon Starter has unlimited calls, so this is well within rate limits.

## 4. Timeframes

- **Signal timeframes:** **daily** (primary) and **4h** (secondary), **scanned twice a day**.
- **Trend-context timeframes:** **weekly, daily, 4h** are each trend-classified to provide multi-timeframe confluence — a signal is weighted up when all three align and down when a higher timeframe conflicts (see architecture §3.2d). Weekly is resampled from daily, so no extra data.
- No real-time streaming required. 15-minute-delayed data is acceptable.

> **Note:** twice-a-day scanning suits the daily and 4h timeframes well. True **1h** signals would need ~hourly scans to be timely, so 1h is effectively dropped to 4h for v1. Easy to increase scan frequency later if wanted.

## 5. Signal logic

A **scoring model**: each indicator contributes points toward a total; a signal fires when the score crosses a user-set threshold. This is preferred over strict confluence ("all must agree") because it is tunable and tolerant of one weak input.

Indicator groups feeding the score:

- **MACD + RSI** — crossover / histogram, RSI levels and divergence (the core).
- **Market structure** — higher-highs/lows, breakouts of swing levels, support/resistance.
- **Momentum + volume** — rate-of-change, ADX, volume spikes for confirmation.
- **Trend filter (MAs)** — price vs 50/200 EMA regime, so signals favour the prevailing trend.

**Key design requirement:** rules must be **easy to add, remove, and re-weight** without rewriting the engine — ideally each condition is a small, self-contained, configurable unit (e.g. a plugin/function returning a score contribution).

Signals cover **both entries and exits**. **Direction: long-only for v1** (no short setups yet).

## 6. Delivery

- **Primary:** a web dashboard showing current signals, scores, the contributing indicators, and recent signal history.
- Optional later: push channel (Telegram/Discord) for new-signal alerts.

## 7. Validation

- **Backtest first.** Before any signal is trusted live, run the scoring model over **10 years** of historical data. **Win rate** is the primary go-live metric (reported alongside average gain/loss, drawdown, and number of signals).

> **Note — data source for the 10-year backtest:** Polygon Starter only includes **5 years** of history, so the 10-year backtest will use a free long-history daily source (**Stooq / Yahoo Finance**) for stocks, while **live** scanning runs on Polygon. Most **crypto** assets are younger than 10 years, so crypto backtests will use each coin's full available history (typically 3–8 years). This keeps the backtest free and within budget.

## 8. Budget allocation (£30/month)

Priority is **data quality**, especially for stocks (crypto data is free).

| Item | Choice | Approx cost/mo |
|---|---|---|
| Crypto data | Exchange APIs (Binance/Coinbase) | £0 |
| US stock data | **Polygon.io Starter** — unlimited calls, 5-yr history, 15-min-delayed minute bars | ~£23 ($29) |
| Hosting | Small VPS (e.g. Hetzner CX22 ~€4, or Netcup) | ~£4 |
| Delivery | Self-hosted dashboard | £0 |
| **Total** | | **~£27** |

Notes on the stock-data decision:

- **Polygon.io Starter ($29):** best quality-per-pound inside budget. 15-min delay and minute aggregates are fine for daily and 1h/4h swing trading. Leaves headroom for hosting.
- **Tiingo Power (£30/$30):** good and cheap but more end-of-day-oriented; intraday coverage weaker, and it consumes the entire budget alone.
- **Alpaca:** real-time SIP data is $99/mo (over budget); its free tier is IEX-only and limited.
- **Free (Yahoo/Stooq):** zero cost but less reliable and rate-limited — a fallback, not the primary, given data quality is the stated priority.

## 9. Technical profile

- User is comfortable running code and using a terminal/GitHub, so a code-based stack (e.g. Python) is appropriate.
- Self-hosted; user maintains it.

## 10. Decisions (resolved)

1. **Direction:** Long-only for v1.
2. **Stock watchlist:** Full S&P 500 (~500 symbols).
3. **Scan cadence:** Twice a day (covers daily + 4h timeframes).
4. **Hosting:** Small VPS (~£4/mo) — recommendation to follow (Hetzner / Netcup).
5. **Backtest:** 10 years of history; **win rate** is the primary go-live metric. (10-yr stock history sourced free from Stooq/Yahoo; live runs on Polygon.)
6. **Threshold/weights:** Start with sensible defaults, tune via backtest.

## 11. Suggested build phases

1. **Data layer** — pull crypto (free API) + stock (Polygon) OHLCV into a local store.
2. **Indicator + scoring engine** — modular conditions, configurable weights/threshold.
3. **Backtester** — run the engine over history, report performance.
4. **Live scanner** — scheduled scans on daily + 1h/4h, persist signals.
5. **Dashboard** — display current/recent signals, scores, and rationale.
6. **(Optional)** push alerts; add short setups; expand universe.

---

*Sources for pricing: Polygon.io, Alpaca, Tiingo (see chat for links).*
