#!/usr/bin/env python3
"""Daily alert digest — the NEW names from the latest scan, written to a file.

Reads the same CSVs the dashboard consumes and collects every row flagged
``new == 'NEW'`` (the first day a name appears in a given scope; see
``signals/history.py``). Writes a dated Markdown digest to ``alerts/`` and
refreshes ``alerts/latest.md``. No email, no network — pure local file output,
so it works regardless of the SQLite-on-synced-folder caveat.

Intended to run right after ``refresh.py`` (which recomputes the NEW flags):

    python refresh.py --canslim --ai      # rescan + rebuild dashboard
    python alerts.py                       # write today's NEW-name digest

The first ever run flags everything NEW (no prior history); from the second run
on, only genuinely new names appear. Idempotent within a day: re-running
``refresh.py`` the same day clears the NEW flags, so a second digest is empty.
"""

from __future__ import annotations

import csv
import datetime as dt
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "alerts")

# scope label -> CSV file (same set the dashboard reads).
SCOPES = [
    ("Base + Divergence (Daily)", "base_div_sheet_daily.csv"),
    ("Recent Div (Daily)", "recent_div_daily.csv"),
    ("Base + Divergence (Weekly)", "base_div_sheet.csv"),
    ("Recent Div (Weekly)", "recent_div_weekly.csv"),
    ("Recent Div (4h)", "recent_div_4h.csv"),
    ("Crypto (Daily)", "recent_div_crypto_daily.csv"),
    ("Crypto (Weekly)", "recent_div_crypto_weekly.csv"),
    ("Crypto (4h)", "recent_div_crypto_4h.csv"),
]


def _load_new(fname):
    """Return the rows flagged NEW in ``fname`` (empty if file/col absent)."""
    path = os.path.join(HERE, fname)
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if (r.get("new") or "").strip().upper() == "NEW"]


def _fmt_row(r):
    sym = r.get("symbol", "?")
    univ = r.get("universe", "")
    dc = r.get("div_count", "")
    inds = r.get("div_indicators", "")
    close = r.get("close", "")
    last = r.get("div_last", "")
    tv = r.get("tradingview_chart", "")
    bits = [f"**{sym}**"]
    if univ:
        bits.append(univ)
    if dc:
        bits.append(f"{dc} div")
    if inds:
        bits.append(f"({inds})")
    if close:
        bits.append(f"${close}")
    if last:
        bits.append(f"last {last}")
    line = " · ".join(bits)
    if tv:
        line += f" · [chart]({tv})"
    return "- " + line


def build_digest(today=None):
    today = today or dt.date.today().isoformat()
    sections = []
    total = 0
    for label, fname in SCOPES:
        new = _load_new(fname)
        if not new:
            continue
        total += len(new)
        # Most divergences first for a useful reading order.
        new.sort(key=lambda r: _num(r.get("div_count")), reverse=True)
        body = "\n".join(_fmt_row(r) for r in new)
        sections.append(f"### {label} — {len(new)} new\n\n{body}")

    header = f"# Scanner alerts — {today}\n"
    if total == 0:
        return header + "\nNo new signals today.\n", 0
    summary = f"\n**{total} new** across {len(sections)} list(s).\n\n"
    return header + summary + "\n\n".join(sections) + "\n", total


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return -1.0


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    today = dt.date.today().isoformat()
    text, total = build_digest(today)

    dated = os.path.join(OUT_DIR, f"alert_{today}.md")
    with open(dated, "w") as f:
        f.write(text)
    with open(os.path.join(OUT_DIR, "latest.md"), "w") as f:
        f.write(text)

    print(f"alerts: {total} new signal(s) — wrote {os.path.relpath(dated, HERE)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
