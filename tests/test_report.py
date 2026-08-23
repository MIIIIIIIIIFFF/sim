"""Tests for report helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from overnight_edge import __version__
from overnight_edge.report import build_manifest, generate_html_report, save_manifest


def test_build_manifest_structure():
    df = pd.DataFrame(
        {
            "ticker": ["AAA", "BBB"],
            "compounded_return_pct": [10.0, -5.0],
            "company": ["Alpha", "Beta"],
        }
    )
    manifest = build_manifest(
        df,
        hold_count=30,
        lookback_calendar_days=59,
        universe_label="Test",
        elapsed_seconds=1.5,
        skipped=["XXX: error"],
        scan_timestamp="2025-01-01T00:00:00+00:00",
        min_trades_required=30,
        starting_capital=10_000.0,
    )
    assert manifest["parameters"]["stocks_analyzed"] == 2
    assert manifest["summary"]["top_performer"]["ticker"] == "AAA"
    assert "strategy" in manifest
    assert manifest["version"] == __version__


def test_html_report_escapes_company_names(tmp_path: Path):
    df = pd.DataFrame(
        {
            "rank": [1],
            "ticker": ["TEST"],
            "company": ['Acme <script>alert("x")</script>'],
            "sector": ["Tech & Co"],
            "compounded_return_pct": [12.5],
            "avg_overnight_return_pct": [0.5],
            "win_rate_pct": [60.0],
            "max_drawdown_pct": [-2.0],
            "profit_factor": [1.5],
            "trades": [30],
            "ending_capital": [11250.0],
            "profit_usd": [1250.0],
            "first_trade_date": ["2025-01-01"],
            "last_trade_date": ["2025-01-30"],
        }
    )
    out = tmp_path / "report.html"
    generate_html_report(
        df, out, hold_count=30, lookback_calendar_days=59, universe_label="Test",
        elapsed_seconds=1.0, skipped_count=0, starting_capital=10_000.0,
    )
    content = out.read_text(encoding="utf-8")
    assert 'Acme <script>' not in content
    assert "&lt;script&gt;" in content
    assert "&amp;" in content


def test_save_manifest_roundtrip(tmp_path: Path):
    path = tmp_path / "scan.json"
    payload = {"tool": "test", "value": 42}
    save_manifest(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["value"] == 42
