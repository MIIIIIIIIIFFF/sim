"""GUI smoke test: construct OvernightEdgeApp headlessly and drive rendering."""
from __future__ import annotations

import pathlib
import sys
import tempfile
from datetime import datetime

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import tkinter as tk
import app as appmod
from overnight_edge.history import save_daily_snapshot


def _rankings():
    return pd.DataFrame([
        {
            "rank": 1, "ticker": "NVDA", "company": "Nvidia", "sector": "Tech",
            "compounded_return_pct": 12.5, "ending_capital": 11250.0,
            "profit_usd": 1250.0, "avg_overnight_return_pct": 0.4,
            "win_rate_pct": 70.0, "max_drawdown_pct": -1.5, "trades": 30,
            "profit_factor": 3.2, "rank_change": 2, "compounded_delta_pct": 1.2,
            "is_new": False, "first_trade_date": "2026-06-01",
            "last_trade_date": "2026-07-01",
        },
        {
            "rank": 2, "ticker": "AAPL", "company": "Apple", "sector": "Tech",
            "compounded_return_pct": -1.2, "ending_capital": 9880.0,
            "profit_usd": -120.0, "avg_overnight_return_pct": -0.04,
            "win_rate_pct": 45.0, "max_drawdown_pct": -4.0, "trades": 30,
            "profit_factor": 0.5, "rank_change": -1, "compounded_delta_pct": -2.0,
            "is_first": False, "first_trade_date": "2026-06-01",
            "last_trade_date": "2026-07-01",
        },
        {
            "rank": 3, "ticker": "JPM", "company": "JPMorgan", "sector": "Banking",
            "compounded_return_pct": 3.1, "ending_capital": 10310.0,
            "profit_usd": 310.0, "avg_overnight_return_pct": 0.1,
            "win_rate_pct": 55.0, "max_drawdown_pct": -2.0, "trades": 30,
            "profit_factor": 1.5, "rank_change": 0, "compounded_delta_pct": 0.0,
            "is_first": False, "first_trade_date": "2026-06-01",
            "last_trade_date": "2026-07-01",
        },
    ])


def main() -> int:
    import overnight_edge.history as H

    root = tk.Tk()
    root.withdraw()
    root.update()

    old_history_dir = H.history_dir
    try:
        with tempfile.TemporaryDirectory() as td:
            H.history_dir = lambda: pathlib.Path(td)
            # Seed one snapshot so _load_saved_scan picks it up.
            save_daily_snapshot(_rankings(), "2026-08-20T12:00:00+00:00")
            app = appmod.OvernightEdgeApp(root)
            app._df = _rankings()
            app._refresh_table()
            assert app.tree.get_children(), "tree not populated"
            assert app.movers_up.get_children(), "movers not populated"
            wl = appmod._watchlist_tickers(app._df)
            assert wl == ["NVDA", "AAPL", "JPM"], wl
            # Strategy table render with synthetic results
            from overnight_edge.strategy import compare_strategies
            from tests.helpers import two_day_scenario

            bars = two_day_scenario()
            strategies = compare_strategies(bars, starting_capital=1000.0)
            app._render_strategy_table(strategies, "5m_precise")
            assert app.strategy_tree.get_children(), "strategy tree empty"
            initial_rows = len(app.strategy_tree.get_children())
            tags = app.strategy_tree.item(app.strategy_tree.get_children()[0], "tags")
            reta = app._row_values(app._df.iloc[0].to_dict())
            print("GUI smoke OK: rows", len(app.tree.get_children()),
                  "strategy rows", initial_rows, "tags", tags)
            return 0
    finally:
        H.history_dir = old_history_dir
        root.destroy()


if __name__ == "__main__":
    raise SystemExit(main())