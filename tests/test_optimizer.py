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
    from overnight_edge.optimizer_panel import OptimizerPanel, MODE_BOTH

    bars = _bars()
    monkeypatch.setattr(data, "download_intraday_cached", lambda ticker, lookback: (bars, "5m_precise"))

    panel = OptimizerPanel.__new__(OptimizerPanel)  # avoid Tk construction; pure method
    pt, slots = panel._analyze_ticker("TEST", date(2025, 1, 1), date(2025, 1, 31),
                                       crossover=False, mode=MODE_BOTH)

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


def test_crossover_broadens_families():
    """Enabling crossover widens the candidate window set of both families."""
    std = dict(families_candidates(False))
    cross = dict(families_candidates(True))
    assert len(cross["day"]) > len(std["day"])
    assert len(cross["night"]) > len(std["night"])


def test_crossover_day_can_buy_preopen_and_sell_afterhours():
    """A crossover DAY slot may buy pre-open and sell after-hours the same day."""
    from overnight_edge.optimizer import evaluate_slot
    bars = _bars()
    r = evaluate_slot(bars, "day", 545, 960)  # 09:05 pre-open buy -> 16:00 after sell
    assert r is not None
    assert r.family == "day"
    assert all(t.sell_date == t.buy_date for t in r.trades)  # still intra-day


def test_crossover_night_can_buy_before_close_and_sell_after_open():
    """A crossover NIGHT slot may buy before the close and sell after the open."""
    from overnight_edge.optimizer import evaluate_slot
    bars = _bars()
    r = evaluate_slot(bars, "night", 955, 600)  # 15:55 buy -> next-day 10:00 sell
    assert r is not None
    assert r.family == "night"
    assert all(t.sell_date > t.buy_date for t in r.trades)  # still overnight


def test_cross_rings_renders_dots_and_tip():
    """The two per-ticker scatter circles render a dot per ticker for both families."""
    import tkinter as tk

    from overnight_edge.optimizer_panel import _CrossRings

    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001  (headless env)
        pytest.skip("Tkinter display not available")
    root.withdraw()
    try:
        rings = _CrossRings(root, "#2e86c1", "#8e44ad")
        rings.set_rings(
            day_points=[("NVDA", 1.2), ("AAPL", -0.8), ("JPM", 0.0)],
            night_points=[("MSFT", 0.6), ("GOOG", -1.1)],
            crossover=True,
        )
        root.update_idletasks()
        # Each scatter draws its outline + zero baseline + dots + center label.
        assert rings.canvas.find_all(), "day scatter empty"
        assert rings.night.canvas.find_all(), "night scatter empty"
        assert rings.day._points == [("NVDA", 1.2), ("AAPL", -0.8), ("JPM", 0.0)]
        assert len(rings.night._points) == 2
    finally:
        root.destroy()


def test_detail_sort_nan_always_sinks():
    """Failed tickers (—/NaN) stay at the bottom in both asc and desc sorts."""
    import tkinter as tk
    from tkinter import ttk

    from overnight_edge.optimizer_panel import OptimizerPanel

    try:
        root = tk.Tk()
    except Exception:  # noqa: BLE001
        pytest.skip("Tkinter display not available")
    root.withdraw()
    try:
        nb = ttk.Notebook(root)
        opt_page = ttk.Frame(nb)
        nb.add(opt_page)
        p = OptimizerPanel(parent=opt_page, root=root, universe_df=None, app=None)
        root.update_idletasks()

        det = p.detail_tree
        # Simulate 4 rows incl. one failed ticker (NaN -> "—").
        for ticker, comp in [("NVDA", "+12.50%"), ("AAPL", "-3.20%"),
                             ("JPM", "+0.00%"), ("FAIL", "—")]:
            det.insert("", "end", values=(ticker, "Jour", "—", comp, "—"))

        # Sort ascending by compounded: -3.20, 0.00, +12.50, then NaN at bottom.
        p._detail_sort = ("compounded", False)
        p._resort_detail()
        order = [det.set(i)["ticker"] for i in det.get_children()]
        assert order == ["AAPL", "JPM", "NVDA", "FAIL"], f"asc: {order}"

        # Sort descending: +12.50, 0.00, -3.20, then NaN STILL at bottom.
        p._detail_sort = ("compounded", True)
        p._resort_detail()
        order = [det.set(i)["ticker"] for i in det.get_children()]
        assert order == ["NVDA", "JPM", "AAPL", "FAIL"], f"desc: {order}"
    finally:
        root.destroy()