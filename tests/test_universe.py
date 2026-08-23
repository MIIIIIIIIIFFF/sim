"""Tests for ticker universe parsing."""

from __future__ import annotations

import pandas as pd
import pytest

from overnight_edge.universe import _constituents_from_table, _normalize_symbol, parse_ticker_list


def test_normalize_brk_symbol():
    assert _normalize_symbol("BRK.B") == "BRK-B"


def test_parse_ticker_list():
    assert parse_ticker_list("aapl, MSFT , nvda") == ["AAPL", "MSFT", "NVDA"]


def test_parse_empty_items_skipped():
    assert parse_ticker_list("AAPL,,MSFT") == ["AAPL", "MSFT"]


def test_constituents_rejects_short_list():
    raw = pd.DataFrame({"Symbol": ["AAPL"], "Security": ["Apple"]})
    with pytest.raises(ValueError, match="too short"):
        _constituents_from_table(raw)


def test_constituents_rejects_missing_symbol():
    raw = pd.DataFrame({"Name": ["Apple"]})
    with pytest.raises(ValueError, match="Symbol"):
        _constituents_from_table(raw)
