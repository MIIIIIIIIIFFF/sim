"""Unit tests for overnight strategy logic."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from overnight_edge.strategy import (
    backtest_buyhold_windowed,
    backtest_intraday_windowed,
    backtest_overnight,
    backtest_overnight_windowed,
    close_buy_price,
    compare_strategies,
    extract_intraday_trades,
    extract_overnight_trades,
    preopen_sell_price,
)
from tests.helpers import bars_from_specs


class TestCloseBuyPrice:
    def test_uses_last_regular_session_bar(self, two_day_scenario):
        monday = two_day_scenario.loc["2025-01-06"]
        price = close_buy_price(monday)
        assert price == 100.0

    def test_returns_none_without_regular_session(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 8, "minute": 0, "open_": 50.0, "close": 51.0},
        ])
        assert close_buy_price(bars) is None


class TestPreopenSellPrice:
    def test_uses_last_premarket_bar(self, two_day_scenario):
        tuesday = two_day_scenario.loc["2025-01-07"]
        price = preopen_sell_price(tuesday)
        assert price == 105.0

    def test_falls_back_to_open_when_no_premarket(self):
        d = date(2025, 1, 7)
        bars = bars_from_specs([
            {"day": d, "hour": 9, "minute": 30, "open_": 110.0, "close": 111.0},
        ])
        assert preopen_sell_price(bars) == 110.0


class TestExtractOvernightTrades:
    def test_single_overnight_hold(self, two_day_scenario):
        trades = extract_overnight_trades(two_day_scenario)
        assert len(trades) == 1
        assert trades[0].buy_price == 100.0
        assert trades[0].sell_price == 105.0
        assert trades[0].return_pct == pytest.approx(5.0)

    def test_skips_weekend_gap(self):
        fri = date(2025, 1, 10)
        mon = date(2025, 1, 13)
        bars = bars_from_specs([
            {"day": fri, "hour": 15, "minute": 55, "open_": 200.0, "close": 200.0},
            {"day": mon, "hour": 9, "minute": 25, "open_": 210.0, "close": 210.0},
        ])
        trades = extract_overnight_trades(bars)
        assert len(trades) == 1
        assert trades[0].buy_date == fri
        assert trades[0].sell_date == mon

    def test_compounded_two_nights(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = bars_from_specs([
            {"day": d1, "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
            {"day": d2, "hour": 9, "minute": 25, "open_": 102.0, "close": 102.0},
            {"day": d2, "hour": 15, "minute": 55, "open_": 102.0, "close": 102.0},
            {"day": d3, "hour": 9, "minute": 25, "open_": 105.06, "close": 105.06},
        ])
        result = backtest_overnight(bars, hold_count=10, min_trades=2)
        assert result is not None
        # Night 1: +2%, Night 2: +3% -> compounded 5.06%
        assert result.compounded_return_pct == pytest.approx(5.06, abs=0.01)
        assert result.ending_capital == pytest.approx(10_000 * 1.02 * 1.03)
        assert result.profit_usd == pytest.approx(506.0)
        assert result.trade_count == 2
        assert result.win_rate_pct == 100.0


class TestBacktestOvernight:
    def test_returns_none_when_insufficient_trades(self, two_day_scenario):
        result = backtest_overnight(two_day_scenario, hold_count=30, min_trades=5)
        assert result is None

    def test_max_drawdown_computed(self):
        d = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9)]
        bars = bars_from_specs([
            {"day": d[0], "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
            {"day": d[1], "hour": 9, "minute": 25, "open_": 90.0, "close": 90.0},
            {"day": d[1], "hour": 15, "minute": 55, "open_": 90.0, "close": 90.0},
            {"day": d[2], "hour": 9, "minute": 25, "open_": 99.0, "close": 99.0},
            {"day": d[2], "hour": 15, "minute": 55, "open_": 99.0, "close": 99.0},
            {"day": d[3], "hour": 9, "minute": 25, "open_": 108.9, "close": 108.9},
        ])
        result = backtest_overnight(bars, hold_count=10, min_trades=2)
        assert result is not None
        assert result.max_drawdown_pct < 0

    def test_limits_to_hold_count(self):
        days = [date(2025, 1, 6 + i) for i in range(6)]
        specs = []
        price = 100.0
        for i, day in enumerate(days):
            specs.append({"day": day, "hour": 15, "minute": 55, "open_": price, "close": price})
            if i < len(days) - 1:
                price *= 1.01
                specs.append({"day": days[i + 1], "hour": 9, "minute": 25, "open_": price, "close": price})
        bars = bars_from_specs(specs)
        result = backtest_overnight(bars, hold_count=3, min_trades=2)
        assert result is not None
        assert result.trade_count == 3

    def test_empty_bars_returns_none(self):
        assert backtest_overnight(pd.DataFrame(), hold_count=30) is None


class TestWindowed:
    def test_date_bracket_filters_buy_days(self):
        days = [date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8), date(2025, 1, 9), date(2025, 1, 10)]
        specs = []
        price = 100.0
        for i, day in enumerate(days):
            specs.append({"day": day, "hour": 15, "minute": 55, "open_": price, "close": price})
            if i < len(days) - 1:
                price *= 1.01
                specs.append({"day": days[i + 1], "hour": 9, "minute": 25, "open_": price, "close": price})
        bars = bars_from_specs(specs)
        full = backtest_overnight_windowed(bars)
        assert full is not None
        assert full.trade_count == 4
        windowed = backtest_overnight_windowed(bars, start_date=date(2025, 1, 8))
        assert windowed is not None
        assert windowed.trade_count == 2

    def test_max_trades_keeps_recent(self):
        days = [date(2025, 1, 6 + i) for i in range(6)]
        specs = []
        price = 100.0
        for i, day in enumerate(days):
            specs.append({"day": day, "hour": 15, "minute": 55, "open_": price, "close": price})
            if i < len(days) - 1:
                price *= 1.01
                specs.append({"day": days[i + 1], "hour": 9, "minute": 25, "open_": price, "close": price})
        bars = bars_from_specs(specs)
        result = backtest_overnight_windowed(bars, max_trades=3, min_trades=1)
        assert result is not None
        assert result.trade_count == 3


class TestIntraday:
    def test_extract_same_day_open_to_close(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 9, "minute": 30, "open_": 100.0, "close": 101.0},
            {"day": d, "hour": 15, "minute": 55, "open_": 109.0, "close": 110.0},
        ])
        trades = extract_intraday_trades(bars)
        assert len(trades) == 1
        assert trades[0].buy_date == d
        assert trades[0].sell_date == d
        assert trades[0].buy_price == 100.0
        assert trades[0].sell_price == 110.0
        assert trades[0].return_pct == pytest.approx(10.0)

    def test_compounds_across_days(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = bars_from_specs([
            {"day": d1, "hour": 9, "minute": 30, "open_": 100.0, "close": 100.0},
            {"day": d1, "hour": 15, "minute": 55, "open_": 102.0, "close": 102.0},
            {"day": d2, "hour": 9, "minute": 30, "open_": 102.0, "close": 102.0},
            {"day": d2, "hour": 15, "minute": 55, "open_": 103.02, "close": 103.02},
        ])
        result = backtest_intraday_windowed(bars)
        assert result is not None
        assert result.trade_count == 2
        assert result.compounded_return_pct == pytest.approx((1.02 * 1.01 - 1) * 100, abs=0.05)


class TestBuyHold:
    def test_single_net_trade(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = bars_from_specs([
            {"day": d1, "hour": 9, "minute": 30, "open_": 100.0, "close": 102.0},
            {"day": d1, "hour": 15, "minute": 55, "open_": 102.0, "close": 102.0},
            {"day": d2, "hour": 9, "minute": 30, "open_": 102.0, "close": 104.0},
            {"day": d2, "hour": 15, "minute": 55, "open_": 104.0, "close": 104.0},
            {"day": d3, "hour": 9, "minute": 30, "open_": 103.0, "close": 106.0},
            {"day": d3, "hour": 15, "minute": 55, "open_": 106.0, "close": 106.0},
        ])
        result = backtest_buyhold_windowed(bars)
        assert result is not None
        assert result.trade_count == 1
        # open day1 -> close day3 : 100 -> 106 = +6%
        assert result.compounded_return_pct == pytest.approx(6.0, abs=0.001)
        assert result.simple_return_pct == pytest.approx(6.0, abs=0.001)


class TestCompareStrategies:
    def test_all_three_keys_present(self):
        d1, d2, d3 = date(2025, 1, 6), date(2025, 1, 7), date(2025, 1, 8)
        bars = bars_from_specs([
            {"day": d1, "hour": 9, "minute": 30, "open_": 100.0, "close": 101.0},
            {"day": d1, "hour": 15, "minute": 55, "open_": 99.0, "close": 100.0},
            {"day": d1, "hour": 16, "minute": 0, "open_": 100.5, "close": 100.5},
            # premarket next day
            {"day": d2, "hour": 9, "minute": 25, "open_": 103.0, "close": 104.0},
            {"day": d2, "hour": 9, "minute": 30, "open_": 104.0, "close": 105.0},
            {"day": d2, "hour": 15, "minute": 55, "open_": 102.0, "close": 103.0},
            {"day": d2, "hour": 16, "minute": 0, "open_": 103.0, "close": 103.0},
            {"day": d3, "hour": 9, "minute": 25, "open_": 106.0, "close": 107.0},
        ])
        out = compare_strategies(bars, starting_capital=1000.0)
        assert set(out.keys()) == {"overnight", "intraday", "buyhold"}
        assert out["overnight"] is not None
        assert out["intraday"] is not None
        assert out["buyhold"] is not None
        # Same date window, comparable capital.
        assert out["overnight"].starting_capital == out["intraday"].starting_capital == 1000.0
