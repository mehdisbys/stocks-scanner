"""Ground-truth tests for the scan enrichment + dashboard pipeline.

Covers the pieces added on top of the base scan: CANSLIM/WDB/AI helpers,
the progress indicator, the scan's enrichment wiring, and the dashboard
generator's weekly-tab logic. Run with:

    python -m tests.test_enrich
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

import sqlite3

from signals import enrich, history, progress, sectors

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check(name, cond):
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    assert cond, name


def _daily(closes):
    n = len(closes)
    idx = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    idx.name = "ts"
    return pd.DataFrame({"open": closes, "high": [c + 1 for c in closes],
                         "low": [c - 1 for c in closes], "close": closes,
                         "volume": [1e6] * n}, index=idx)


# ------------------------------------------------------------------ CANSLIM ---
def test_canslim_needs_200_bars():
    check("canslim returns None below 200 bars",
          enrich.canslim_technical(_daily(list(range(1, 100)))) is None)
    check("canslim returns None for None input",
          enrich.canslim_technical(None) is None)


def test_canslim_uptrend_passes_4of4():
    # net-rising series *with* small pullbacks (real prices always have down
    # days; a perfectly monotonic ramp would make RSI divide by zero).
    closes = [100 + i * 0.5 + 0.3 * ((-1) ** i) for i in range(260)]
    r = enrich.canslim_technical(_daily(closes))
    check("strong uptrend scores 4/4 PASS", r["score"] == 4 and r["label"] == "4/4 PASS")


def test_canslim_downtrend_fails():
    # steadily falling series: price below SMAs and RSI under 50
    df = _daily([300 - i * 0.5 for i in range(260)])
    r = enrich.canslim_technical(df)
    check("strong downtrend scores 0/4", r["score"] == 0 and r["label"] == "0/4")
    check("failing label carries no PASS", "PASS" not in r["label"])


# ---------------------------------------------------------------------- WDB ---
def test_wdb_shape_is_safe():
    # never raises; always returns a {score,label} dict even offline
    r = enrich.wdb_value("DEFINITELY_NOT_A_TICKER_XYZ")
    check("wdb returns a dict", isinstance(r, dict) and "score" in r and "label" in r)
    check("wdb score in 0..3", 0 <= r["score"] <= 3)


# ------------------------------------------------- CANSLIM (fundamental) ---
def _fake_yf(info, income=None):
    """A stand-in ``yfinance`` module so the CANSLIM logic can be tested offline."""
    import types
    m = types.ModuleType("yfinance")

    class T:
        def __init__(self, sym):
            self._sym = sym

        @property
        def info(self):
            return info

        @property
        def income_stmt(self):
            return income if income is not None else pd.DataFrame()

        def history(self, period=None):
            return pd.DataFrame()

    m.Ticker = T
    return m


def test_canslim_fundamental_all_six_pass():
    info = {"quoteType": "EQUITY", "trailingEps": 5.0,
            "earningsQuarterlyGrowth": 0.40,       # C
            "earningsGrowth": 0.50,                # A (fallback)
            "fiftyTwoWeekHigh": 100.0, "currentPrice": 95.0,  # N (within 15%)
            "52WeekChange": 0.30, "SandP52WeekChange": 0.10,  # L (beats S&P)
            "heldPercentInstitutions": 0.65}       # I
    sys.modules["yfinance"] = _fake_yf(info)
    try:
        r = enrich.canslim_fundamental("TEST", market_ok=True)  # M
    finally:
        sys.modules.pop("yfinance", None)
    check("all six letters pass -> 6/6 PASS", r["label"] == "6/6 PASS" and r["score"] == 6)
    check("detail lists passed letters C,A,N,L,I,M", r["detail"] == "CANLIM")


def test_canslim_fundamental_partial_and_na():
    weak = {"quoteType": "EQUITY", "trailingEps": 2.0,
            "earningsQuarterlyGrowth": 0.05,       # C fail
            "fiftyTwoWeekHigh": 100.0, "currentPrice": 50.0,  # N fail
            "52WeekChange": 0.02, "SandP52WeekChange": 0.10,  # L fail
            "heldPercentInstitutions": 0.10}       # I fail; A missing; M fail
    sys.modules["yfinance"] = _fake_yf(weak)
    try:
        r = enrich.canslim_fundamental("TEST", market_ok=False)
    finally:
        sys.modules.pop("yfinance", None)
    check("no criteria pass -> 0/6", r["score"] == 0 and r["label"].startswith("0/6"))
    check("failing label carries no PASS", "PASS" not in r["label"])

    sys.modules["yfinance"] = _fake_yf({})  # empty fundamentals (ETF / feed miss)
    try:
        r2 = enrich.canslim_fundamental("TEST")
    finally:
        sys.modules.pop("yfinance", None)
    check("empty fundamentals -> n/a", r2["label"] == "n/a")


def test_run_scan_emits_canslim_real_and_drops_for_crypto():
    from signals import scan_base_div as S
    S.get_sp500 = lambda: ["AAA"]
    S.load_broader = lambda *a, **k: []
    S.get_crypto_universe = lambda: ["BTCUSDT"]
    mk, cf = enrich.market_uptrend, enrich.canslim_fundamental
    enrich.market_uptrend = lambda *a, **k: True
    enrich.canslim_fundamental = lambda sym, d=None, market_ok=None: {
        "score": 5, "label": "5/6 CANLI", "detail": "CANLI"}

    class FakeSvc:
        def get(self, ac, sym, tf, source=None):
            return pd.DataFrame()  # empty -> 0 rows, but columns still defined

    try:
        stock = S.run_scan(FakeSvc(), "sp500", 60, True, timeframe="daily",
                           require_base=False, add_canslim_real=True, desc="t")
        crypto = S.run_scan(FakeSvc(), "crypto", 60, True, timeframe="daily",
                            require_base=False, add_canslim_real=True, desc="t")
    finally:
        enrich.market_uptrend, enrich.canslim_fundamental = mk, cf
    check("run_scan emits canslim_real for stocks", "canslim_real" in stock.columns)
    check("canslim_real dropped for crypto", "canslim_real" not in crypto.columns)


# ----------------------------------------------------------------------- AI ---
def test_ai_url_encodes_ticker_and_prompt():
    url = enrich.ai_url("BF-B")
    check("ai url targets Google AI Mode (udm=50)", url.startswith(
        "https://www.google.com/search?udm=50&q="))
    check("ai url embeds the ticker", "BF-B" in url)
    check("ai url is percent-encoded (no raw spaces)", " " not in url)
    check("prompt template has no leftover placeholder", "{T}" not in url)


# ------------------------------------------------------------------ PROGRESS --
def test_progress_yields_all_and_is_silent_when_not_tty():
    sink = io.StringIO()  # StringIO.isatty() is False -> must stay silent
    out = list(progress.track(["A", "B", "C"], desc="x", stream=sink))
    check("progress yields every item unchanged", out == ["A", "B", "C"])
    check("progress silent when not a terminal", sink.getvalue() == "")


def test_progress_writes_counter_on_tty():
    class TTY(io.StringIO):
        def isatty(self):
            return True
    t = TTY()
    list(progress.track(["AAPL", "MSFT"], desc="base-div", label=lambda s: s, stream=t))
    body = t.getvalue()
    check("tty progress shows count + label", "1/2" in body and "AAPL" in body)


# ----------------------------------------------------------- SCAN WIRING ------
def test_scan_run_adds_enrichment_columns():
    # tiny patched universe so this is fast; exercises the real run_scan path
    from signals import scan_base_div as S
    from signals.config import Config
    from signals.data.service import DataService
    S.get_sp500 = lambda: ["KMX", "AXP"]
    S.load_broader = lambda *a, **k: []
    svc = DataService(Config.load(os.path.join(HERE, "config.yaml")))
    df = S.run_scan(svc, "sp500", 60, False, timeframe="daily", require_base=False,
                    add_canslim=True, add_wdb=False, add_ai=True, desc="test")
    for col in ("canslim", "ai_analysis"):
        check(f"run_scan emits '{col}' column", col in df.columns)
    check("wdb column absent when not requested", "wdb" not in df.columns)
    if len(df):
        check("ai_analysis is a Google AI Mode URL",
              str(df["ai_analysis"].iloc[0]).startswith("https://www.google.com/search?udm=50"))


# -------------------------------------------------------------- HISTORY -------
def test_history_flags_new_then_persists():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "h.sqlite")
        d1 = pd.DataFrame({"symbol": ["AAA", "BBB"], "div_count": [3, 2]})
        r1 = history.update_history(d1, "daily:base", p, today="2026-01-01")
        check("first run flags every name NEW", list(r1["new"]) == ["NEW", "NEW"])

        # next day: AAA persists, CCC is brand new, BBB drops off
        d2 = pd.DataFrame({"symbol": ["AAA", "CCC"], "div_count": [4, 1]})
        r2 = history.update_history(d2, "daily:base", p, today="2026-01-02")
        m = dict(zip(r2["symbol"], r2["new"]))
        check("returning name is not NEW", m["AAA"] == "")
        check("brand-new name is NEW", m["CCC"] == "NEW")
        dl = dict(zip(r2["symbol"], r2["days_on_list"]))
        check("days_on_list counts from first_seen", dl["AAA"] == 1 and dl["CCC"] == 0)

        # same-day rerun is idempotent (no re-flagging as new)
        r3 = history.update_history(d2, "daily:base", p, today="2026-01-02")
        check("same-day rerun keeps names not-NEW", list(r3["new"]) == ["", ""])

        # a different scope is tracked independently
        r4 = history.update_history(d2, "weekly:base", p, today="2026-01-02")
        check("separate scope flags its own names NEW", list(r4["new"]) == ["NEW", "NEW"])


# -------------------------------------------------------------- SECTORS -------
def test_sectors_reads_cache_without_network():
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sec.sqlite")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE sector_cache (symbol TEXT PRIMARY KEY, sector TEXT, "
                    "industry TEXT, fetched TEXT)")
        con.executemany("INSERT INTO sector_cache VALUES (?,?,?,?)",
                        [("PFE", "Healthcare", "Drug Manufacturers", "2026-01-01"),
                         ("AAPL", "Technology", "Consumer Electronics", "2026-01-01")])
        con.commit(); con.close()
        # fetch_missing=False guarantees no network; cached rows come back
        got = sectors.get_sectors(["AAPL", "PFE", "UNKNOWN_XYZ"], p, fetch_missing=False)
        check("cached sector returned", got["PFE"] == "Healthcare" and got["AAPL"] == "Technology")
        check("uncached symbol maps to empty string", got["UNKNOWN_XYZ"] == "")
        check("result keyed for every requested symbol", set(got) == {"AAPL", "PFE", "UNKNOWN_XYZ"})


def test_scan_run_adds_sector_column():
    from signals import scan_base_div as S
    from signals.config import Config
    from signals.data.service import DataService
    S.get_sp500 = lambda: ["KMX", "AXP"]
    S.load_broader = lambda *a, **k: []
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "sec.sqlite")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE sector_cache (symbol TEXT PRIMARY KEY, sector TEXT, "
                    "industry TEXT, fetched TEXT)")
        con.executemany("INSERT INTO sector_cache VALUES (?,?,?,?)",
                        [("KMX", "Consumer Cyclical", "", "2026-01-01"),
                         ("AXP", "Financial Services", "", "2026-01-01")])
        con.commit(); con.close()
        svc = DataService(Config.load(os.path.join(HERE, "config.yaml")))
        df = S.run_scan(svc, "sp500", 60, False, timeframe="daily", require_base=False,
                        add_sector=True, sector_file=p, desc="test")
        check("run_scan emits 'sector' column", "sector" in df.columns)
        if len(df):
            vals = set(df["sector"])
            check("sector values come from the cache",
                  vals <= {"Consumer Cyclical", "Financial Services", ""})


# ----------------------------------------------------------------- 4H ---------
def test_4h_timeframe_registered():
    from signals import scan_base_div as S
    from signals.data.base import Timeframe
    tf, min_bars, src = S._TF["4h"]
    check("4h maps to the H4 timeframe", tf == Timeframe.H4)
    check("4h reads from the polygon (intraday) source", src == "polygon")
    check("4h keeps a sane minimum-bars floor", min_bars >= 60)


def test_run_scan_routes_4h_to_polygon_source():
    # network-free: a fake service records what source/timeframe run_scan asks for
    from signals import scan_base_div as S
    from signals.data.base import Timeframe
    S.get_sp500 = lambda: ["AAA"]
    S.load_broader = lambda *a, **k: []
    seen = {}

    class FakeSvc:
        def get(self, ac, sym, tf, source=None):
            seen["source"], seen["tf"] = source, tf
            return pd.DataFrame()  # empty -> symbol skipped, loop still runs

    S.run_scan(FakeSvc(), "sp500", 30, False, timeframe="4h",
               require_base=False, desc="t")
    check("run_scan asks the polygon source for 4h", seen.get("source") == "polygon")
    check("run_scan requests H4 bars for 4h", seen.get("tf") == Timeframe.H4)


# ------------------------------------------------------------------ CRYPTO ----
def test_crypto_timeframe_map_registered():
    from signals import scan_base_div as S
    from signals.data.base import Timeframe
    for name, want_tf in (("daily", Timeframe.D1), ("weekly", Timeframe.W1),
                          ("4h", Timeframe.H4)):
        tf, min_bars, src = S._TF_CRYPTO[name]
        check(f"crypto {name} maps to {want_tf.name}", tf == want_tf)
        check(f"crypto {name} reads from the binance source", src == "binance")
        check(f"crypto {name} keeps a sane min-bars floor", min_bars >= 60)


def test_run_scan_routes_crypto_to_binance_and_drops_equity_enrich():
    # network-free: a fake service records the asset class + source run_scan uses,
    # and returns one usable frame so we can inspect the emitted row.
    from signals import scan_base_div as S
    from signals.data.base import AssetClass, Timeframe
    S.get_crypto_universe = lambda: ["BTCUSDT"]
    seen = {}

    def _frame():
        idx = pd.date_range("2023-01-01", periods=400, freq="D", tz="UTC")
        base = pd.Series(range(400), index=idx, dtype=float) + 100
        return pd.DataFrame({"open": base, "high": base + 1, "low": base - 1,
                             "close": base, "volume": 1000.0}, index=idx)

    class FakeSvc:
        def get(self, ac, sym, tf, source=None):
            seen["ac"], seen["source"], seen["tf"] = ac, source, tf
            return _frame()

    df = S.run_scan(FakeSvc(), "crypto", 60, True, timeframe="daily",
                    require_base=False, add_wdb=True, add_sector=True,
                    add_canslim=True, add_ai=True, desc="t")
    check("run_scan uses the CRYPTO asset class", seen.get("ac") == AssetClass.CRYPTO)
    check("run_scan asks the binance source for crypto", seen.get("source") == "binance")
    check("run_scan requests daily bars", seen.get("tf") == Timeframe.D1)
    check("crypto rows are tagged CRYPTO", (df["universe"] == "CRYPTO").all() if len(df) else True)
    check("crypto TV link points at BINANCE:",
          len(df) == 0 or df["tradingview_chart"].iloc[0].endswith("BINANCE:BTCUSDT"))
    check("equity-only WDB column dropped for crypto", "wdb" not in df.columns)
    check("equity-only sector column dropped for crypto", "sector" not in df.columns)
    check("CANSLIM still computed for crypto", "canslim" in df.columns)
    check("AI column still present for crypto", "ai_analysis" in df.columns)


# --------------------------------------------------------- DASHBOARD BUILD ----
def test_dashboard_builds_and_has_expected_tabs():
    # run the generator as a subprocess; assert the HTML has the daily tabs + boot
    subprocess.run([sys.executable, "build_dashboard.py"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL)
    html = open(os.path.join(HERE, "dashboard.html")).read()
    check("dashboard has a Daily base tab", 'data-tab="base"' in html)
    check("dashboard has a Daily recent tab", 'data-tab="recent"' in html)
    check("dashboard boots the base watchlist", "initWatch('base','base')" in html)
    check("dashboard labels the momentum proxy 'Trend'", "label:'Trend'" in html)
    check("dashboard defines the real CANSLIM + WDB columns",
          "label:'CANSLIM'" in html and "label:'WDB'" in html)
    check("data placeholder was filled", "/*__DATA__*/" not in html)
    check("weekly tabs present iff weekly CSV exists",
          (os.path.exists(os.path.join(HERE, "base_div_sheet.csv"))
           or os.path.exists(os.path.join(HERE, "recent_div_weekly.csv")))
          == ('data-tab="wbase"' in html or 'data-tab="wrecent"' in html))
    check("4h tab present iff 4h CSV exists",
          os.path.exists(os.path.join(HERE, "recent_div_4h.csv"))
          == ('data-tab="h4"' in html))
    check("crypto daily tab present iff crypto daily CSV exists",
          os.path.exists(os.path.join(HERE, "recent_div_crypto_daily.csv"))
          == ('data-tab="crypto"' in html))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(f"Running {len(tests)} enrichment/dashboard tests\n")
    for t in tests:
        t()
    print("\nALL TESTS PASSED")


if __name__ == "__main__":
    main()
