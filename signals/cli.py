"""Command-line entry point for the data layer.

Examples::

    python -m signals.cli coverage
    python -m signals.cli fetch-crypto --symbol BTCUSDT --timeframe 1d
    python -m signals.cli fetch-crypto --top --timeframe 4h
    python -m signals.cli fetch-stock-history --symbol AAPL
    python -m signals.cli fetch-stock-history --sp500
    python -m signals.cli fetch-stock-live --symbol AAPL --timeframe 4h
"""

from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from .config import Config
from .data.base import AssetClass, Timeframe
from .data.resample import resample
from .data.service import DataService
from .data.universe import get_crypto_universe, get_sp500
from .indicators.trend import build_context
from .scoring.engine import ScoringConfig, ScoringEngine
from .backtest.engine import run_backtest
from .backtest.tuning import split_backtest, sweep_thresholds


def _tf(s: str) -> Timeframe:
    return Timeframe(s)


def cmd_coverage(svc: DataService, _: argparse.Namespace) -> None:
    cov = svc.store.coverage()
    if cov.empty:
        print("No data cached yet.")
        return
    print(cov.to_string(index=False))


def cmd_fetch_crypto(svc: DataService, args: argparse.Namespace) -> None:
    symbols = get_crypto_universe() if args.top else [args.symbol]
    tf = _tf(args.timeframe)
    for i, sym in enumerate(symbols, 1):
        try:
            n = svc.update_crypto(sym, tf)
            print(f"[{i}/{len(symbols)}] {sym} {tf.value}: {n} rows cached")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(symbols)}] {sym} {tf.value}: ERROR {e}",
                  file=sys.stderr)
        time.sleep(0.2)


def cmd_fetch_stock_history(svc: DataService, args: argparse.Namespace) -> None:
    symbols = get_sp500() if args.sp500 else [args.symbol]
    for i, sym in enumerate(symbols, 1):
        try:
            n = svc.update_stock_history(sym)
            print(f"[{i}/{len(symbols)}] {sym} daily history: {n} rows cached")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(symbols)}] {sym}: ERROR {e}", file=sys.stderr)
        time.sleep(0.2)


def cmd_fetch_stock_live(svc: DataService, args: argparse.Namespace) -> None:
    symbols = get_sp500() if args.sp500 else [args.symbol]
    tf = _tf(args.timeframe)
    for i, sym in enumerate(symbols, 1):
        try:
            n = svc.update_stock_live(sym, tf)
            print(f"[{i}/{len(symbols)}] {sym} {tf.value} (live): {n} rows cached")
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(symbols)}] {sym}: ERROR {e}", file=sys.stderr)
        time.sleep(0.2)


def cmd_signal(svc: DataService, args: argparse.Namespace) -> None:
    eng = ScoringEngine(ScoringConfig.load(args.scoring))
    sym = args.symbol

    if args.asset == "crypto":
        if svc.get(AssetClass.CRYPTO, sym, Timeframe.D1).empty or args.refresh:
            svc.update_crypto(sym, Timeframe.D1,
                              start=pd.Timestamp.utcnow() - pd.Timedelta(days=900))
        daily = svc.get(AssetClass.CRYPTO, sym, Timeframe.D1)
        h4 = svc.get(AssetClass.CRYPTO, sym, Timeframe.H4)
    else:
        if svc.get(AssetClass.STOCK, sym, Timeframe.D1, source="history").empty or args.refresh:
            svc.update_stock_history(sym)
        daily = svc.get(AssetClass.STOCK, sym, Timeframe.D1, source="history")
        h4 = daily  # no intraday stock history on free tier; daily proxy

    if daily.empty:
        print(f"No data for {sym}.", file=sys.stderr)
        return

    weekly = resample(daily, Timeframe.W1)
    ctx = build_context(weekly, daily, h4 if not h4.empty else daily)

    print(f"{sym} ({args.asset}) — data through {daily.index.max().date()}, "
          f"{len(daily)} daily bars")
    print(f"trend: {ctx.labels}\n")

    # recent signals
    ss = eng.score_series(daily)
    cutoff = daily.index.max() - pd.Timedelta(days=args.days)
    recent = ss[(ss.index >= cutoff) & (ss.entry_signal | ss.exit_signal)]
    if len(recent):
        print(f"Signals in last {args.days} days:")
        for ts, row in recent.iterrows():
            kind = "ENTRY" if row.entry_signal else "EXIT"
            sc = row.entry_score if row.entry_signal else row.exit_score
            pos = daily.index.get_loc(ts)
            res = eng.evaluate(daily, at=pos)
            bd = res.entry_breakdown if row.entry_signal else res.exit_breakdown
            detail = ", ".join(f"{k}+{v:g}" for k, v in bd.items())
            print(f"  {ts.date()}  {kind:5}  score={sc:.1f}  close={daily.loc[ts,'close']:.2f}")
            print(f"           {detail}")
    else:
        print(f"No entry/exit signals in the last {args.days} days.")

    print("\nLatest bar:")
    print(eng.evaluate(daily, trend=ctx).summary())
    print("\nNote: weights are untuned (pre-backtest). Not financial advice.")


