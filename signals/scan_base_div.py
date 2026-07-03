"""Base + divergence watchlist scan (daily timeframe).

Reproduces the "bottom base confirmed by momentum/volume divergence" sheet,
but with divergences detected on **daily** bars (the original run used the
weekly resample). For each symbol it requires, on the latest bar:

  * a *base*: deep drawdown from the multi-year high AND price near the
    bottom of its range AND (consolidating OR quietly accumulating), and
  * at least one *bullish divergence* confirmed within a recent window,
    across the standard indicator panel (RSI, MACD, MFI, MVI, CMF, OBV,
    Williams %R, squeeze momentum).

Output columns match the original sheet:
    symbol, close, off_high, range_position, base_type, div_count,
    div_indicators, div_last, universe, tradingview_chart

Usage::

    python -m signals.scan_base_div                       # SP500 + broader
    python -m signals.scan_base_div --universe sp500      # SP500 only
    python -m signals.scan_base_div --recent-days 90 --out my_sheet.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .config import Config
from .data.base import AssetClass, Timeframe
from .data.service import DataService
from .data.universe import get_sp500, get_crypto_universe
from .indicators.base_consolidation import base_consolidation_signals
from .indicators.divergence import divergence_signals, CONFIRMED, POTENTIAL
from . import enrich
from . import history
from . import sectors
from .progress import track

# Panel key -> display name, in the order used by the original sheet.
_DISPLAY = [
    ("rsi", "RSI"), ("macd", "MACD"), ("mfi", "MFI"), ("mvi", "MVI"),
    ("cmf", "CMF"), ("obv", "OBV"), ("willr", "WILLR"), ("squeeze", "SQUEEZE"),
]


def load_broader(path: str | Path = "data/universe/broader.csv") -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [s.strip() for s in p.read_text().splitlines()[1:] if s.strip()]


def _num(x, ndigits):
    """Round, but pass NaN through as None so the CSV cell stays blank."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else round(f, ndigits)


def scan_symbol(df: pd.DataFrame, recent_days: int = 60,
                include_potential: bool = False, require_base: bool = True,
                min_bars: int = 252) -> dict | None:
    """Return a result row if the symbol has a recent bullish divergence
    (and, unless ``require_base`` is False, is also in a base), else ``None``.

    Note: the base-consolidation thresholds are calibrated for *daily* bars.
    On the weekly timeframe the ``off_high`` / ``range_position`` ratios are
    still meaningful, but ``base_type`` is most reliable on daily data.
    """
    if df is None or len(df) < min_bars:
        return None

    base = base_consolidation_signals(df)
    last = base.iloc[-1]
    if require_base:
        in_base = bool(last["deep_drawdown"] and last["near_lows"]
                       and (last["consolidating"] or last["accumulation"]))
        if not in_base:
            return None

    labels = []
    if last["consolidating"]:
        labels.append("consolidating")
    if last["accumulation"]:
        labels.append("accumulation")
    base_type = "|".join(labels)

    div = divergence_signals(df)
    # Window is the last `recent_days` *trading* bars (not calendar days).
    recent_idx = df.index[-recent_days:]

    wanted = {CONFIRMED} if not include_potential else {CONFIRMED, POTENTIAL}
    hits: list[tuple[str, pd.Timestamp]] = []
    for key, name in _DISPLAY:
        col = f"{key}_bull_div"
        if col not in div.columns:
            continue
        states = div.loc[recent_idx, col]
        active = states[states.isin(wanted)]
        if len(active):
            hits.append((name, active.index.max()))
    if not hits:
        return None

    div_last = max(ts for _, ts in hits)
    return {
        "symbol": None,  # filled by caller
        "close": _num(df["close"].iloc[-1], 2),
        "off_high": _num(last["drawdown_from_high"], 3),
        "range_position": _num(last["range_position"], 2),
        "base_type": base_type,
        "div_count": len(hits),
        "div_indicators": "|".join(n for n, _ in hits),
        "div_last": div_last.date().isoformat(),
    }


# Timeframe -> (Timeframe enum, minimum bars required, store source).
# Daily/weekly come from the long free history cache; 4h is resampled from
# Polygon 1h and lives under the "polygon" source (see DataService).
_TF = {
    "daily": (Timeframe.D1, 252, "history"),
    "weekly": (Timeframe.W1, 60, "history"),
    "4h": (Timeframe.H4, 120, "polygon"),
}

# Crypto timeframe map. All three come straight from Binance (daily/4h fetched,
# weekly resampled from daily by DataService.update_crypto) and live under the
# "binance" source. min_bars mirror the stock map, except daily is relaxed to
# 200 (base_consolidation's longest MA) so younger liquid coins still qualify.
_TF_CRYPTO = {
    "daily": (Timeframe.D1, 200, "binance"),
    "weekly": (Timeframe.W1, 60, "binance"),
    "4h": (Timeframe.H4, 120, "binance"),
}


