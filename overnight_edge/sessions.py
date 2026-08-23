"""US equity session timing and 5-minute bar selection rules.

Yahoo Finance 5-minute bar convention (verified against live data)
-----------------------------------------------------------------
* Bar timestamps mark the **start** of each 5-minute bucket.
* The 15:55 bar covers 15:55:00 - 15:59:59 ET; its Close is the official
  session close when no 16:00 bar is present.
* Yahoo also emits a 16:00 bar for many symbols; when present it is the
  last regular-session bar and its Close matches the daily closing price.
* The 09:25 bar covers 09:25:00 - 09:29:59 ET; its Close is our best
  proxy for a 09:29 ET exit (last trade before the 09:30 opening bell).
* Pre-market begins at 04:00 ET; post-market begins after 16:00 ET.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from typing import Optional

import numpy as np
import pandas as pd

from overnight_edge.constants import (
    PREMARKET_START,
    PREOPEN_EXIT,
    SESSION_CLOSE,
    SESSION_OPEN,
)


@dataclass(frozen=True)
class PricePoint:
    price: float
    bar_time: pd.Timestamp  # timezone-aware, US/Eastern
    source: str  # audit label, e.g. "regular_close" or "premarket_0925"


def _valid(price: float) -> bool:
    return bool(price > 0 and np.isfinite(price))


def select_close_buy(day_bars: pd.DataFrame) -> Optional[PricePoint]:
    """
    Select the regular-session closing price (target: 16:00 ET).

    Uses the Close of the last 5-minute bar between 09:30 and 16:00 inclusive.
    Post-market bars (after 16:00) are never considered.
    """
    regular = day_bars.between_time(SESSION_OPEN, SESSION_CLOSE)
    if regular.empty:
        return None

    bar_time = regular.index[-1]
    price = float(regular["Close"].iloc[-1])
    if not _valid(price):
        return None

    clock = bar_time.time()
    if clock == SESSION_CLOSE:
        label = "regular_close_1600"
    elif clock == time(15, 55):
        label = "regular_close_1555"
    else:
        label = f"regular_close_{bar_time.strftime('%H%M')}"
    return PricePoint(price=price, bar_time=bar_time, source=label)


def select_preopen_sell(day_bars: pd.DataFrame) -> Optional[PricePoint]:
    """
    Select the pre-market exit price (target: 09:29 ET).

    Uses the Close of the last 5-minute bar between 04:00 and 09:29 inclusive.
    This is typically the 09:25 bar (covering 09:25 - 09:29:59).

    Falls back to the 09:30 opening print only when no pre-market data exists.
    """
    premarket = day_bars.between_time(PREMARKET_START, PREOPEN_EXIT)
    if not premarket.empty:
        bar_time = premarket.index[-1]
        price = float(premarket["Close"].iloc[-1])
        if _valid(price):
            return PricePoint(
                price=price,
                bar_time=bar_time,
                source=f"premarket_{bar_time.strftime('%H%M')}",
            )

    opening = day_bars.between_time(SESSION_OPEN, SESSION_OPEN)
    if not opening.empty:
        bar_time = opening.index[0]
        price = float(opening["Open"].iloc[0])
        if _valid(price):
            return PricePoint(price=price, bar_time=bar_time, source="fallback_open_0930")

    return None


def select_open(day_bars: pd.DataFrame) -> Optional[PricePoint]:
    """Opening print at 09:30 ET (first regular-session bar's Open)."""
    opening = day_bars.between_time(SESSION_OPEN, SESSION_OPEN)
    if opening.empty:
        return None
    bar_time = opening.index[0]
    price = float(opening["Open"].iloc[0])
    if not _valid(price):
        return None
    return PricePoint(price=price, bar_time=bar_time, source="open_0930")


def select_session_open_buy(day_bars: pd.DataFrame) -> Optional[PricePoint]:
    """Buy at the 09:30 ET opening bell (first regular-session bar)."""
    return select_open(day_bars)


def select_session_close_sell(day_bars: pd.DataFrame) -> Optional[PricePoint]:
    """Sell at the 16:00 ET session close (last regular-session bar).

    Mirrors select_close_buy: the Close of the last 5m bar up to 16:00,
    falling back to the 15:55 bar when no 16:00 bar exists.
    """
    return select_close_buy(day_bars)


def all_days_in_data(bars: pd.DataFrame) -> list[date]:
    """Sorted unique dates present in the bar data (any session)."""
    return sorted({ts.date() for ts in bars.index})


def has_regular_session(day_bars: pd.DataFrame) -> bool:
    """True when the day has at least one regular-session bar (09:30-16:00)."""
    return not day_bars.between_time(SESSION_OPEN, SESSION_CLOSE).empty


def trading_days_with_session(bars: pd.DataFrame) -> list[date]:
    """
    Return sorted dates that contain at least one regular-session bar.

    Used for data-quality checks; sell days may only have pre-market bars.
    """
    return [d for d in all_days_in_data(bars) if has_regular_session(_day_slice(bars, d))]


def _day_slice(bars: pd.DataFrame, day: date) -> pd.DataFrame:
    slice_ = bars.loc[str(day)]
    if isinstance(slice_, pd.Series):
        return slice_.to_frame().T
    return slice_


def is_next_trading_day(earlier: date, later: date, all_days: list[date]) -> bool:
    """True when `later` is the immediate successor of `earlier` in `all_days`."""
    try:
        idx = all_days.index(earlier)
    except ValueError:
        return False
    return idx + 1 < len(all_days) and all_days[idx + 1] == later
