"""Headless usage-stress assertions for the Overnight Edge audit."""

from __future__ import annotations

import math
import pathlib
import sys
import tempfile
from datetime import date, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytz

from overnight_edge.compounding import (
    annotate_equity,
    compound_returns,
    nightly_return,
)
from overnight_edge.data import (
    _coverage_days,
    _merge_bars,
    load_cached_bars,
    normalize_bars,
    save_cached_bars,
)
from overnight_edge.strategy import (
    _daily_buyhold,
    _daily_intraday,
    backtest_overnight,
    backtest_overnight_daily_windowed,
    compare_strategies,
    extract_overnight_daily_trades,
)

ET = pytz.timezone("America/New_York")
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  ok    {name}")
    else:
        FAILURES.append(f"{name}: {detail}")
        print(f"  FAIL  {name}  {detail}")


def daily_bars(prices):
    """Daily OHLC bars from (date, open, close) tuples at 16:00 ET."""
    rows = []
    for d, o, c in prices:
        ts = ET.localize(datetime(d.year, d.month, d.day, 16, 0))
        rows.append({"timestamp": ts, "Open": float(o), "Close": float(c)})
    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


def five_min_for_prices(day_prices):
    """5-minute bars: 09:25 (pre-open) + 15:55 (close) per day."""
    rows = []
    for d, close, preopen in day_prices:
        rows.append({
            "timestamp": ET.localize(datetime(d.year, d.month, d.day, 15, 55)),
            "Open": close, "Close": close,
        })
        rows.append({
            "timestamp": ET.localize(datetime(d.year, d.month, d.day, 9, 25)),
            "Open": preopen, "Close": preopen,
        })
    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


def trading_days(start, end):
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_compounding():
    print("== Compounding ==")
    r = compound_returns([0.02, 0.03], starting_capital=10_000)
    check("+2% then +3% = 5.06% not 5.00%", abs(r.compounded_return_pct - 5.06) < 1e-9,
          f"got {r.compounded_return_pct}")
    check("equity path", list(r.equity_path) == [10_000.0, 10_200.0, 10_506.0], str(r.equity_path))

    s = compound_returns([0.10])
    check("single trade", s.equity_path == (10_000.0, 11_000.0), str(s.equity_path))

    z = compound_returns([])
    check("zero trades -> 0% unchanged", z.compounded_return_pct == 0.0 and z.ending_capital == 10_000.0)

    wipe = compound_returns([-1.0, 0.5])
    check("-100% wipes to 0 and stays 0", wipe.ending_capital == 0.0)

    big = compound_returns([2.0, 3.0])
    check(">100% gains compound", abs(big.compounded_return_pct - 1100.0) < 1e-6, str(big.compounded_return_pct))

    dd = compound_returns([0.5, -0.9, 0.5])
    check("drawdown bounded (-100,0)", -100.0 <= dd.max_drawdown_pct < 0, str(dd.max_drawdown_pct))


def test_edge_frames():
    print("== Empty / all-NaN frames ==")
    check("backtest empty -> None", backtest_overnight(pd.DataFrame(), 30) is None)
    check("daily backtest empty -> None", backtest_overnight_daily_windowed(pd.DataFrame()) is None)
    try:
        nightly_return(0, 10)
        check("nightly_return(0,..) raises", False)
    except ValueError:
        check("nightly_return(0,..) raises", True)
    # non-finite returns rejected by compound
    try:
        compound_returns([float("nan")])
        check("NaN return rejected", False)
    except ValueError:
        check("NaN return rejected", True)


def test_zero_capital():
    print("== Zero/negative capital guard ==")
    for cap in (0, -5):
        try:
            compound_returns([0.1], starting_capital=cap)
            check(f"compound_returns(capital={cap}) raises", False)
        except ValueError:
            check(f"compound_returns(capital={cap}) raises", True)
    try:
        annotate_equity([{"return_pct": 1.0}], 0)
        check("annotate_equity zero capital raises", False)
    except ValueError:
        check("annotate_equity zero capital raises", True)


def test_daily_fallback_consistency():
    print("== Daily fallback Overnight vs Intraday vs Buy & Hold ==")
    days = trading_days(date(2025, 1, 6), date(2025, 1, 10))
    rows = []
    for i, d in enumerate(days):
        o = 100.0 + i * 2
        c = o + 3.0
        rows.append((d, o, c))
    bars = daily_bars(rows)
    out = compare_strategies(bars, starting_capital=1000.0, source="daily_fallback")
    overnight, intraday, buyhold = out["overnight"], out["intraday"], out["buyhold"]
    check("overnight present", overnight is not None)
    check("intraday present", intraday is not None)
    check("buyhold present", buyhold is not None)
    if overnight and intraday and buyhold:
        check("intraday -> 5 trades", intraday.trade_count == 5, str(intraday.trade_count))
        check("buyhold single trade", buyhold.trade_count == 1)
        # Self-consistency: every intraday return must be (close_d / open_d - 1),
        # and the buyhold return must be (close_last / open_first - 1).
        for t in intraday.trades:
            expected = (t.sell_price / t.buy_price - 1.0) * 100.0
            check("intraday return matches bar math",
                  abs(t.return_pct - expected) < 1e-6, f"{t.return_pct} vs {expected}")
        buyhold_expected = (buyhold.trades[0].sell_price / buyhold.trades[0].buy_price - 1.0) * 100.0
        check("buyhold matches first-open/last-close",
              abs(buyhold.compounded_return_pct - buyhold_expected) < 1e-6)
        # Overnight on daily bars: close T -> open T+1
        check("overnight trades == 4", overnight.trade_count == 4, str(overnight.trade_count))