def run_scan(svc: DataService, universe: str = "all", recent_days: int = 60,
             include_potential: bool = False, timeframe: str = "daily",
             require_base: bool = True, *, add_canslim: bool = False,
             add_canslim_real: bool = False,
             add_wdb: bool = False, add_ai: bool = False,
             add_sector: bool = False, sector_file: str = "sector_cache.sqlite",
             desc: str = "scanning") -> pd.DataFrame:
    is_crypto = universe == "crypto"
    asset_class = AssetClass.CRYPTO if is_crypto else AssetClass.STOCK
    tf, min_bars, src = (_TF_CRYPTO if is_crypto else _TF)[timeframe]

    targets: list[tuple[str, str]] = []
    if is_crypto:
        targets += [(s, "CRYPTO") for s in get_crypto_universe()]
    else:
        if universe in ("all", "sp500"):
            targets += [(s, "SP500") for s in get_sp500()]
        if universe in ("all", "broader"):
            targets += [(s, "broader") for s in load_broader()]

    # WDB (equity fundamentals), sector (GICS) and real CANSLIM (earnings,
    # institutions) are equity-only; silently drop them for crypto.
    if is_crypto:
        add_wdb = add_sector = add_canslim_real = False

    # 'M' (market direction) is one read shared by every symbol — fetch it once.
    market_ok = enrich.market_uptrend() if add_canslim_real else None

    rows = []
    for sym, tag in track(targets, desc=desc, label=lambda t: t[0]):
        df = svc.get(asset_class, sym, tf, source=src)
        res = scan_symbol(df, recent_days, include_potential,
                          require_base=require_base, min_bars=min_bars)
        if res is None:
            continue
        res["symbol"] = sym
        res["universe"] = tag
        res["tradingview_chart"] = (
            f"https://www.tradingview.com/chart/?symbol=BINANCE:{sym}" if is_crypto
            else f"https://www.tradingview.com/chart/?symbol={sym}")
        # Optional enrichment columns (each degrades gracefully).
        if add_canslim:
            # CANSLIM is a daily-bar check regardless of the scan timeframe.
            daily = (df if timeframe == "daily"
                     else svc.get(asset_class, sym, Timeframe.D1, source=src))
            c = enrich.canslim_technical(daily)
            res["canslim"] = c["label"] if c else "n/a"
        if add_canslim_real:
            daily = (df if timeframe == "daily"
                     else svc.get(asset_class, sym, Timeframe.D1, source=src))
            res["canslim_real"] = enrich.canslim_fundamental(sym, daily, market_ok)["label"]
        if add_wdb:
            res["wdb"] = enrich.wdb_value(sym)["label"]
        if add_ai:
            res["ai_analysis"] = enrich.ai_url(sym)
        rows.append(res)

    cols = ["symbol", "close", "off_high", "range_position", "base_type",
            "div_count", "div_indicators", "div_last", "universe",
            "tradingview_chart"]
    if add_sector:
        cols.insert(1, "sector")  # right after symbol
    if add_canslim:
        cols.append("canslim")
    if add_canslim_real:
        cols.append("canslim_real")
    if add_wdb:
        cols.append("wdb")
    if add_ai:
        cols.append("ai_analysis")

    if not rows:
        return pd.DataFrame(columns=cols)

    out = pd.DataFrame(rows)
    if add_sector:
        smap = sectors.get_sectors([r["symbol"] for r in rows], sector_file)
        out["sector"] = out["symbol"].map(smap).fillna("")
    # Most divergences first; within a tie, the deepest drawdown first.
    out = out.sort_values(["div_count", "off_high"],
                          ascending=[False, True]).reset_index(drop=True)
    return out[cols]


