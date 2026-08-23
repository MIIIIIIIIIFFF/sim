"""Yahoo Finance intraday data access with retry logic."""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd
import yfinance as yf

from overnight_edge.constants import INTRADAY_INTERVAL

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)


def download_intraday_bars(
    ticker: str,
    lookback_days: int,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.5,
) -> pd.DataFrame:
    """
    Download 5-minute OHLC bars with extended (pre/post) hours.

    Retries transient Yahoo Finance failures with exponential backoff.
    """
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            df = yf.download(
                ticker,
                period=f"{lookback_days}d",
                interval=INTRADAY_INTERVAL,
                prepost=True,
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if df is not None and not df.empty:
                return df
            last_error = ValueError(f"{ticker}: empty response from Yahoo Finance")
        except Exception as exc:  # noqa: BLE001
            last_error = exc

        if attempt < max_retries - 1:
            time.sleep(retry_delay * (2**attempt))

    if last_error:
        raise last_error
    return pd.DataFrame()


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a timezone-aware DatetimeIndex (US/Eastern) and standard OHLC columns."""
    if df is None or df.empty:
        return pd.DataFrame()

    idx = pd.to_datetime(df.index)
    if idx.tz is None:
        # Yahoo 5-minute bars are timezone-aware in practice. Naive indexes
        # in tests and rare feeds are already US Eastern wall-clock times.
        idx = idx.tz_localize("America/New_York")
    else:
        idx = idx.tz_convert("America/New_York")

    out = _extract_ohlc(df).copy()
    out.index = idx
    return out.sort_index()


def _extract_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        level0 = df.columns.get_level_values(0)
        if "Close" in level0:
            close, open_ = df["Close"], df["Open"]
        else:
            close = df.xs("Close", axis=1, level=1)
            open_ = df.xs("Open", axis=1, level=1)
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        if isinstance(open_, pd.DataFrame):
            open_ = open_.iloc[:, 0]
        return pd.DataFrame({"Open": open_, "Close": close})

    return df[[c for c in ("Open", "Close") if c in df.columns]].copy()
