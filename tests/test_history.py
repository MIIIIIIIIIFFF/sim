"""Daily snapshot and variance tests."""

from __future__ import annotations

import pandas as pd

from overnight_edge.history import (
    attach_variance,
    load_previous_snapshot,
    movers_summary,
    save_daily_snapshot,
)


def test_rank_up_is_positive(tmp_path, monkeypatch):
    monkeypatch.setattr("overnight_edge.history.history_dir", lambda: tmp_path)
    prev = pd.DataFrame(
        {
            "rank": [5, 1],
            "ticker": ["AAA", "BBB"],
            "company": ["A", "B"],
            "compounded_return_pct": [3.0, 10.0],
        }
    )
    cur = pd.DataFrame(
        {
            "rank": [1, 2],
            "ticker": ["AAA", "BBB"],
            "company": ["A", "B"],
            "compounded_return_pct": [8.0, 9.0],
        }
    )
    out = attach_variance(cur, prev)
    aaa = out[out["ticker"] == "AAA"].iloc[0]
    assert int(aaa["rank_change"]) == 4  # 5 -> 1
    assert float(aaa["compounded_delta_pct"]) == 5.0
    bbb = out[out["ticker"] == "BBB"].iloc[0]
    assert int(bbb["rank_change"]) == -1  # 1 -> 2


def test_new_name_flagged():
    prev = pd.DataFrame({"rank": [1], "ticker": ["OLD"], "compounded_return_pct": [1.0]})
    cur = pd.DataFrame({"rank": [1], "ticker": ["NEW"], "compounded_return_pct": [2.0]})
    out = attach_variance(cur, prev)
    assert bool(out.iloc[0]["is_new"]) is True


def test_snapshot_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("overnight_edge.history.history_dir", lambda: tmp_path)
    df = pd.DataFrame(
        {
            "rank": [1],
            "ticker": ["AAA"],
            "company": ["Alpha"],
            "sector": ["Tech"],
            "compounded_return_pct": [4.2],
            "ending_capital": [10420.0],
            "profit_usd": [420.0],
            "avg_overnight_return_pct": [0.1],
            "win_rate_pct": [50.0],
            "max_drawdown_pct": [-1.0],
            "trades": [30],
        }
    )
    save_daily_snapshot(df, "2026-08-20T12:00:00+00:00")
    prev, day = load_previous_snapshot("2026-08-21")
    assert day == "2026-08-20"
    assert prev is not None
    assert prev.iloc[0]["ticker"] == "AAA"


def test_utc_evening_snapshot_uses_eastern_date(tmp_path, monkeypatch):
    """After 20:00 ET, UTC is already the next calendar day — keep the market date."""
    monkeypatch.setattr("overnight_edge.history.history_dir", lambda: tmp_path)
    df = pd.DataFrame(
        {
            "rank": [1],
            "ticker": ["AAA"],
            "compounded_return_pct": [1.0],
            "ending_capital": [10100.0],
            "profit_usd": [100.0],
            "avg_overnight_return_pct": [0.1],
            "win_rate_pct": [50.0],
            "max_drawdown_pct": [-1.0],
            "trades": [30],
        }
    )
    # 02:00 UTC on Aug 24 is still Aug 23 evening in US Eastern (EDT).
    day = save_daily_snapshot(df, "2026-08-24T02:00:00+00:00")
    assert day == "2026-08-23"


def test_movers_empty_when_ranks_unchanged():
    df = pd.DataFrame(
        {
            "rank": [1, 2],
            "ticker": ["AAA", "BBB"],
            "rank_change": [0, 0],
            "compounded_return_pct": [8.0, 7.0],
            "is_new": [False, False],
        }
    )
    movers = movers_summary(df, top_n=15)
    assert movers["climbers"].empty
    assert movers["fallers"].empty


def test_movers_only_actual_rank_changes():
    df = pd.DataFrame(
        {
            "rank": [1, 2, 3],
            "ticker": ["AAA", "BBB", "CCC"],
            "rank_change": [4, 0, -2],
            "compounded_return_pct": [8.0, 7.0, 1.0],
            "is_new": [False, False, False],
        }
    )
    movers = movers_summary(df, top_n=15)
    assert list(movers["climbers"]["ticker"]) == ["AAA"]
    assert list(movers["fallers"]["ticker"]) == ["CCC"]
