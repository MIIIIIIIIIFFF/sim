"""Tests for bar normalization."""

from __future__ import annotations

import pandas as pd
import pytz

from overnight_edge.data import normalize_bars

ET = pytz.timezone("America/New_York")


def test_normalize_adds_eastern_timezone():
    idx = pd.date_range("2025-01-06 09:30", periods=3, freq="5min")
    df = pd.DataFrame({"Open": [1, 2, 3], "Close": [1.1, 2.1, 3.1]}, index=idx)
    out = normalize_bars(df)
    assert str(out.index.tz) == "America/New_York"


def test_normalize_empty_frame():
    out = normalize_bars(pd.DataFrame())
    assert out.empty


def test_normalize_multiindex_columns():
    idx = pd.date_range("2025-01-06 09:30", periods=2, freq="5min", tz=ET)
    df = pd.DataFrame(
        {
            ("Open", "AAPL"): [100.0, 101.0],
            ("Close", "AAPL"): [100.5, 101.5],
        },
        index=idx,
    )
    out = normalize_bars(df)
    assert list(out.columns) == ["Open", "Close"]
    assert len(out) == 2
