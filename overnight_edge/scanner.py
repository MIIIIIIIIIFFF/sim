"""Scan orchestration across a stock universe."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from overnight_edge.compounding import annotate_equity
from overnight_edge.data import download_intraday_bars
from overnight_edge.models import ScanConfig, ScanResult
from overnight_edge.strategy import backtest_overnight


def _analyze_one(ticker: str, config: ScanConfig) -> Optional[dict]:
    try:
        bars = download_intraday_bars(
            ticker,
            config.lookback_days,
            max_retries=config.max_retries,
        )
        result = backtest_overnight(
            bars,
            config.hold_count,
            min_trades=config.min_trades_required,
            starting_capital=config.starting_capital,
        )
        if result is None:
            return None

        result.ticker = ticker
        row = result.to_ranking_row()
        row["_trade_log"] = annotate_equity(
            result.trade_log_dicts(),
            config.starting_capital,
        )
        return row

    except Exception as exc:  # noqa: BLE001
        return {"ticker": ticker, "_error": str(exc)}


def run_scan(
    tickers: list[str],
    config: ScanConfig,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> ScanResult:
    started = time.time()
    results: list[dict] = []
    skipped: list[str] = []
    total = len(tickers)

    with ThreadPoolExecutor(max_workers=config.max_workers) as pool:
        futures = {pool.submit(_analyze_one, t, config): t for t in tickers}
        done = 0
        for future in as_completed(futures):
            done += 1
            ticker = futures[future]
            row = future.result()

            if row is None:
                skipped.append(f"{ticker}: insufficient data (< {config.min_trades_required} trades)")
            elif "_error" in row:
                skipped.append(f"{ticker}: {row['_error']}")
            else:
                results.append(row)

            if on_progress:
                on_progress(done, total)

    if not results:
        raise RuntimeError(
            "No tickers produced valid results. Check network access and try again."
        )

    df = pd.DataFrame(results)
    df = df.sort_values("compounded_return_pct", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)

    return ScanResult(
        rankings=df,
        skipped=skipped,
        elapsed_seconds=time.time() - started,
        universe_size=total,
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
        lookback_calendar_days=config.lookback_days,
    )
