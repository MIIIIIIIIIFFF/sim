"""Calendar-day lookback calculations for intraday data windows."""

from __future__ import annotations

import math

from overnight_edge.constants import INTRADAY_MAX_CALENDAR_DAYS


def calendar_days_for_trading_days(trading_days: int) -> int:
    """
    Convert a requested number of **trading-day overnight holds** into the
    calendar-day lookback needed when downloading Yahoo 5-minute bars.

    N overnight holds require N+1 trading sessions (buy on day 1, sell on day N+1).

    Formula
    -------
    * sessions_needed = trading_days + 1
    * ~5 trading sessions per 7 calendar days
    * +15 calendar-day buffer for weekends and US market holidays
    * Capped at Yahoo's 60-day 5-minute data limit

    Examples
    --------
    30 overnight holds -> 31 sessions -> ceil(43.4) + 15 = 59 calendar days
    """
    if trading_days < 1:
        raise ValueError("trading_days must be >= 1")

    sessions_needed = trading_days + 1
    raw = math.ceil(sessions_needed * 7 / 5) + 15
    return min(raw, INTRADAY_MAX_CALENDAR_DAYS)


def max_trading_days_available() -> int:
    """Largest hold window that fits inside Yahoo's 60-day 5-minute limit."""
    # Reverse: sessions ≈ (60 - 15) * 5/7, then holds = sessions - 1
    sessions = math.floor((INTRADAY_MAX_CALENDAR_DAYS - 15) * 5 / 7)
    return max(1, sessions - 1)
