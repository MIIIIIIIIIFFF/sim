"""Edge-case tests for the audit: empty/NaN frames, zero capital, lookback=0,
daily-fallback path, and ticker dedup."""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
import pytz

from overnight_edge.compounding import annotate_equity, compound_returns
from overnight_edge.data import _coverage_days, _merge_bars, normalize_bars
from overnight_edge.strategy import (
    backtest_overnight,
    backtest_overnight_daily_windowed,
    compare_strategies,
)
from overnight_edge.universe import parse_ticker_list
from tests.helpers import bars_from_specs

ET = pytz.timezone("America/New_York")


def _daily_bars(prices):
    rows = []
    for d, o, c in prices:
        ts = ET.localize(datetime(d.year, d.month, d.day, 16, 0))
        rows.append({"timestamp": ts, "Open": o, "Close": c})
    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


def _trading_days(start, end):
    out = []
    d = start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def test_empty_dataframe_returns_none():
    assert backtest_overnight(pd.DataFrame(), 30) is None
    assert backtest_overnight_daily_windowed(pd.DataFrame()) is None


def test_all_nan_columns_do_not_crash():
    idx = pd.date_range("2025-01-06 09:25", periods=4, freq="5min", tz=ET)
    df = pd.DataFrame({"Open": [np.nan] * 4, "Close": [np.nan] * 4}, index=idx)
    out = normalize_bars(df)
    # Should not raise; empty-able selection yields [] trades / None.
    assert backtest_overnight(out, 30) is None
    assert backtest_overnight_daily_windowed(out) is None


def test_single_trade_backtest():
    d1, d2 = date(2025, 1, 6), date(2025, 1, 7)
    bars = bars_from_specs([
        {"day": d1, "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
        {"day": d2, "hour": 9, "minute": 25, "open_": 105.0, "close": 105.0},
    ])
    res = backtest_overnight(bars, hold_count=10, min_trades=1)
    assert res is not None
    assert res.trade_count == 1
    assert res.compounded_return_pct == pytest.approx(5.0)


def test_zero_starting_capital_raises():
    with pytest.raises(ValueError):
        compound_returns([0.1], starting_capital=0)
    with pytest.raises(ValueError):
        compound_returns([0.1], starting_capital=-10)
    with pytest.raises(ValueError):
        annotate_equity([{"return_pct": 1.0}], 0)


def test_lookback_zero_marks_insufficient_but_no_raise():
    # A tiny lookback with an empty/NA window should return None, not crash.
    res = backtest_overnight(pd.DataFrame(), 0)
    assert res is None


def test_monthy_max_daily_path_uses_many_trading_days():
    start = date(2021, 1, 4)
    end = start + timedelta(days=365 * 2)
    days = _trading_days(start, end)
    base = 100.0
    rows = []
    for d in days:
        c = base * 1.0005
        rows.append((d, base, c))
        base = c
    bars = _daily_bars(rows)
    res = backtest_overnight_daily_windowed(bars, starting_capital=1000.0)
    assert res is not None
    assert res.trade_count > 200


def test_ticker_list_dedups_duplicates():
    assert parse_ticker_list("AAPL, MSFT, AAPL, nvda") == ["AAPL", "MSFT", "NVDA"]
    assert parse_ticker_list("aapl") == ["AAPL"]


def test_merge_handles_fresh_or_cached_empty():
    a = bars_from_specs([{"day": date(2025, 1, 6), "hour": 15, "minute": 55,
                          "open_": 100.0, "close": 100.0}])
    merged = _merge_bars(pd.DataFrame(), a)
    assert len(merged) == len(a)
    merged2 = _merge_bars(a, pd.DataFrame())
    assert len(merged2) == len(a)


def test_coverage_days():
    bars = bars_from_specs([
        {"day": date(2025, 1, 6), "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
        {"day": date(2025, 1, 8), "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
    ])
    assert _coverage_days(bars) == 2
    assert _coverage_days(pd.DataFrame()) == 0


def test_compare_strategies_overnight_vs_intraday_same_window():
    d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
    bars = _daily_bars([
        (d1, 100.0, 103.0),
        (d2, 104.0, 106.0),
        (d3, 109.0, 110.0),
    ])
    out = compare_strategies(bars, source="daily_fallback", starting_capital=1000.0)
    assert out["overnight"] is not None
    assert out["intraday"] is not None
    assert out["buyhold"] is not None
    assert out["intraday"].trade_count == 3