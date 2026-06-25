"""TD Sequential (Tom DeMark) — Setup and Countdown.

A faithful reproduction of the public DeMark TD Sequential algorithm.
The trader's "TD7 / TD9" refer to the *Setup* count reaching 7 (warning)
and 9 (a completed setup, a potential exhaustion / reversal point); the
"13" he mentions is the *Countdown* completion.

Two stages
----------
1. **TD Setup** — after a *price flip*, a run of 9 consecutive bars whose
   close is below (buy setup) / above (sell setup) the close 4 bars
   earlier. The run resets the moment a bar fails the condition.
   - *Perfection*: a buy setup is "perfected" when the low of bar 8 or 9
     is <= the lows of bars 6 and 7 (mirror for sell with highs). A
     perfected 9 is a stronger reversal signal.
   - *TDST level*: the extreme of the setup (highest high of a buy setup =
     resistance; lowest low of a sell setup = support). Used as a
     trend/cancellation reference.

2. **TD Countdown** — begins once a setup completes. A buy countdown
   increments (not necessarily consecutively) on bars whose close <= the
   *low* 2 bars earlier, up to 13. Bar 13 only qualifies if its low is
   <= the close recorded at countdown bar 8 (the standard qualifier);
   otherwise the count defers at 12 until a qualifying bar appears. A
   completed 13 is the primary exhaustion signal. An opposite setup
   completing cancels an in-progress countdown.

Output
------
``td_sequential(df)`` returns a DataFrame on the same index with columns::

    buy_setup, sell_setup            # 0..9
    buy_setup_perfected, sell_setup_perfected   # bool, true on the 9 bar
    buy_countdown, sell_countdown    # 0..13
    tdst_resistance, tdst_support    # forward-filled level lines
    price_flip                       # +1 bullish flip, -1 bearish flip, 0

Bullish events (buy setup 9, buy countdown 13) suggest downside
exhaustion -> support entries; bearish events suggest upside exhaustion
-> exit/short context.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def td_sequential(df: pd.DataFrame, countdown: bool = True) -> pd.DataFrame:
    c = df["close"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    n = len(df)

    buy_setup = np.zeros(n, dtype=int)
    sell_setup = np.zeros(n, dtype=int)
    buy_perf = np.zeros(n, dtype=bool)
    sell_perf = np.zeros(n, dtype=bool)
    buy_cd = np.zeros(n, dtype=int)
    sell_cd = np.zeros(n, dtype=int)
    tdst_res = np.full(n, np.nan)
    tdst_sup = np.full(n, np.nan)
    flip = np.zeros(n, dtype=int)

    bc = sc = 0                  # setup counts
    buy_bars: list[int] = []     # indices of current buy-setup run
    sell_bars: list[int] = []

    active_buy_cd = active_sell_cd = False
    bcd = scd = 0                # countdown counts
    bcd_close8 = scd_close8 = None

    for i in range(n):
        # ---- price flip (for annotation) ----
        if i >= 5:
            prev_below = c[i - 1] < c[i - 5]
            prev_above = c[i - 1] > c[i - 5]
            if c[i] > c[i - 4] and prev_below:
                flip[i] = 1     # bullish flip -> precedes a sell setup
            elif c[i] < c[i - 4] and prev_above:
                flip[i] = -1    # bearish flip -> precedes a buy setup

        # ---- TD Setup ----
        if i >= 4 and c[i] < c[i - 4]:           # buy-setup bar
            bc += 1
            sc = 0
            sell_bars = []
            buy_bars.append(i)
            buy_setup[i] = bc
            if bc == 9:
                bb = buy_bars[-9:]
                perfected = min(low[bb[7]], low[bb[8]]) <= min(low[bb[5]], low[bb[6]])
                buy_perf[i] = bool(perfected)
                tdst_res[i] = float(np.max(h[bb[0]: bb[8] + 1]))
                # completing a buy setup starts a buy countdown and
                # cancels any active sell countdown
                active_buy_cd, active_sell_cd = True, False
                bcd, bcd_close8 = 0, None
                bc, buy_bars = 0, []
        elif i >= 4 and c[i] > c[i - 4]:         # sell-setup bar
            sc += 1
            bc = 0
            buy_bars = []
            sell_bars.append(i)
            sell_setup[i] = sc
            if sc == 9:
                sb = sell_bars[-9:]
                perfected = max(h[sb[7]], h[sb[8]]) >= max(h[sb[5]], h[sb[6]])
                sell_perf[i] = bool(perfected)
                tdst_sup[i] = float(np.min(low[sb[0]: sb[8] + 1]))
                active_sell_cd, active_buy_cd = True, False
                scd, scd_close8 = 0, None
                sc, sell_bars = 0, []
        else:                                     # condition broke
            bc = sc = 0
            buy_bars = []
            sell_bars = []

        # ---- TD Countdown ----
        if countdown:
            if active_buy_cd and i >= 2 and c[i] <= low[i - 2]:
                if bcd < 12:
                    bcd += 1
                    buy_cd[i] = bcd
                    if bcd == 8:
                        bcd_close8 = c[i]
                else:  # candidate for 13 — apply the bar-8 qualifier
                    if bcd_close8 is None or low[i] <= bcd_close8:
                        bcd = 13
                        buy_cd[i] = 13
                        active_buy_cd = False
                    else:
                        buy_cd[i] = 12  # deferred

            if active_sell_cd and i >= 2 and c[i] >= h[i - 2]:
                if scd < 12:
                    scd += 1
                    sell_cd[i] = scd
                    if scd == 8:
                        scd_close8 = c[i]
                else:
                    if scd_close8 is None or h[i] >= scd_close8:
                        scd = 13
                        sell_cd[i] = 13
                        active_sell_cd = False
                    else:
                        sell_cd[i] = 12

    out = pd.DataFrame(
        {
            "buy_setup": buy_setup,
            "sell_setup": sell_setup,
            "buy_setup_perfected": buy_perf,
            "sell_setup_perfected": sell_perf,
            "buy_countdown": buy_cd,
            "sell_countdown": sell_cd,
            "tdst_resistance": tdst_res,
            "tdst_support": tdst_sup,
            "price_flip": flip,
        },
        index=df.index,
    )
    # carry TDST levels forward so they act as standing reference lines
    out["tdst_resistance"] = out["tdst_resistance"].ffill()
    out["tdst_support"] = out["tdst_support"].ffill()
    return out


def latest_state(df: pd.DataFrame) -> dict:
    """Compact summary of the most recent bar's TD Sequential state."""
    td = td_sequential(df)
    last = td.iloc[-1]
    return {
        "buy_setup": int(last.buy_setup),
        "sell_setup": int(last.sell_setup),
        "buy_setup_perfected": bool(last.buy_setup_perfected),
        "sell_setup_perfected": bool(last.sell_setup_perfected),
        "buy_countdown": int(last.buy_countdown),
        "sell_countdown": int(last.sell_countdown),
        "tdst_resistance": float(last.tdst_resistance) if pd.notna(last.tdst_resistance) else None,
        "tdst_support": float(last.tdst_support) if pd.notna(last.tdst_support) else None,
    }
