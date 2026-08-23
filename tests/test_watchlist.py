"""Tests for the TradingView watchlist export helper."""

from __future__ import annotations

import pandas as pd

from app import _watchlist_tickers


def _df():
    return pd.DataFrame(
        [
            {"rank": 1, "ticker": "NVDA", "company": "Nvidia", "sector": "Tech", "compounded_return_pct": 12.5},
            {"rank": 2, "ticker": "AAPL", "company": "Apple", "sector": "Tech", "compounded_return_pct": -1.2},
            {"rank": 3, "ticker": "JPM", "company": "JPMorgan", "sector": "Banking", "compounded_return_pct": 3.1},
        ]
    )


def test_returns_uppercase_in_rank_order():
    assert _watchlist_tickers(_df()) == ["NVDA", "AAPL", "JPM"]


def test_sorts_by_compounded_descending():
    out = _watchlist_tickers(_df(), sort_col="compounded", sort_desc=True)
    assert out == ["NVDA", "JPM", "AAPL"]


def test_sorts_by_compounded_ascending():
    out = _watchlist_tickers(_df(), sort_col="compounded", sort_desc=False)
    assert out == ["AAPL", "JPM", "NVDA"]


def test_filters_by_search():
    out = _watchlist_tickers(_df(), search="tech")
    assert out == ["NVDA", "AAPL"]


def test_empty_df_returns_empty():
    assert _watchlist_tickers(pd.DataFrame()) == []
    assert _watchlist_tickers(None) == []