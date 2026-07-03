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


# ------------------------------------------------- CANSLIM (fundamental) ----
# The "real" O'Neil CANSLIM, as far as free fundamentals allow. Scored over
# six of the seven letters:
#   C  current quarterly EPS growth  >= 25% YoY
#   A  annual earnings growth        >= 25%
#   N  price within 15% of its 52-week high (near new highs)
#   L  leader: 52-week return beats the S&P 500 (relative strength)
#   I  institutional sponsorship present (>= 30% held by institutions)
#   M  general market in an uptrend (computed once, passed in)
# 'S' (supply/demand — share-count trend, buybacks) is deliberately omitted:
# a reliable shares-outstanding *trend* isn't available from the free feed,
# so scoring it would be guesswork. Label is "score/6" plus the passed letters
# (e.g. "4/6 CANL"), or "n/a" when fundamentals can't be fetched.

MARKET_INDEX = "^GSPC"  # S&P 500 index, for the 'M' (market direction) check


def market_uptrend(symbol: str = MARKET_INDEX) -> bool | None:
    """True if the market index is above its rising 50/200-day MAs.

    Returns ``None`` when the data can't be fetched (treated as unknown by the
    caller). Compute this once per scan and pass the result to
    :func:`canslim_fundamental` so every symbol shares one market read.
    """
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        h = yf.Ticker(symbol).history(period="1y")
    except Exception:
        return None
    if h is None or h.empty or len(h) < 200:
        return None
    c = h["Close"]
    px = c.iloc[-1]
    sma50 = c.rolling(50).mean().iloc[-1]
    sma200 = c.rolling(200).mean().iloc[-1]
    return bool(px > sma50 > sma200)


def _annual_earnings_growth(tkr) -> float | None:
    """Latest-vs-prior annual net-income growth from the income statement."""
    try:
        fin = tkr.income_stmt
        if fin is None or fin.empty:
            return None
        row = next((r for r in ("Net Income", "NetIncome",
                                "Net Income Common Stockholders") if r in fin.index), None)
        if row is None:
            return None
        ni = fin.loc[row].dropna()
        if len(ni) < 2:
            return None
        latest, prior = float(ni.iloc[0]), float(ni.iloc[1])
        if prior == 0:
            return None
        return (latest - prior) / abs(prior)
    except Exception:
        return None


def canslim_fundamental(symbol: str, df_daily: pd.DataFrame | None = None,
                        market_ok: bool | None = None) -> dict:
    """Real(ish) CANSLIM score (0-6 over C,A,N,L,I,M) from Yahoo fundamentals.

    ``df_daily`` (optional) is a fallback for the 52-week-high check when the
    info feed lacks price fields. ``market_ok`` is the shared result of
    :func:`market_uptrend`. Returns ``{"score", "label", "detail"}``; label is
    ``"n/a"`` for ETFs or when no fundamentals are available."""
    try:
        import yfinance as yf
    except ImportError:
        return {"score": 0, "label": "n/a", "detail": ""}
    try:
        tkr = yf.Ticker(symbol)
        info = tkr.info or {}
    except Exception:
        return {"score": 0, "label": "n/a", "detail": ""}
    # No usable fundamentals (ETF, delisted, or feed miss) -> n/a, not "0/6".
    if not info or info.get("quoteType") == "ETF" or (
            info.get("trailingEps") is None and info.get("earningsQuarterlyGrowth") is None):
        return {"score": 0, "label": "n/a", "detail": ""}

    passed: dict[str, bool] = {}
    # C — current quarterly EPS growth >= 25% YoY
    c = info.get("earningsQuarterlyGrowth")
    passed["C"] = c is not None and c >= 0.25
    # A — annual earnings growth >= 25%
    a = _annual_earnings_growth(tkr)
    if a is None:
        a = info.get("earningsGrowth")
    passed["A"] = a is not None and a >= 0.25
    # N — within 15% of the 52-week high
    hi = info.get("fiftyTwoWeekHigh")
    px = info.get("currentPrice") or info.get("regularMarketPrice")
    if (hi is None or px is None) and df_daily is not None and len(df_daily) >= 20:
        hi = float(df_daily["close"].tail(252).max())
        px = float(df_daily["close"].iloc[-1])
    passed["N"] = (hi is not None and px is not None and hi > 0 and px >= 0.85 * hi)
    # L — leader: 52-week return beats the S&P 500
    rs, spx = info.get("52WeekChange"), info.get("SandP52WeekChange")
    passed["L"] = rs is not None and spx is not None and rs > spx
    # I — institutional sponsorship present
    inst = info.get("heldPercentInstitutions")
    passed["I"] = inst is not None and inst >= 0.30
    # M — general market uptrend (shared read; unknown -> not passed)
    passed["M"] = bool(market_ok)

    letters = "".join(k for k in ("C", "A", "N", "L", "I", "M") if passed[k])
    score = len(letters)
    label = f"{score}/6" + (" PASS" if score == 6 else (f" {letters}" if letters else ""))
    return {"score": score, "label": label, "detail": letters}


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
