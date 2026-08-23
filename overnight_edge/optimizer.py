"""Session-window optimizer: find the best buy/sell minute-slot pair per day vs night.

Two timing families are optimized independently:

* **day** — buy in the morning window (09:30–10:30), sell in the afternoon
  window (15:00–15:55), on the same regular-session trading day.
* **night** — buy at/just after the 16:00 close (16:00–16:30, after-hours),
  sell the next morning pre-open (09:00–09:25), holding overnight.

Yahoo serves 5-minute bars whose timestamp marks the *start* of the bucket, so
"a window" is: take the first valid Close among bars whose clock time falls in
[open, close]. All reads use the bar **Close** — for day buys/sells during the
regular session and for night buys at/after the after-hours close, as well as
for night sells in the pre-open window. The optimizer intentionally uses the
precise 5-minute path only (up to ~60 calendar days); it never mixes in the
daily-bar fallback family.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from overnight_edge.compounding import compound_returns
from overnight_edge.constants import DEFAULT_STARTING_CAPITAL
from overnight_edge.paths import user_data_dir
from overnight_edge.sessions import _day_slice, all_days_in_data, has_regular_session


def _to_time(m: int) -> time:
    """minutes since midnight -> time(HH:MM)."""
    return time(m // 60, m % 60)


# Candidate windows (minute-of-day tuples for buy and sell), per family.
# day:  buy mornings, sell afternoons
# night: buy at/after close, sell next pre-open morning
DAY_BUY_MINUTES = (570, 585, 600, 615, 630)          # 09:30..10:30 morning buys
DAY_SELL_MINUTES = (900, 915, 930, 940, 955)          # 15:00..15:55 afternoon sells
NIGHT_BUY_MINUTES = (960, 968, 975, 983, 990)        # 16:00..16:30 after-hours buys
NIGHT_SELL_MINUTES = (540, 545, 550, 555, 560, 565)   # 09:00..09:25 pre-open sells

DAY_BUY_LABEL = "Jour"
NIGHT_BUY_LABEL = "Nuit"


def _valid(price: float) -> bool:
    return bool(price > 0 and np.isfinite(price))


def _first_price_in(bars: pd.DataFrame, t_from: time, t_to: time, field: str = "Close") -> Optional[float]:
    """First valid bar value whose clock time is within [t_from, t_to] (inclusive)."""
    if not t_from <= t_to:
        return None
    window = bars.between_time(t_from, t_to)
    for ts, row in window.iterrows():
        value = float(row.get(field, np.nan))
        if _valid(value):
            return value
    return None


# ---------------------------------------------------------------------------
# Trade building
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionTrade:
    """One day-or-night window trade."""

    buy_date: date
    sell_date: date
    buy_price: float
    sell_price: float
    family: str  # "day" or "night"
    slot_name: str = ""
    source: str = ""

    @property
    def return_pct(self) -> float:
        return (self.sell_price / self.buy_price - 1.0) * 100.0


def _slot_label(family: str, buy_min: int, sell_min: int) -> str:
    b = _to_time(buy_min).strftime("%H:%M")
    s = _to_time(sell_min).strftime("%H:%M")
    return f"{'Jour' if family == 'day' else 'Nuit'} {b}→{s}"


def _build_day_trades(bars: pd.DataFrame, buy_min: int, sell_min: int, start: Optional[date], end: Optional[date]) -> list[SessionTrade]:
    """One trade per trading day: buy in morning window, sell in afternoon window."""
    buy_from = _to_time(buy_min)
    buy_to = _to_time(buy_min + 10)
    sell_from = _to_time(sell_min)
    sell_to = _to_time(sell_min + 10)
    trades: list[SessionTrade] = []
    for day in all_days_in_data(bars):
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        d = _day_slice(bars, day)
        if not has_regular_session(d):
            continue
        buy = _first_price_in(d, buy_from, buy_to)
        sell = _first_price_in(d, sell_from, sell_to)
        if buy is None or sell is None:
            continue
        trades.append(SessionTrade(day, day, buy, sell, "day"))
    return trades


def _build_night_trades(bars: pd.DataFrame, buy_min: int, sell_min: int, start: Optional[date], end: Optional[date]) -> list[SessionTrade]:
    """One overnight trade per pair (day T, next day): buy at close, sell next pre-open."""
    buy_from = _to_time(buy_min)
    buy_to = _to_time(min(buy_min + 10, 16 * 60 + 30))
    sell_from = _to_time(sell_min)
    sell_to = _to_time(min(sell_min + 10, 9 * 60 + 29))
    all_days = all_days_in_data(bars)
    trades: list[SessionTrade] = []
    for i, day in enumerate(all_days):
        if start is not None and day < start:
            continue
        if end is not None and day > end:
            continue
        if i + 1 >= len(all_days):
            break
        next_day = all_days[i + 1]
        d = _day_slice(bars, day)
        nd = _day_slice(bars, next_day)
        if not has_regular_session(d) or not has_regular_session(nd):
            continue
        buy = _first_price_in(d, buy_from, buy_to)
        sell = _first_price_in(nd, sell_from, sell_to)
        if buy is None or sell is None:
            continue
        trades.append(SessionTrade(day, next_day, buy, sell, "night"))
    return trades


# --------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class SlotResult:
    """A candidate slot's outcome across the available window."""

    family: str
    slot_name: str
    buy_minute: int
    sell_minute: int
    trades: list[SessionTrade]
    compounded_return_pct: float
    simple_return_pct: float
    avg_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    day_count: int


