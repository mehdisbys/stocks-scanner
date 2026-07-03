"""Sector / industry lookup for tickers, with a persistent cache.

Sectors barely change, so we fetch each symbol once from Yahoo and cache it in
SQLite (default ``sector_cache.sqlite``). Later runs are instant and offline.

    get_sectors(["AAPL", "PFE"]) -> {"AAPL": "Technology", "PFE": "Healthcare"}

Missing/unknown symbols (e.g. ETFs) map to "" and never raise.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Iterable

from .progress import track

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sector_cache (
    symbol   TEXT PRIMARY KEY,
    sector   TEXT,
    industry TEXT,
    fetched  TEXT
);
"""


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute(_SCHEMA)
    return con


def get_sectors(symbols: Iterable[str], path: str = "sector_cache.sqlite",
                fetch_missing: bool = True) -> dict:
    """Return ``{symbol: sector}`` for all ``symbols``, fetching any not yet
    cached (unless ``fetch_missing`` is False). Result is "" when unknown."""
    symbols = list(dict.fromkeys(symbols))  # de-dupe, keep order
    con = _connect(path)
    have = {r[0]: (r[1] or "") for r in con.execute("SELECT symbol, sector FROM sector_cache")}
    missing = [s for s in symbols if s not in have]

    if fetch_missing and missing:
        try:
            import yfinance as yf
        except ImportError:
            yf = None
        if yf is not None:
            today = dt.date.today().isoformat()
            for s in track(missing, desc="sectors", label=lambda x: x):
                sec, ind = "", ""
                try:
                    info = yf.Ticker(s).info
                    sec = info.get("sector") or ""
                    ind = info.get("industry") or ""
                except Exception:
                    pass
                con.execute("INSERT OR REPLACE INTO sector_cache(symbol, sector, industry, fetched) "
                            "VALUES (?,?,?,?)", (s, sec, ind, today))
                have[s] = sec
            con.commit()
    con.close()
    return {s: have.get(s, "") for s in symbols}
