"""Tests for the session-window optimizer (day vs night slot evaluation)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest
import pytz

from overnight_edge.optimizer import (
    families_candidates,
    evaluate_slot,
    evaluate_all_slots,
    best_per_family,
    load_favorites,
    save_favorites,
)

ET = pytz.timezone("America/New_York")


def _bars() -> pd.DataFrame:
    """Synthetic 5-minute bars covering 4 days with session, pre/post market."""
    rows: list[dict] = []

    def bar(day: date, hour: int, minute: int, open_: float, close: float) -> None:
        ts = ET.localize(datetime(day.year, day.month, day.day, hour, minute))
        rows.append({"timestamp": ts, "Open": open_, "Close": close})

    d1 = date(2025, 1, 6)   # Mon
    d2 = date(2025, 1, 7)
    d3 = date(2025, 1, 8)
    d4 = date(2025, 1, 9)

    # Mon close 100 -> Tue pre-open 101 = +1% night
    bar(d1, 9, 30, 98, 99)
    bar(d1, 16, 0, 100, 100)
    # Tue pre-open sell candidates
    bar(d2, 9, 5, 104, 104)
    bar(d2, 9, 10, 104, 104)
    # Tue session: morning buy window (10:00) and afternoon sell (15:00)
    bar(d2, 9, 30, 104, 104.5)
    bar(d2, 9, 40, 104.6, 104.7)
    bar(d2, 10, 0, 104.8, 104.9)
    bar(d2, 15, 0, 105, 105.1)
    bar(d2, 15, 30, 105.5, 105.6)
    bar(d2, 15, 55, 106, 106.5)
    bar(d2, 16, 0, 106.5, 106.5)  # close for Wed night
    # Wed session
    bar(d3, 9, 30, 107, 108)
    bar(d3, 9, 40, 108, 108.2)
    bar(d3, 10, 0, 108.3, 108.4)
    bar(d3, 15, 0, 108.5, 109)
    bar(d3, 15, 30, 109, 109.3)
    bar(d3, 16, 0, 109.5, 109.5)
    # Thu pre-open + session (for a night close Wed->Thu)
    bar(d4, 9, 10, 110, 110)
    bar(d4, 9, 30, 110, 110)
    bar(d4, 15, 0, 111, 111)
    bar(d4, 15, 30, 111, 111)

    df = pd.DataFrame(rows).set_index("timestamp")
    return df[["Open", "Close"]]


def test_candidate_counts():
    fam = dict(families_candidates())
    assert 25 == len(fam["day"])   # 5 morning x 5 afternoon
    assert 30 == len(fam["night"])  # 5 close buys x 6 pre-open sells


def test_day_slot_builds_trades():
    df = _bars()
    res = evaluate_slot(df, "day", 600, 900)  # 10:00 buy -> 15:00 sell
    assert res is not None
    assert res.family == "day"
    assert res.day_count >= 1
    assert all(t.family == "day" for t in res.trades)
    assert all(t.sell_date == t.buy_date for t in res.trades)


def test_night_slot_builds_trades():
    df = _bars()
    res = evaluate_slot(df, "night", 960, 545)  # 16:00 close buy -> 09:05 pre-open sell
    assert res is not None
    assert res.family == "night"
    assert res.day_count >= 1
    assert all(t.sell_date > t.buy_date for t in res.trades)


def test_night_trade_holds_overnight():
    df = _bars()
    res = evaluate_slot(df, "night", 960, 540)  # 16:00 -> 09:00
    assert res is not None
    trade = res.trades[0]
    assert trade.sell_date == date(2025, 1, 7)
    assert trade.buy_date == date(2025, 1, 6)
    assert trade.return_pct > 0  # 100 -> 104


def test_day_trade_same_day():
    df = _bars()
    res = evaluate_slot(df, "day", 600, 900)  # 10:00 buy -> 15:00 sell
    assert res is not None
    assert all(t.sell_date == t.buy_date for t in res.trades)


def test_evaluate_all_slots_sorted():
    df = _bars()
    results = evaluate_all_slots(df)
    assert len(results) > 0
    rets = [r.compounded_return_pct for r in results]
    assert rets == sorted(rets, reverse=True)


def test_best_per_family():
    df = _bars()
    best = best_per_family(df)
    assert best["day"] is not None
    assert best["night"] is not None


def test_favorites_roundtrip(tmp_path, monkeypatch):
    import overnight_edge.optimizer as opt
    monkeypatch.setattr(opt, "user_data_dir", lambda: tmp_path)
    save_favorites({"Portefeuille 5 titres": ["NVDA", "AAPL", "msft"]})
    loaded = load_favorites()
    assert loaded["Portefeuille 5 titres"] == ["NVDA", "AAPL", "MSFT"]


def test_favorites_load_missing(tmp_path, monkeypatch):
    import overnight_edge.optimizer as opt
    monkeypatch.setattr(opt, "user_data_dir", lambda: tmp_path)
    assert load_favorites() == {}


def test_analyze_ticker_picks_best(monkeypatch, capsys):
    """_analyze_ticker returns the best slot for a single ticker (network patched)."""
    from datetime import timedelta
    import overnight_edge.data as data
    from overnight_edge.optimizer_panel import OptimizerPanel

    bars = _bars()
    monkeypatch.setattr(data, "download_intraday_cached", lambda ticker, lookback: (bars, "5m_precise"))

    panel = OptimizerPanel.__new__(OptimizerPanel)  # avoid Tk construction; pure method
    pt, slots = panel._analyze_ticker("TEST", date(2025, 1, 1), date(2025, 1, 31))

    assert pt["ticker"] == "TEST"
    assert pt["family"] in ("day", "night")
    assert pt["compounded"] == pt["compounded"]  # not NaN => a best slot existed
    assert len(slots) > 0
    assert all(pt["slot"] for pt in [pt])


def test_aggregate_rows_averages_across_tickers():
    """Multi-ticker aggregation averages the compounded return per slot."""
    from overnight_edge.optimizer import evaluate_slot
    from overnight_edge.optimizer_panel import OptimizerPanel

    bars = _bars()
    panel = OptimizerPanel.__new__(OptimizerPanel)

    # Two distinct tickers sharing the same night slot (16:00 buy -> 09:05 sell).
    slot = evaluate_slot(bars, "night", 960, 545)
    assert slot is not None
    key = (slot.family, slot.buy_minute, slot.sell_minute)
    panel._agg = {key: {"n": 0, "compounded": 0.0, "simple": 0.0, "win": 0.0,
                        "avg": 0.0, "dd": 0.0, "days": set(), "trades": []}}
    b = panel._agg[key]
    b["n"] = 2
    b["compounded"] = slot.compounded_return_pct * 2
    b["simple"] = slot.simple_return_pct * 2
    b["win"] = slot.win_rate_pct * 2
    b["avg"] = slot.avg_return_pct * 2
    b["dd"] = slot.max_drawdown_pct * 2
    b["days"].update(t.buy_date for t in slot.trades)

    rows = panel._aggregate_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["family"] == "Nuit"
    assert row["compounded"] == pytest.approx(slot.compounded_return_pct)
    assert row["days"] == min(t.buy_date for t in slot.trades)