def evaluate_slot(
    bars: pd.DataFrame,
    family: str,
    buy_minute: int,
    sell_minute: int,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> Optional[SlotResult]:
    """Evaluate one (buy, sell) minute slot; None when no trades are buildable."""
    if family == "day":
        trades = _build_day_trades(bars, buy_minute, sell_minute, start, end)
    elif family == "night":
        trades = _build_night_trades(bars, buy_minute, sell_minute, start, end)
    else:
        raise ValueError(f"unknown family {family!r}")
    if not trades:
        return None

    returns = [t.return_pct / 100.0 for t in trades]
    compounded = compound_returns(returns, DEFAULT_STARTING_CAPITAL)
    wins = [r for r in returns if r > 0]
    n = len(returns)
    return SlotResult(
        family=family,
        slot_name=_slot_label(family, buy_minute, sell_minute),
        buy_minute=buy_minute,
        sell_minute=sell_minute,
        trades=trades,
        compounded_return_pct=compounded.compounded_return_pct,
        simple_return_pct=sum(returns) * 100,
        avg_return_pct=sum(returns) / n * 100,
        win_rate_pct=len(wins) / n * 100,
        max_drawdown_pct=compounded.max_drawdown_pct,
        day_count=n,
    )


def families_candidates() -> list[tuple[str, list[tuple[int, int]]]]:
    """Return (family, [(buy_min, sell_min), ...]) for both families."""
    return [
        ("day", [(b, s) for b in DAY_BUY_MINUTES for s in DAY_SELL_MINUTES]),
        ("night", [(b, s) for b in NIGHT_BUY_MINUTES for s in NIGHT_SELL_MINUTES]),
    ]


def evaluate_all_slots(
    bars: pd.DataFrame,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> list[SlotResult]:
    """Evaluate every candidate slot in both families, sorted best-first."""
    results: list[SlotResult] = []
    for family, slots in families_candidates():
        for b, s in slots:
            r = evaluate_slot(bars, family, b, s, start=start, end=end)
            if r is not None:
                results.append(r)
    results.sort(key=lambda r: r.compounded_return_pct, reverse=True)
    return results


def best_per_family(
    bars: pd.DataFrame,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> dict[str, Optional[SlotResult]]:
    """Return the best slot for each family (day and night)."""
    best: dict[str, Optional[SlotResult]] = {"day": None, "night": None}
    for family, slots in families_candidates():
        for b, s in slots:
            r = evaluate_slot(bars, family, b, s, start=start, end=end)
            if r is not None and (best[family] is None or r.compounded_return_pct > best[family].compounded_return_pct):
                best[family] = r
    return best


# ---------------------------------------------------------------------------
# Persisted watchlists / favorite lists (JSON in user data dir)
# ---------------------------------------------------------------------------

_FAVORITES_FILE = "optimizer_favorites.json"


def favorites_path() -> Path:
    """Path to the favorites JSON."""
    return user_data_dir() / _FAVORITES_FILE


def load_favorites() -> dict[str, list[str]]:
    """Return {watchlist_name: [tickers]} from disk (never raises)."""
    try:
        import json
        path = favorites_path()
        if path is not None and Path(path).exists():
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                return {str(k): [str(t).upper() for t in v] for k, v in raw.items() if isinstance(v, list)}
    except Exception:
        pass
    return {}


def save_favorites(favorites: dict[str, list[str]]) -> None:
    try:
        import json
        path = favorites_path()
        if path is not None:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({k: v for k, v in favorites.items()}, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass