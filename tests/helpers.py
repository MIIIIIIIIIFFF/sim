"""Synthetic bar data builders for tests."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytz

ET = pytz.timezone("America/New_York")


def make_bar(day: date, hour: int, minute: int, open_: float, close: float) -> dict:
    ts = ET.localize(datetime(day.year, day.month, day.day, hour, minute))
    return {"timestamp": ts, "Open": open_, "Close": close}


def bars_from_specs(specs: list[dict]) -> pd.DataFrame:
    rows = [make_bar(**s) for s in specs]
    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


def two_day_scenario() -> pd.DataFrame:
    """Monday close $100 -> Tuesday premarket $105 = +5%."""
    d1 = date(2025, 1, 6)
    d2 = date(2025, 1, 7)
    return bars_from_specs([
        {"day": d1, "hour": 9, "minute": 30, "open_": 98.0, "close": 98.5},
        {"day": d1, "hour": 15, "minute": 55, "open_": 99.5, "close": 100.0},
        {"day": d2, "hour": 9, "minute": 25, "open_": 104.0, "close": 105.0},
        {"day": d2, "hour": 9, "minute": 30, "open_": 105.5, "close": 106.0},
    ])
