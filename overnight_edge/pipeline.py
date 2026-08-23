"""Shared scan + export pipeline used by CLI, interactive mode, and the GUI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from overnight_edge.calendar import calendar_days_for_trading_days
from overnight_edge.history import (
    attach_variance,
    current_scan_date,
    load_previous_snapshot,
    save_daily_snapshot,
)
from overnight_edge.models import ScanConfig, ScanResult
from overnight_edge.paths import default_output_dir
from overnight_edge.report import (
    build_manifest,
    enrich_with_metadata,
    generate_html_report,
    save_csv,
    save_manifest,
    save_trade_logs,
)
from overnight_edge.scanner import run_scan
from overnight_edge.universe import fetch_sp500_universe, parse_ticker_list


def resolve_universe(tickers_csv: str) -> tuple[list[str], Optional[pd.DataFrame], str]:
    if tickers_csv.strip():
        tickers = parse_ticker_list(tickers_csv)
        return tickers, None, f"Custom list ({len(tickers)} tickers)"
    universe = fetch_sp500_universe()
    return universe["ticker"].tolist(), universe, "S&P 500 (top ~500 US large caps)"


def run_and_export(
    *,
    hold_count: int,
    starting_capital: float,
    workers: int,
    top_n: int,
    min_trades: int,
    tickers_csv: str,
    output_dir: Optional[Path] = None,
    write_html: bool = True,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> tuple[ScanResult, pd.DataFrame, dict[str, Path]]:
    lookback = calendar_days_for_trading_days(hold_count)
    config = ScanConfig(
        hold_count=hold_count,
        lookback_days=lookback,
        max_workers=workers,
        top_n=top_n,
        min_trades_required=min_trades,
        starting_capital=starting_capital,
    )

    tickers, universe, universe_label = resolve_universe(tickers_csv)
    result = run_scan(tickers, config, on_progress=on_progress)

    df = result.rankings
    if universe is not None:
        df = enrich_with_metadata(df, universe)
    else:
        df["company"] = "N/A"
        df["sector"] = "N/A"

    today = current_scan_date(result.scan_timestamp)
    previous_df, previous_date = load_previous_snapshot(today)
    df = attach_variance(df, previous_df)
    save_daily_snapshot(df, result.scan_timestamp)

    output_dir = Path(output_dir) if output_dir else default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    paths = {
        "csv": output_dir / f"rankings_{stamp}.csv",
        "csv_latest": output_dir / "rankings_latest.csv",
        "trades": output_dir / f"top_trades_{stamp}.csv",
        "manifest": output_dir / f"scan_{stamp}.json",
        "manifest_latest": output_dir / "scan_latest.json",
        "html": output_dir / f"report_{stamp}.html",
        "html_latest": output_dir / "report_latest.html",
        "output_dir": output_dir,
    }

    save_csv(df, paths["csv"])
    save_csv(df, paths["csv_latest"])
    save_trade_logs(df, paths["trades"], top_n=min(10, top_n))

    manifest = build_manifest(
        df,
        hold_count=hold_count,
        lookback_calendar_days=lookback,
        universe_label=universe_label,
        elapsed_seconds=result.elapsed_seconds,
        skipped=result.skipped,
        scan_timestamp=result.scan_timestamp,
        min_trades_required=min_trades,
        starting_capital=starting_capital,
    )
    save_manifest(paths["manifest"], manifest)
    save_manifest(paths["manifest_latest"], manifest)

    if write_html:
        for key in ("html", "html_latest"):
            generate_html_report(
                df,
                paths[key],
                hold_count=hold_count,
                lookback_calendar_days=lookback,
                universe_label=universe_label,
                elapsed_seconds=result.elapsed_seconds,
                skipped_count=len(result.skipped),
                starting_capital=starting_capital,
                previous_scan_date=previous_date,
            )

    result.rankings = df
    return result, df, paths
