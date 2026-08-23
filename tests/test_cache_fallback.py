"""Tests for the local 5-minute cache and daily-bar fallback."""

from __future__ import annotations

import pandas as pd
import pytz
import pytest
from datetime import date, datetime

from overnight_edge.data import (
    _merge_bars,
    download_intraday_cached,
    load_cached_bars,
    save_cached_bars,
)
from overnight_edge.strategy import (
    backtest_overnight_daily_windowed,
    compare_strategies,
    extract_overnight_daily_trades,
)
from tests.helpers import bars_from_specs

ET = pytz.timezone("America/New_York")


def _daily_bars(prices):
    """Build daily Open/Close bars from (date, open, close) tuples."""
    rows = []
    for d, o, c in prices:
        ts = ET.localize(datetime(d.year, d.month, d.day, 16, 0))
        rows.append({"timestamp": ts, "Open": o, "Close": c})
    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


class TestCache:
    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("overnight_edge.data.bars_cache_dir", lambda: tmp_path)
        bars = bars_from_specs(
            [{"day": date(2025, 1, 6), "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0}]
        )
        save_cached_bars("TEST", bars)
        loaded = load_cached_bars("TEST")
        assert not loaded.empty
        assert len(loaded) == len(bars)

    def test_merge_dedups_by_timestamp(self):
        a = bars_from_specs(
            [{"day": date(2025, 1, 6), "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0}]
        )
        b = bars_from_specs(
            [
                {"day": date(2025, 1, 6), "hour": 15, "minute": 55, "open_": 101.0, "close": 101.0},
                {"day": date(2025, 1, 7), "hour": 9, "minute": 25, "open_": 105.0, "close": 105.0},
            ]
        )
        merged = _merge_bars(a, b)
        assert len(merged) == 2
        # Duplicate timestamp keeps the freshest (b's 101.0).
        assert float(merged.loc[merged.index[0]]["Close"]) == 101.0


class TestDailyFallbackExtraction:
    def test_pairs_close_to_next_open(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = _daily_bars([
            (d1, 100.0, 102.0),   # close 102
            (d2, 103.0, 101.0),   # open 103 (sell from d1->d2), close 101
            (d3, 100.0, 105.0),   # open 100 (sell from d2->d3)
        ])
        trades = extract_overnight_daily_trades(bars)
        assert len(trades) == 2
        assert trades[0].buy_price == 102.0 and trades[0].sell_price == 103.0
        assert trades[1].buy_price == 101.0 and trades[1].sell_price == 100.0
        assert trades[0].buy_price_source == "daily_close"
        assert trades[0].sell_price_source == "daily_open"

    def test_backtest_compounds(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = _daily_bars([
            (d1, 100.0, 100.0),
            (d2, 102.0, 102.0),   # +2%
            (d3, 103.02, 103.02), # +1%
        ])
        result = backtest_overnight_daily_windowed(bars, starting_capital=1000.0)
        assert result is not None
        assert result.compounded_return_pct == pytest.approx((1.02 * 1.01 - 1) * 100)


class TestCompareStrategiesDaily:
    def test_daily_source_uses_daily_paths(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = _daily_bars([
            (d1, 100.0, 102.0),
            (d2, 104.0, 103.0),
            (d3, 106.0, 108.0),
        ])
        out = compare_strategies(bars, starting_capital=1000.0, source="daily_fallback")
        assert set(out.keys()) == {"overnight", "intraday", "buyhold"}
        # Overnight: close T -> open T+1
        assert out["overnight"] is not None
        # Intraday: open T -> close T (one per day)
        assert out["intraday"] is not None
        assert out["intraday"].trade_count == 3
        # Buy & Hold: open day1 -> close day3
        assert out["buyhold"] is not None
        assert out["buyhold"].trade_count == 1
