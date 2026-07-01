"""Optional enrichment columns for the base+divergence scan.

Three independent add-ons, each opt-in from the CLI:

* **canslim** — finviz-style *technical* CAN SLIM proxy computed from daily
  bars: price above SMA20, SMA50, SMA200 and RSI(14) > 50. Score 0-4,
  labelled ``"4/4 PASS"`` when all four hold. Pure price data, no network.

* **wdb** — deep-value screen from Yahoo fundamentals: P/E < 10, P/B < 1,
  Price/Cash < 3. Score 0-3, labelled ``"3/3 PASS"``. Needs ``yfinance``
  and network access; returns ``"n/a"`` when no fundamentals are available.

* **ai** — a one-click Google AI Mode (Gemini) URL that runs a structured
  equity-research prompt for the ticker. No network at scan time.

Each helper degrades gracefully (returns ``None`` / ``"n/a"``) so a missing
dependency or data gap never breaks the scan.
"""

from __future__ import annotations

import urllib.parse

import numpy as np
import pandas as pd

# ---------------------------------------------------------------- CANSLIM ----

def _rsi(series: pd.Series, n: int = 14) -> pd.Series:
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def canslim_technical(df_daily: pd.DataFrame | None) -> dict | None:
    """CAN SLIM technical proxy from *daily* bars. Returns
    ``{"score": int, "label": str}`` or ``None`` if insufficient data."""
    if df_daily is None or len(df_daily) < 200:
        return None
    c = df_daily["close"]
    close = c.iloc[-1]
    checks = [
        close > c.rolling(20).mean().iloc[-1],
        close > c.rolling(50).mean().iloc[-1],
        close > c.rolling(200).mean().iloc[-1],
        _rsi(c).iloc[-1] > 50,
    ]
    score = int(sum(bool(x) for x in checks))
    return {"score": score, "label": f"{score}/4" + (" PASS" if score == 4 else "")}


# -------------------------------------------------------------------- WDB ----

def wdb_value(symbol: str) -> dict:
    """Deep-value check from Yahoo fundamentals (P/E<10, P/B<1, P/Cash<3).

    Returns ``{"score": int, "label": str}``; label is ``"n/a"`` when no
    fundamentals are available (e.g. ETFs) or ``yfinance`` is missing.
    """
    try:
        import yfinance as yf
    except ImportError:
        return {"score": 0, "label": "n/a"}
    pe = pb = pc = None
    try:
        info = yf.Ticker(symbol).info
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        price = info.get("currentPrice")
        tcps = info.get("totalCashPerShare")
        if price and tcps and tcps > 0:
            pc = price / tcps
    except Exception:
        pass
    have = sum(v is not None for v in (pe, pb, pc))
    if have == 0:
        return {"score": 0, "label": "n/a"}
    checks = [
        pe is not None and 0 < pe < 10,
        pb is not None and 0 < pb < 1,
        pc is not None and 0 < pc < 3,
    ]
    score = int(sum(checks))
    return {"score": score, "label": f"{score}/3" + (" PASS" if score == 3 else "")}


# --------------------------------------------------------------------- AI ----

AI_PROMPT = (
    "Act as an equity research analyst and give a detailed analysis of the stock with "
    "ticker {T}. Structure it with clear sections: a short company overview; the core "
    "bear case; the bull case and any turnaround or growth strategy; a financial snapshot "
    "table of key metrics (revenue, net income, margins, free cash flow) with latest "
    "full-year and most recent quarter figures; the current technical setup and key price "
    "levels to watch; a valuation-versus-risk discussion; and a summary recommendation "
    "framework for different investor types (value/contrarian versus income/risk-averse). "
    "Use the most recent available data and finish by offering a deeper follow-up."
)


def ai_url(symbol: str) -> str:
    """One-click Google AI Mode (Gemini) URL with the research prompt."""
    q = urllib.parse.quote_plus(AI_PROMPT.replace("{T}", symbol))
    return "https://www.google.com/search?udm=50&q=" + q
