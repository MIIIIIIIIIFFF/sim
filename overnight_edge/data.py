"""Yahoo Finance data access with retry logic, local 5-min cache, and daily fallback.

Two data layers:
- ``download_intraday_bars``: Yahoo 5-minute bars with extended hours (precise,
  but limited to ~60 calendar days by Yahoo).
- ``download_daily_bars``: Yahoo daily bars (Open/Close only, ~10+ years).

``download_intraday_cached`` is the high-level entry: it fetches fresh 5-minute
bars, merges them into the per-ticker local cache (so the window grows over
time), and returns the union. When the requested lookback exceeds what 5-minute
data can cover (cache + Yahoo's ~60 days), it falls back to daily bars and flags
the result as ``daily_fallback`` so the UI can mark it "Approximatif".
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pandas as pd
import yfinance as yf

from overnight_edge.constants import INTRADAY_INTERVAL
from overnight_edge.paths import bars_cache_dir

logging.getLogger("yfinance").setLevel(logging.CRITICAL)
logger = logging.getLogger(__name__)

# Yahoo caps 5-minute history at roughly this many calendar days.
FIVE_MIN_MAX_CALENDAR_DAYS = 60


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


def download_daily_bars(
    ticker: str,
    *,
    period: str = "max",
    max_retries: int = 3,
    retry_delay: float = 1.5,
) -> pd.DataFrame:
    """Download daily OHLC bars (Open/Close). Up to ~10+ years of history.

    Used as a fallback when 5-minute data cannot cover the requested window.
    Buy = day T close, sell = day T+1 open (proxy for 09:29 pre-open).
    """
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            df = yf.download(
                ticker,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True,
                threads=False,
            )
            if df is not None and not df.empty:
                return df
            last_error = ValueError(f"{ticker}: empty daily response from Yahoo Finance")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        if attempt < max_retries - 1:
            time.sleep(retry_delay * (2**attempt))
    if last_error:
        raise last_error
    return pd.DataFrame()


# ---------------------------------------------------------------------------
# Local 5-minute cache (accumulates over time)
# ---------------------------------------------------------------------------

def _cache_path(ticker: str):
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in (".", "-", "_"))
    return bars_cache_dir() / f"{safe}.parquet"


def load_cached_bars(ticker: str) -> pd.DataFrame:
    """Load all locally-accumulated 5-minute bars for ``ticker`` (empty if none)."""
    path = _cache_path(ticker)
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        if df is not None and not df.empty:
            return df
    except Exception:  # noqa: BLE001
        logger.debug("cache read failed for %s", ticker, exc_info=True)
    return pd.DataFrame()


def save_cached_bars(ticker: str, bars: pd.DataFrame) -> None:
    """Persist the union of cached + new bars (dedup by timestamp, keep last)."""
    if bars is None or bars.empty:
        return
    path = _cache_path(ticker)
    try:
        bars.to_parquet(path)
    except Exception:  # noqa: BLE001
        logger.debug("cache write failed for %s", ticker, exc_info=True)


def _merge_bars(cached: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """Union two 5-minute frames, dedup by index, keep the freshest row."""
    if fresh is None or fresh.empty:
        return cached
    if cached is None or cached.empty:
        return fresh
    out = pd.concat([cached, fresh])
    out = out[~out.index.duplicated(keep="last")]
    return out.sort_index()


def download_intraday_cached(
    ticker: str,
    lookback_days: int,
    *,
    max_retries: int = 3,
    retry_delay: float = 1.5,
) -> tuple[pd.DataFrame, str]:
    """
    High-level data fetch with local accumulation and daily fallback.

    Returns ``(bars, source)`` where ``source`` is one of:
    - ``"5m_precise"``: 5-minute bars (from cache + fresh Yahoo), precise to the bar.
    - ``"daily_fallback"``: daily bars used because the 5-minute window cannot
      cover ``lookback_days``. Buy=day T close, sell=day T+1 open (approximation).

    The 5-minute cache is written through on every successful fetch so the
    window grows over time; a user who scans daily accumulates a multi-year
    precise dataset after enough time.
    """
    cached = load_cached_bars(ticker)
    five_min_lookback = min(lookback_days, FIVE_MIN_MAX_CALENDAR_DAYS)

    try:
        fresh = download_intraday_bars(
            ticker,
            five_min_lookback,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
    except Exception:  # noqa: BLE001
        fresh = pd.DataFrame()

    if not fresh.empty:
        merged = _merge_bars(cached, normalize_bars(fresh))
        save_cached_bars(ticker, merged)
        return merged, "5m_precise"

    # Fresh fetch failed — use cache alone if it covers the window.
    if not cached.empty:
        return cached, "5m_precise"

    # No 5-minute data at all: fall back to daily bars.
    daily = download_daily_bars(ticker, max_retries=max_retries, retry_delay=retry_delay)
    return normalize_bars(daily), "daily_fallback"


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
