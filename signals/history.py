"""Signal persistence — track when each scan hit first/last appeared.

State lives in a small SQLite DB (default ``signal_history.sqlite``) in a table
keyed by ``(scope, symbol)``, where scope is e.g. ``daily:base`` /
``weekly:recent``. Each scan run upserts the current hits and returns the frame
with three columns added:

    new           'NEW' the first run a symbol appears in this scope, else ''
    first_seen    ISO date it first appeared
    days_on_list  calendar days since first_seen

This gives the dashboard a "new today" view and how long a name has been on the
list, and is the foundation for alerts ("tell me the new ones"). Symbols that
drop off keep their stored ``last_seen`` (so history is never lost).

Note: SQLite on some networked/cloud-synced folders can throw
``disk I/O error``; keep the DB on a local path (same caveat as ``meta.sqlite``).
"""

from __future__ import annotations

import datetime as dt
import sqlite3

import pandas as pd

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_history (
    scope          TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    first_seen     TEXT NOT NULL,
    last_seen      TEXT NOT NULL,
    seen_count     INTEGER NOT NULL,
    last_div_count TEXT,
    PRIMARY KEY (scope, symbol)
);
"""


def _connect(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute(_SCHEMA)
    return con


def update_history(df: pd.DataFrame, scope: str,
                   path: str = "signal_history.sqlite",
                   today: str | None = None) -> pd.DataFrame:
    """Upsert the current hits for ``scope`` and return ``df`` with
    ``new`` / ``first_seen`` / ``days_on_list`` columns.

    Idempotent within a day: re-running on the same ``today`` won't double-count
    ``seen_count`` or re-flag names as new.
    """
    if today is None:
        today = dt.date.today().isoformat()

    new_col, first_col, days_col = [], [], []
    con = _connect(path)
    try:
        for _, row in df.iterrows():
            sym = str(row["symbol"])
            prev = con.execute(
                "SELECT first_seen, last_seen, seen_count FROM signal_history "
                "WHERE scope=? AND symbol=?", (scope, sym)).fetchone()
            if prev and prev[0]:
                first, is_new = prev[0], False
                seen = int(prev[2] or 0) + (0 if prev[1] == today else 1)
            else:
                first, is_new, seen = today, True, 1
            # keep original first_seen on conflict; refresh the rest
            con.execute(
                "INSERT INTO signal_history "
                "(scope, symbol, first_seen, last_seen, seen_count, last_div_count) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(scope, symbol) DO UPDATE SET "
                "  last_seen=excluded.last_seen, seen_count=excluded.seen_count, "
                "  last_div_count=excluded.last_div_count",
                (scope, sym, first, today, seen, str(row.get("div_count", ""))))
            new_col.append("NEW" if is_new else "")
            first_col.append(first)
            try:
                days_col.append((dt.date.fromisoformat(today) - dt.date.fromisoformat(first)).days)
            except ValueError:
                days_col.append("")
        con.commit()
    finally:
        con.close()

    out = df.copy()
    out["new"], out["first_seen"], out["days_on_list"] = new_col, first_col, days_col
    return out
