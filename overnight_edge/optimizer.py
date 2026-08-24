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

# Crossover add-on windows ("crossing" the two circles). When enabled:
# - the DAY family may also buy pre-open and sell after-hours (same trading day);
# - the NIGHT family may also buy before the close (= the day afternoon sells)
#   and sell after the open (= the day morning buys), still holding overnight.
CROSS_DAY_BUY_MINUTES = (540, 545, 550, 555, 560, 565)   # 09:00..09:25 pre-open buys
CROSS_DAY_SELL_MINUTES = (960, 968, 975, 983, 990)       # 16:00..16:30 after-hours sells
CROSS_NIGHT_BUY_MINUTES = (900, 915, 930, 940, 955)      # 15:00..15:55 pre-close buys (= day sells)
CROSS_NIGHT_SELL_MINUTES = (570, 585, 600, 615, 630)     # 09:30..10:30 post-open sells (= day buys)

DAY_BUY_LABEL = "Jour"
NIGHT_BUY_LABEL = "Nuit"


def _valid(price: float) -> bool:
    return bool(price > 0 and np.isfinite(price))


def _first_price_in(bars: pd.DataFrame, t_from: time, t_to: time, field: str = "Close") -> Optional[float]:
    """First valid bar value whose clock time is within [t_from, t_to] (inclusive)."""
    if not t_from <= t_to:
        return None
    window = bars.between_time(t_from, t_to)
    if window.empty:
        return None
    series = window[field]
    # Fast path: dropna returns the valid entries in index order; take the first.
    valid = series.dropna()
    if valid.empty:
        return None
    first = float(valid.iloc[0])
    return first if _valid(first) else None


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
    # Crossover night sells that target a regular-session window (>= 09:30,
    # e.g. after the open) must be able to read those mid-day bars; the pre-open
    # cap only applies to the standard pre-open sell windows (< 09:30).
    if sell_min >= 9 * 60 + 30:
        sell_to = _to_time(min(sell_min + 10, 16 * 60 + 29))
    else:
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


def families_candidates(crossover: bool = False) -> list[tuple[str, list[tuple[int, int]]]]:
    """Return (family, [(buy_min, sell_min), ...]) for both families.

    With ``crossover=True`` the DAY and NIGHT candidate windows are widened so
    each family can also use the other's timing territory (see the
    ``CROSS_*_MINUTES`` windows): the two circles are allowed to "cross".
    """
    if crossover:
        day_buys = _unique_sorted(DAY_BUY_MINUTES + CROSS_DAY_BUY_MINUTES)
        day_sells = _unique_sorted(DAY_SELL_MINUTES + CROSS_DAY_SELL_MINUTES)
        night_buys = _unique_sorted(NIGHT_BUY_MINUTES + CROSS_NIGHT_BUY_MINUTES)
        night_sells = _unique_sorted(NIGHT_SELL_MINUTES + CROSS_NIGHT_SELL_MINUTES)
    else:
        day_buys, day_sells = DAY_BUY_MINUTES, DAY_SELL_MINUTES
        night_buys, night_sells = NIGHT_BUY_MINUTES, NIGHT_SELL_MINUTES
    return [
        ("day", [(b, s) for b in day_buys for s in day_sells]),
        ("night", [(b, s) for b in night_buys for s in night_sells]),
    ]


def _unique_sorted(items):
    seen: set[int] = set()
    out: list[int] = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def evaluate_all_slots(
    bars: pd.DataFrame,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    crossover: bool = False,
) -> list[SlotResult]:
    """Evaluate every candidate slot in both families, sorted best-first.

    Uses a vectorized precompute path: for each family, the first valid Close at
    every candidate buy/sell minute is resolved once per trading day, then all
    (buy, sell) slots are assembled from that lookup table. This avoids the
    O(slots × days × bars) cost of re-slicing the frame for every slot.
    """
    results: list[SlotResult] = []
    for family, slots in families_candidates(crossover=crossover):
        if not slots:
            continue
        buy_minutes = sorted({b for b, _ in slots})
        sell_minutes = sorted({s for _, s in slots})
        day_prices = _precompute_family_prices(
            bars, family, buy_minutes, sell_minutes, start, end
        )
        # day_prices: list of dicts {buy_min: price, sell_min: price}, one per
        # valid (day [, next_day]) anchor, in chronological order.
        for b, s in slots:
            trades: list[SessionTrade] = []
            for px in day_prices:
                buy = px["buy"].get(b)
                sell = px["sell"].get(s)
                if buy is None or sell is None:
                    continue
                if family == "day":
                    trades.append(SessionTrade(px["day"], px["day"], buy, sell, "day"))
                else:
                    trades.append(SessionTrade(px["day"], px["next_day"], buy, sell, "night"))
            if not trades:
                continue
            results.append(_slot_result_from_trades(family, b, s, trades))
    results.sort(key=lambda r: r.compounded_return_pct, reverse=True)
    return results