def push_to_gsheet(df: pd.DataFrame, title: str, cred_path: str | None = None,
                   share_email: str | None = None) -> str:
    """Create or overwrite a Google Sheet named ``title`` with ``df``.

    Auth uses a Google service-account key (``cred_path``, else the
    ``GSPREAD_SERVICE_ACCOUNT`` env var, else gspread's default location).
    Returns the spreadsheet URL.
    """
    try:
        import gspread
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "gspread is not installed. Run:\n"
            "    pip install gspread google-auth\n"
            "and set up a service account (see README).") from e

    import os
    cred = cred_path or os.environ.get("GSPREAD_SERVICE_ACCOUNT")
    gc = gspread.service_account(filename=cred) if cred else gspread.service_account()

    try:
        sh = gc.open(title)
    except gspread.SpreadsheetNotFound:
        sh = gc.create(title)
        if share_email:
            sh.share(share_email, perm_type="user", role="writer")

    ws = sh.sheet1
    ws.clear()
    # Header + rows; blanks (None/NaN) become empty cells.
    values = [list(df.columns)] + df.where(pd.notna(df), "").astype(object).values.tolist()
    ws.update(values, value_input_option="USER_ENTERED")
    return sh.url


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="scan_base_div",
                                description="Daily base + divergence watchlist")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--universe", default="all",
                   choices=["all", "sp500", "broader", "crypto"],
                   help="'crypto' scans the top Binance USDT pairs off the "
                        "binance cache (see populate_crypto.py)")
    p.add_argument("--recent-days", type=int, default=60,
                   help="number of recent bars (of the chosen timeframe) that "
                        "count as a 'recent' divergence")
    p.add_argument("--timeframe", default="daily", choices=["daily", "weekly", "4h"],
                   help="bars to detect divergences on (4h needs Polygon intraday "
                        "cache; see DataService.update_stock_live)")
    p.add_argument("--no-base", action="store_true",
                   help="report every recent divergence, not only names in a base")
    p.add_argument("--include-potential", action="store_true",
                   help="also count potential (unconfirmed) divergences")
    p.add_argument("--out", default="base_div_sheet_daily.csv")
    p.add_argument("--canslim", action="store_true",
                   help="add a Trend column: the technical proxy price>SMA20/50/200 & "
                        "RSI>50 (labelled 'Trend' in the dashboard)")
    p.add_argument("--canslim-real", action="store_true",
                   help="add a real CANSLIM column scored over C/A/N/L/I/M from Yahoo "
                        "fundamentals (earnings growth, relative strength, institutions, "
                        "market direction); stocks only, needs yfinance + internet")
    p.add_argument("--wdb", action="store_true",
                   help="add a WDB deep-value column (P/E<10, P/B<1, P/Cash<3); "
                        "needs yfinance + internet")
    p.add_argument("--ai", action="store_true",
                   help="add an ai_analysis column with a one-click Google AI Mode URL")
    p.add_argument("--sector", action="store_true",
                   help="add a sector column (e.g. Healthcare, Technology); "
                        "cached in --sector-file, needs yfinance + internet on first fetch")
    p.add_argument("--sector-file", default="sector_cache.sqlite",
                   help="SQLite cache of symbol -> sector")
    p.add_argument("--enrich", action="store_true",
                   help="shortcut for --canslim --canslim-real --wdb --ai --sector")
    p.add_argument("--history", action="store_true",
                   help="track first/last-seen and add new/first_seen/days_on_list "
                        "columns (state persisted in --history-file)")
    p.add_argument("--history-file", default="signal_history.sqlite",
                   help="SQLite DB where signal history is stored")
    p.add_argument("--gsheet", metavar="TITLE",
                   help="also push results to a Google Sheet with this title "
                        "(created if missing); needs gspread + a service account")
    p.add_argument("--gsheet-cred", metavar="PATH",
                   help="service-account JSON (else $GSPREAD_SERVICE_ACCOUNT "
                        "or gspread's default location)")
    p.add_argument("--gsheet-share", metavar="EMAIL",
                   help="share a newly created sheet with this email (writer)")
    args = p.parse_args(argv)

    add_canslim = args.canslim or args.enrich
    add_canslim_real = args.canslim_real or args.enrich
    add_wdb = args.wdb or args.enrich
    add_ai = args.ai or args.enrich
    add_sector = args.sector or args.enrich

    desc = ("recent-div" if args.no_base else "base-div") + f"/{args.timeframe}"

    svc = DataService(Config.load(args.config))
    df = run_scan(svc, args.universe, args.recent_days, args.include_potential,
                  timeframe=args.timeframe, require_base=not args.no_base,
                  add_canslim=add_canslim, add_canslim_real=add_canslim_real,
                  add_wdb=add_wdb, add_ai=add_ai,
                  add_sector=add_sector, sector_file=args.sector_file,
                  desc=desc)
    if args.history:
        prefix = "crypto:" if args.universe == "crypto" else ""
        scope = f"{prefix}{args.timeframe}:{'recent' if args.no_base else 'base'}"
        df = history.update_history(df, scope, args.history_file)
        n_new = int((df["new"] == "NEW").sum()) if len(df) else 0
        print(f"history: {scope} — {n_new} new / {len(df)} total")
    df.to_csv(args.out, index=False)
    print(f"{len(df)} matches written to {args.out}")
    if len(df):
        print(df.head(20).to_string(index=False))
    if args.gsheet:
        url = push_to_gsheet(df, args.gsheet, args.gsheet_cred, args.gsheet_share)
        print(f"Google Sheet updated: {url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