def test_single_day_and_gaps():
    print("== Single day / weekend gap / repeated timestamps ==")
    d = date(2025, 1, 6)
    check("single day daily -> None",
          backtest_overnight_daily_windowed(daily_bars([(d, 100, 105)])) is None)
    fri, mon = date(2025, 1, 10), date(2025, 1, 13)
    bars = daily_bars([(fri, 100.0, 102.0), (mon, 101.0, 104.0)])
    trades = extract_overnight_daily_trades(bars)
    check("weekend gap pairs one trade", len(trades) == 1, str(len(trades)))
    if trades:
        check("close Fri -> open Mon",
              abs(trades[0].buy_price - 102.0) < 1e-6 and abs(trades[0].sell_price - 101.0) < 1e-6)
    # repeated timestamps dedup
    a = five_min_for_prices([(d, 100.0, 100.0), (d + timedelta(days=1), 102.0, 102.0)])
    b = five_min_for_prices([(d, 100.0, 100.0), (d + timedelta(days=1), 102.0, 102.0)])
    merged = _merge_bars(a, b)
    check("merge dedups repeated timestamps", len(merged) == 4, f"len={len(merged)}")
    m5 = five_min_for_prices([(d, 100.0, 100.0), (d + timedelta(days=1), 101.0, 101.0)])
    res = backtest_overnight(m5, 30, min_trades=1)
    check("5m 1-night backtest", res is not None and res.trade_count == 1)


def test_daily_intraday_nan():
    print("== daily fallback NaN guard ==")
    d1, d2 = date(2025, 1, 6), date(2025, 1, 7)
    bars = daily_bars([(d1, 100.0, 102.0), (d2, float("nan"), 103.0)])
    out = _daily_intraday(bars, None, None, None, 1000.0)
    check("daily intraday skips NaN open", out is not None and out.trade_count == 1,
          f"got {None if out is None else out.trade_count}")
    # Buy&Hold only needs first Open + last Close; middle NaN Open is irrelevant.
    bh = _daily_buyhold(bars, None, None, 1000.0)
    check("daily buyhold tolerates middle NaN", bh is not None and bh.trade_count == 1)


def test_cache(tmp):
    print("== Cache roundtrip & merge ==")
    import overnight_edge.data as D
    old = D.bars_cache_dir
    D.bars_cache_dir = lambda: tmp
    try:
        a = five_min_for_prices([(date(2025, 1, 6), 100.0, 100.0)])
        save_cached_bars("CACHEME", a)
        loaded = load_cached_bars("CACHEME")
        check("cache roundtrip", not loaded.empty and len(loaded) == len(a))
        cov = _coverage_days(a)
        check("coverage_days >= 0", cov >= 0, str(cov))
    finally:
        D.bars_cache_dir = old


def test_variance_roundtrip(tmp):
    print("== history attach_variance / snapshots ==")
    from overnight_edge import history as H
    from overnight_edge.history import attach_variance, load_previous_snapshot, save_daily_snapshot
    old = H.history_dir
    H.history_dir = lambda: tmp
    try:
        df = pd.DataFrame({
            "rank": [1, 2], "ticker": ["AAP", "BBB"], "company": ["A", "B"],
            "sector": ["s", "x"], "compounded_return_pct": [5.0, -2.0],
            "ending_capital": [10500.0, 9800.0], "profit_usd": [500.0, -200.0],
            "avg_overnight_return_pct": [0.1, -0.1], "win_rate_pct": [70.0, 40.0],
            "max_drawdown_pct": [-1.0, -2.0], "trades": [30, 30],
        })
        save_daily_snapshot(df, "2026-08-20T12:00:00+00:00")
        prev, day = load_previous_snapshot("2026-08-21")
        check("snapshot roundtrip", day == "2026-08-20" and prev is not None, str(day))
        cur = pd.DataFrame({"rank": [2, 1], "ticker": ["AAA", "BBB"],
                            "compounded_return_pct": [3.0, 6.0]})
        out = H.attach_variance(cur, prev)
        needed = ["rank_change", "prev_rank", "compounded_delta_pct", "is_new"]
        check("variance columns added", all(c in out.columns for c in needed),
              str(list(out.columns)))
        out2 = H.attach_variance(cur, None)
        check("variance with no prev returns defaults",
              int(out2["rank_change"].iloc[0]) == 0 and bool(out2["is_new"].iloc[0]) is False)
    finally:
        H.history_dir = old


def test_long_history():
    print("== Long-history daily path (port) ==")
    start = date(2021, 1, 4)
    end = start + timedelta(days=5 * 365)
    days = trading_days(start, end)
    base = 100.0
    rows = []
    for d in days:
        c = base * 1.001
        rows.append((d, base, c))
        base = c
    bars = daily_bars(rows)
    res = backtest_overnight_daily_windowed(bars, starting_capital=1000.0)
    check("~5y daily backtest returns", res is not None)
    if res:
        check("many trades", res.trade_count > 200, str(res.trade_count))


def main():
    print("Overnight Edge audit stress — synthetic bars only")
    with tempfile.TemporaryDirectory() as td:
        tp = pathlib.Path(td)
        test_cache(tp)
        test_variance_roundtrip(tp)
    test_compounding()
    test_edge_frames()
    test_zero_capital()
    test_daily_fallback_consistency()
    test_single_day_and_gaps()
    test_daily_intraday_nan()
    test_long_history()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILURES")
        sys.exit(1)
    print("\nALL OK")


if __name__ == "__main__":
    main()