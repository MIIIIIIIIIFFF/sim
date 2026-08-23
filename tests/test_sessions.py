"""Tests for 5-minute bar session selection logic."""

from __future__ import annotations

from datetime import date, time

import pandas as pd
import pytest
import pytz

from overnight_edge.sessions import (
    _day_slice,
    has_regular_session,
    select_close_buy,
    select_preopen_sell,
    trading_days_with_session,
)
from tests.helpers import bars_from_specs

ET = pytz.timezone("America/New_York")


class TestSelectCloseBuy:
    def test_prefers_1600_bar_over_1555(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 15, "minute": 55, "open_": 99.0, "close": 99.5},
            {"day": d, "hour": 16, "minute": 0, "open_": 99.5, "close": 100.0},
            {"day": d, "hour": 16, "minute": 5, "open_": 100.0, "close": 100.5},  # after-hours
        ])
        point = select_close_buy(bars)
        assert point is not None
        assert point.price == 100.0
        assert point.bar_time.time() == time(16, 0)
        assert point.source == "regular_close_1600"

    def test_excludes_post_market(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 15, "minute": 55, "open_": 50.0, "close": 50.0},
            {"day": d, "hour": 16, "minute": 5, "open_": 99.0, "close": 99.0},
        ])
        point = select_close_buy(bars)
        assert point.price == 50.0

    def test_uses_1555_when_no_1600_bar(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 15, "minute": 55, "open_": 42.0, "close": 42.5},
        ])
        point = select_close_buy(bars)
        assert point.price == 42.5
        assert point.source == "regular_close_1555"


class TestSelectPreopenSell:
    def test_uses_0925_bar_not_0930(self):
        d = date(2025, 1, 7)
        bars = bars_from_specs([
            {"day": d, "hour": 9, "minute": 25, "open_": 104.0, "close": 105.0},
            {"day": d, "hour": 9, "minute": 30, "open_": 106.0, "close": 107.0},
        ])
        point = select_preopen_sell(bars)
        assert point is not None
        assert point.price == 105.0
        assert point.bar_time.time() == time(9, 25)
        assert point.source == "premarket_0925"

    def test_excludes_regular_session_for_exit(self):
        d = date(2025, 1, 7)
        bars = bars_from_specs([
            {"day": d, "hour": 9, "minute": 30, "open_": 200.0, "close": 201.0},
        ])
        point = select_preopen_sell(bars)
        assert point.price == 200.0
        assert point.source == "fallback_open_0930"

    def test_premarket_0929_boundary(self):
        """09:30 bar must NOT be used when premarket bars exist up to 09:25."""
        d = date(2025, 1, 7)
        bars = bars_from_specs([
            {"day": d, "hour": 9, "minute": 20, "open_": 10.0, "close": 10.5},
            {"day": d, "hour": 9, "minute": 25, "open_": 10.5, "close": 11.0},
            {"day": d, "hour": 9, "minute": 30, "open_": 99.0, "close": 99.0},
        ])
        point = select_preopen_sell(bars)
        assert point.price == 11.0


class TestTradingDaysWithSession:
    def test_excludes_premarket_only_days(self):
        d = date(2025, 1, 7)
        bars = bars_from_specs([
            {"day": d, "hour": 8, "minute": 0, "open_": 1.0, "close": 1.0},
        ])
        assert trading_days_with_session(bars) == []

    def test_includes_days_with_regular_session(self):
        d = date(2025, 1, 6)
        bars = bars_from_specs([
            {"day": d, "hour": 10, "minute": 0, "open_": 1.0, "close": 1.0},
        ])
        assert trading_days_with_session(bars) == [d]

    def test_premarket_only_day_not_a_buy_day(self):
        """Monday with only premarket is valid as sell day but not buy day."""
        fri = date(2025, 1, 10)
        mon = date(2025, 1, 13)
        bars = bars_from_specs([
            {"day": fri, "hour": 15, "minute": 55, "open_": 100.0, "close": 100.0},
            {"day": mon, "hour": 9, "minute": 25, "open_": 105.0, "close": 105.0},
        ])
        assert fri in trading_days_with_session(bars)
        assert mon not in trading_days_with_session(bars)
