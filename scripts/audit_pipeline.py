"""Pipeline smoke test: run_and_export + report generation with a stubbed scan."""
from __future__ import annotations

import pathlib
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import overnight_edge.pipeline as P
from overnight_edge.models import ScanResult


def fake_scan(tickers, config, on_progress=None):
    for i, t in enumerate(tickers):
        if on_progress:
            on_progress(i + 1, len(tickers))
    rows = []
    for i, t in enumerate(tickers):
        rows.append({
            "ticker": t, "company": f"Co {t}", "sector": "Tech",
            "compounded_return_pct": 10.0 - i, "ending_capital": 11000 - i,
            "profit_usd": 1000 - i, "avg_overnight_return_pct": 0.3,
            "win_rate_pct": 60.0, "max_drawdown_pct": -2.0, "trades": 30,
            "profit_factor": 2.5, "first_trade_date": "2026-06-01",
            "last_trade_date": "2026-07-01",
            "_trade_log": [{
                "buy_date": "2026-06-01", "sell_date": "2026-06-02",
                "buy_price": 100.0, "sell_price": 101.0, "return_pct": 1.0,
                "buy_price_source": "regular_close_1600",
                "sell_price_source": "premarket_0925",
            }],
        })
    df = pd.DataFrame(rows).sort_values("compounded_return_pct", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    return ScanResult(
        rankings=df, skipped=[], elapsed_seconds=0.5,
        universe_size=len(tickers),
        scan_timestamp=datetime.now(timezone.utc).isoformat(),
        lookback_calendar_days=60,
    )


original_scan = P.run_scan
P.run_scan = fake_scan
try:
    with tempfile.TemporaryDirectory() as td:
        res, df, paths = P.run_and_export(
            hold_count=30, starting_capital=10000, workers=4, top_n=25,
            min_trades=30, tickers_csv="AAPL,MSFT,NVDA",
            output_dir=pathlib.Path(td), write_html=True,
        )
        assert df.shape[0] == 3, df.shape
        assert paths["csv"].exists() and paths["html"].exists()
        assert paths["html"].stat().st_size > 5000
        # CSV should not contain _trade_log
        text = paths["csv"].read_text(encoding="utf-8-sig")
        assert "_trade_log" not in text
        print("OK PIPELINE: csv", paths["csv"].stat().st_size, "html", paths["html"].stat().st_size)
finally:
    P.run_scan = original_scan