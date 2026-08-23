"""Tests for calendar lookback calculations."""

from __future__ import annotations

import pytest

from overnight_edge.calendar import calendar_days_for_trading_days, max_trading_days_available


def test_30_trading_days_lookback():
    assert calendar_days_for_trading_days(30) == 59  # 31 sessions -> ceil(43.4)+15


def test_5_trading_days_lookback():
    assert calendar_days_for_trading_days(5) == 24  # 6 sessions -> ceil(8.4)+15


def test_capped_at_60_days():
    assert calendar_days_for_trading_days(100) == 60


def test_invalid_trading_days():
    with pytest.raises(ValueError):
        calendar_days_for_trading_days(0)


def test_max_trading_days_available():
    assert max_trading_days_available() >= 30