def _load_symbol(svc: DataService, sym: str, asset: str, refresh: bool):
    if asset == "crypto":
        if svc.get(AssetClass.CRYPTO, sym, Timeframe.D1).empty or refresh:
            svc.update_crypto(sym, Timeframe.D1,
                              start=pd.Timestamp.utcnow() - pd.Timedelta(days=365 * 9))
        return svc.get(AssetClass.CRYPTO, sym, Timeframe.D1)
    if svc.get(AssetClass.STOCK, sym, Timeframe.D1, source="history").empty or refresh:
        svc.update_stock_history(sym)
    return svc.get(AssetClass.STOCK, sym, Timeframe.D1, source="history")


def cmd_backtest(svc: DataService, args: argparse.Namespace) -> None:
    cfg = ScoringConfig.load(args.scoring)
    df = _load_symbol(svc, args.symbol, args.asset, args.refresh)
    if df.empty:
        print(f"No data for {args.symbol}.", file=sys.stderr)
        return
    bt = dict(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps,
              stop_pct=args.stop_pct, max_hold=args.max_hold)
    print(f"{args.symbol} ({args.asset}) — {len(df)} bars, "
          f"{df.index.min().date()} -> {df.index.max().date()}\n")

    if args.split:
        ins, outs = split_backtest(df, cfg, args.split, **bt)
        print(ins.report(f"IN-SAMPLE (< {args.split})"))
        print()
        print(outs.report(f"OUT-OF-SAMPLE (>= {args.split})"))
    else:
        res = run_backtest(df, ScoringEngine(cfg), **bt)
        print(res.report("(full history)"))

    if args.sweep:
        print("\nThreshold sweep (entry x exit):")
        sw = sweep_thresholds(df, cfg, entry_values=[5, 6, 7, 8],
                              exit_values=[4, 5, 6], **bt)
        sw = sw.sort_values("profit_factor", ascending=False)
        with pd.option_context("display.width", 120):
            print(sw.to_string(index=False,
                  formatters={"win_rate": "{:.1%}".format,
                              "expectancy": "{:+.2%}".format,
                              "total_return": "{:+.1%}".format,
                              "max_drawdown": "{:.1%}".format,
                              "profit_factor": "{:.2f}".format}))
    print("\nNote: results are backtested (not forward-tested). Not financial advice.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="signals", description="Signals data layer")
    p.add_argument("--config", default="config.yaml")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("coverage", help="show what data is cached")

    c = sub.add_parser("fetch-crypto", help="fetch crypto OHLCV from Binance")
    g = c.add_mutually_exclusive_group(required=True)
    g.add_argument("--symbol")
    g.add_argument("--top", action="store_true", help="all top crypto pairs")
    c.add_argument("--timeframe", default="1d", choices=[t.value for t in Timeframe])

    h = sub.add_parser("fetch-stock-history",
                       help="fetch long daily history from Stooq")
    gg = h.add_mutually_exclusive_group(required=True)
    gg.add_argument("--symbol")
    gg.add_argument("--sp500", action="store_true", help="full S&P 500")

    l = sub.add_parser("fetch-stock-live",
                       help="fetch live/intraday from Polygon (needs key)")
    gl = l.add_mutually_exclusive_group(required=True)
    gl.add_argument("--symbol")
    gl.add_argument("--sp500", action="store_true")
    l.add_argument("--timeframe", default="1d",
                   choices=[t.value for t in Timeframe])

    s = sub.add_parser("signal", help="score one symbol and show recent signals")
    s.add_argument("--symbol", required=True, help="e.g. AAPL or BTCUSDT")
    s.add_argument("--asset", default="stock", choices=["stock", "crypto"])
    s.add_argument("--days", type=int, default=120, help="recent window for signals")
    s.add_argument("--scoring", default="scoring.yaml")
    s.add_argument("--refresh", action="store_true", help="re-fetch latest data first")

    b = sub.add_parser("backtest", help="backtest the scoring engine on a symbol")
    b.add_argument("--symbol", required=True)
    b.add_argument("--asset", default="stock", choices=["stock", "crypto"])
    b.add_argument("--scoring", default="scoring.yaml")
    b.add_argument("--split", help="train/test split date YYYY-MM-DD (out-of-sample from here)")
    b.add_argument("--sweep", action="store_true", help="grid-sweep entry/exit thresholds")
    b.add_argument("--fee-bps", type=float, default=10.0)
    b.add_argument("--slippage-bps", type=float, default=5.0)
    b.add_argument("--stop-pct", type=float, default=None, help="e.g. 0.08 = 8% stop")
    b.add_argument("--max-hold", type=int, default=None, help="max bars to hold")
    b.add_argument("--refresh", action="store_true")
    return p


_HANDLERS = {
    "coverage": cmd_coverage,
    "fetch-crypto": cmd_fetch_crypto,
    "fetch-stock-history": cmd_fetch_stock_history,
    "fetch-stock-live": cmd_fetch_stock_live,
    "signal": cmd_signal,
    "backtest": cmd_backtest,
}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    svc = DataService(Config.load(args.config))
    _HANDLERS[args.command](svc, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
