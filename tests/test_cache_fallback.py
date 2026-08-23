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


class TestDownloadIntradayCachedDecision:
    """Verify the fallback gate in download_intraday_cached."""

    def test_short_range_returns_5m_precise(self, tmp_path, monkeypatch):
        idx = pd.date_range("2025-01-06 15:55", periods=40, freq="24h", tz=ET)
        fresh = pd.DataFrame({"Open": [100.0] * 40, "Close": [101.0] * 40}, index=idx)
        monkeypatch.setattr("overnight_edge.data.bars_cache_dir", lambda: tmp_path)
        monkeypatch.setattr("overnight_edge.data.download_intraday_bars",
                            lambda *a, **k: fresh)
        monkeypatch.setattr("overnight_edge.data.download_daily_bars",
                            lambda *a, **k: pytest.fail("should not fall back"))
        bars, source = download_intraday_cached("SHORT", 30)
        assert source == "5m_precise"
        assert not bars.empty

    def test_wide_range_falls_back_to_daily(self, tmp_path, monkeypatch):
        idx = pd.date_range("2024-01-01", periods=10, freq="24h", tz=ET)
        fresh = pd.DataFrame({"Open": [100.0] * 10, "Close": [101.0] * 10}, index=idx)
        monkeypatch.setattr("overnight_edge.data.bars_cache_dir", lambda: tmp_path)
        monkeypatch.setattr("overnight_edge.data.download_intraday_bars",
                            lambda *a, **k: fresh)
        daily_idx = pd.date_range("2024-01-01", periods=500, freq="24h", tz=ET)
        daily = pd.DataFrame({"Open": [100.0] * 500, "Close": [101.0] * 500}, index=daily_idx)
        monkeypatch.setattr("overnight_edge.data.download_daily_bars",
                            lambda *a, **k: daily)
        bars, source = download_intraday_cached("AAPL", 300)
        assert source == "daily_fallback"
        assert len(bars) == 500


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


class TestMemoryCache:
    """Verify the in-memory session cache avoids redundant downloads."""

    def test_memory_cache_returns_same_object(self, monkeypatch):
        """A second call with the same key should not re-download."""
        import overnight_edge.data as data
        from overnight_edge.data import clear_memory_cache, download_intraday_cached

        clear_memory_cache()

        call_count = {"n": 0}

        def fake_download_intraday_bars(ticker, lookback_days, **kw):
            call_count["n"] += 1
            return pd.DataFrame()

        def fake_load_cached_bars(ticker):
            return pd.DataFrame()

        def fake_download_daily_bars(ticker, **kw):
            return pd.DataFrame()

        monkeypatch.setattr(data, "download_intraday_bars", fake_download_intraday_bars)
        monkeypatch.setattr(data, "load_cached_bars", fake_load_cached_bars)
        monkeypatch.setattr(data, "download_daily_bars", fake_download_daily_bars)

        download_intraday_cached("AAPL", 30)
        download_intraday_cached("AAPL", 30)

        # The in-memory cache should have served the second call without
        # re-downloading.
        assert call_count["n"] == 1
        clear_memory_cache()

    def test_clear_memory_cache(self, monkeypatch):
        """clear_memory_cache empties the cache so the next call re-downloads."""
        import overnight_edge.data as data
        from overnight_edge.data import clear_memory_cache, download_intraday_cached

        clear_memory_cache()

        call_count = {"n": 0}

        def fake_download_intraday_bars(ticker, lookback_days, **kw):
            call_count["n"] += 1
            return pd.DataFrame()

        monkeypatch.setattr(data, "download_intraday_bars", fake_download_intraday_bars)
        monkeypatch.setattr(data, "load_cached_bars", lambda t: pd.DataFrame())
        monkeypatch.setattr(data, "download_daily_bars", lambda t, **kw: pd.DataFrame())

        download_intraday_cached("MSFT", 30)
        clear_memory_cache()
        download_intraday_cached("MSFT", 30)

        assert call_count["n"] == 2
        clear_memory_cache()