def _precompute_family_prices(
    bars: pd.DataFrame,
    family: str,
    buy_minutes: list[int],
    sell_minutes: list[int],
    start: Optional[date],
    end: Optional[date],
) -> list[dict]:
    """Resolve the first valid Close at each candidate minute, once per day.

    Returns one dict per valid trading anchor: ``{"day", ["next_day"],
    "buy": {minute: price}, "sell": {minute: price}}``.

    The frame is grouped by calendar date once; each group's minute-of-day and
    Close arrays are precomputed as numpy arrays so every window lookup is a
    cheap searchsorted + slice with no pandas overhead per call.
    """
    all_days = all_days_in_data(bars)
    if not all_days:
        return []

    # Precompute per-day numpy arrays once: {date: (minutes, closes, has_session)}.
    day_arrays: dict[date, tuple[np.ndarray, np.ndarray, bool]] = {}
    for day_val, group in bars.groupby(bars.index.date):
        mins = (group.index.hour * 60 + group.index.minute).to_numpy()
        closes = group["Close"].to_numpy()
        has_sess = bool(((mins >= 570) & (mins <= 960)).any())
        # Groups from groupby are already sorted by index, so mins is ascending.
        day_arrays[day_val] = (mins, closes, has_sess)

    def _arrays(day: date) -> tuple[np.ndarray, np.ndarray, bool]:
        return day_arrays.get(day, (None, None, False))

    out: list[dict] = []

    buy_windows = {b: (_to_time(b), _to_time(b + 10)) for b in buy_minutes}
    if family == "night":
        sell_windows = {}
        for s in sell_minutes:
            if s >= 9 * 60 + 30:
                sell_to = min(s + 10, 16 * 60 + 29)
            else:
                sell_to = min(s + 10, 9 * 60 + 29)
            sell_windows[s] = (_to_time(s), _to_time(sell_to))
    else:
        sell_windows = {s: (_to_time(s), _to_time(s + 10)) for s in sell_minutes}

    if family == "day":
        for day in all_days:
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            mins, closes, has_sess = _arrays(day)
            if not has_sess:
                continue
            buy_px, sell_px = _resolve_minutes_arr(mins, closes, buy_windows, sell_windows)
            out.append({"day": day, "buy": buy_px, "sell": sell_px})
    else:  # night
        for i, day in enumerate(all_days):
            if start is not None and day < start:
                continue
            if end is not None and day > end:
                continue
            if i + 1 >= len(all_days):
                break
            next_day = all_days[i + 1]
            bmins, bcloses, b_sess = _arrays(day)
            nmins, ncloses, n_sess = _arrays(next_day)
            if not b_sess or not n_sess:
                continue
            buy_px, _ = _resolve_minutes_arr(bmins, bcloses, buy_windows, {})
            _, sell_px = _resolve_minutes_arr(nmins, ncloses, {}, sell_windows)
            out.append({"day": day, "next_day": next_day, "buy": buy_px, "sell": sell_px})
    return out


def _resolve_minutes_arr(
    mins: np.ndarray,
    closes: np.ndarray,
    buy_windows: dict[int, tuple[time, time]],
    sell_windows: dict[int, tuple[time, int]],
) -> tuple[dict[int, Optional[float]], dict[int, Optional[float]]]:
    """First valid Close per window from precomputed (ascending) minute/closes arrays."""
    buy_px: dict[int, Optional[float]] = {m: None for m in buy_windows}
    sell_px: dict[int, Optional[float]] = {m: None for m in sell_windows}
    if mins is None or len(mins) == 0:
        return buy_px, sell_px

    valid_mask = np.isfinite(closes) & (closes > 0)
    suffix_any = np.cumsum(valid_mask[::-1])[::-1] > 0

    def _first(lo: int, hi: int) -> Optional[float]:
        left = int(np.searchsorted(mins, lo, side="left"))
        right = int(np.searchsorted(mins, hi, side="right"))
        if left >= right or not suffix_any[left]:
            return None
        sub_valid = valid_mask[left:right]
        if not sub_valid.any():
            return None
        return float(closes[left + int(sub_valid.argmax())])

    for m, (t0, t1) in buy_windows.items():
        buy_px[m] = _first(t0.hour * 60 + t0.minute, t1.hour * 60 + t1.minute)
    for m, (t0, t1) in sell_windows.items():
        sell_px[m] = _first(t0.hour * 60 + t0.minute, t1.hour * 60 + t1.minute)
    return buy_px, sell_px


def _slot_result_from_trades(family: str, buy_minute: int, sell_minute: int,
                             trades: list[SessionTrade]) -> SlotResult:
    """Build a SlotResult from an already-assembled trade list (shared by both paths)."""
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


def best_per_family(
    bars: pd.DataFrame,
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    crossover: bool = False,
) -> dict[str, Optional[SlotResult]]:
    """Return the best slot for each family (day and night).

    Uses the same vectorized precompute path as ``evaluate_all_slots``.
    """
    best: dict[str, Optional[SlotResult]] = {"day": None, "night": None}
    for family, slots in families_candidates(crossover=crossover):
        if not slots:
            continue
        buy_minutes = sorted({b for b, _ in slots})
        sell_minutes = sorted({s for _, s in slots})
        day_prices = _precompute_family_prices(
            bars, family, buy_minutes, sell_minutes, start, end
        )
        for b, s in slots:
            trades: list[SessionTrade] = []
            for px in day_prices:
                buy = px["buy"].get(b)
                sell = px["sell"].get(s)
                if buy is None or sell is None:
                    continue
                if family == "day":
                    trades.append(SessionTrade(px["day"], px["day"], buy, sell, "day"))
                else:
                    trades.append(SessionTrade(px["day"], px["next_day"], buy, sell, "night"))
            if not trades:
                continue
            r = _slot_result_from_trades(family, b, s, trades)
            if best[family] is None or r.compounded_return_pct > best[family].compounded_return_pct:
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