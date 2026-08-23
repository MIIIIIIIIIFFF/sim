"""Overnight hold strategy: buy at close, sell before the open."""

from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from overnight_edge.compounding import compound_returns, nightly_return
from overnight_edge.constants import DEFAULT_STARTING_CAPITAL, MIN_TRADES_REQUIRED
from overnight_edge.data import normalize_bars
from overnight_edge.models import BacktestResult, OvernightTrade
from overnight_edge.sessions import (
    PricePoint,
    _day_slice,
    all_days_in_data,
    has_regular_session,
    is_next_trading_day,
    select_close_buy,
    select_preopen_sell,
    select_session_close_sell,
    select_session_open_buy,
    trading_days_with_session,
)


def close_buy_price(day_bars: pd.DataFrame) -> Optional[float]:
    point = select_close_buy(day_bars)
    return point.price if point else None


def preopen_sell_price(day_bars: pd.DataFrame) -> Optional[float]:
    point = select_preopen_sell(day_bars)
    return point.price if point else None


def _profit_factor(returns: list[float]) -> float:
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def extract_overnight_trades(bars: pd.DataFrame) -> list[OvernightTrade]:
    """
    Pair each session close (day T) with the next session's pre-open price (day T+1).

    Pairing rules
    -------------
    * Only consecutive dates present in the 5-minute data are paired.
      Weekends and holidays with no bars are skipped automatically
      (Friday close pairs with Monday pre-market).
    * Buy day must have a regular-session bar (09:30-16:00).
    * Sell day must have a pre-market bar (04:00-09:29) or 09:30 open fallback.
    """
    bars = normalize_bars(bars)
    if bars.empty:
        return []

    all_days = all_days_in_data(bars)
    if len(all_days) < 2:
        return []

    trades: list[OvernightTrade] = []

    for i in range(len(all_days) - 1):
        buy_day = all_days[i]
        sell_day = all_days[i + 1]

        if not is_next_trading_day(buy_day, sell_day, all_days):
            continue

        buy_bars = _day_slice(bars, buy_day)
        sell_bars = _day_slice(bars, sell_day)

        if not has_regular_session(buy_bars):
            continue

        buy_point = select_close_buy(buy_bars)
        sell_point = select_preopen_sell(sell_bars)
        if buy_point is None or sell_point is None:
            continue

        trades.append(_trade_from_points(buy_day, sell_day, buy_point, sell_point))

    return trades


def _trade_from_points(
    buy_day: date,
    sell_day: date,
    buy_point: PricePoint,
    sell_point: PricePoint,
) -> OvernightTrade:
    return OvernightTrade(
        buy_date=buy_day,
        sell_date=sell_day,
        buy_price=buy_point.price,
        sell_price=sell_point.price,
        buy_bar_time=buy_point.bar_time.isoformat(),
        sell_bar_time=sell_point.bar_time.isoformat(),
        buy_price_source=buy_point.source,
        sell_price_source=sell_point.source,
    )


def extract_intraday_trades(bars: pd.DataFrame) -> list[OvernightTrade]:
    """
    Intraday holds: buy at the 09:30 open, sell at the same day's 16:00 close.

    Only days with a full regular session (09:30-16:00) produce a trade.
    Because the open and close fall on the same calendar day, these use
    ``sell_date == buy_date``.
    """
    bars = normalize_bars(bars)
    if bars.empty:
        return []

    trades: list[OvernightTrade] = []
    for day in all_days_in_data(bars):
        day_bars = _day_slice(bars, day)
        if not has_regular_session(day_bars):
            continue
        open_point = select_session_open_buy(day_bars)
        close_point = select_session_close_sell(day_bars)
        if open_point is None or close_point is None:
            continue
        trades.append(_trade_from_points(day, day, open_point, close_point))
    return trades


def extract_buyhold_trades(bars: pd.DataFrame) -> list[OvernightTrade]:
    """
    Buy & Hold: buy at the 09:30 open of the first session, sell at the close
    of the last session in the window. Yields a single net trade spanning the
    whole period, so compounding is a no-op — the result IS the simple return.
    """
    bars = normalize_bars(bars)
    trading_days = trading_days_with_session(bars)
    if len(trading_days) < 2:
        return []

    first = _day_slice(bars, trading_days[0])
    last = _day_slice(bars, trading_days[-1])
    open_point = select_session_open_buy(first)
    close_point = select_session_close_sell(last)
    if open_point is None or close_point is None:
        return []
    return [_trade_from_points(trading_days[0], trading_days[-1], open_point, close_point)]


def extract_overnight_daily_trades(bars: pd.DataFrame) -> list[OvernightTrade]:
    """
    Overnight trades from daily bars (fallback when 5-minute data is unavailable).

    Buy = day T Close (regular-session close proxy), sell = day T+1 Open (09:30
    proxy for 09:29 pre-open). Same compounding model as the 5-minute overnight
    path, but each trade is labeled with ``daily_close`` / ``daily_open`` sources
    so the UI can mark results as "Approximatif".
    """
    bars = normalize_bars(bars)
    if bars.empty:
        return []
    all_days = all_days_in_data(bars)
    if len(all_days) < 2:
        return []

    trades: list[OvernightTrade] = []
    for i in range(len(all_days) - 1):
        buy_day = all_days[i]
        sell_day = all_days[i + 1]
        buy_bars = _day_slice(bars, buy_day)
        sell_bars = _day_slice(bars, sell_day)
        if buy_bars.empty or sell_bars.empty:
            continue
        buy_close = float(buy_bars["Close"].iloc[-1])
        sell_open = float(sell_bars["Open"].iloc[0])
        if not (buy_close > 0 and sell_open > 0) or not (
            np.isfinite(buy_close) and np.isfinite(sell_open)
        ):
            continue
        trades.append(
            OvernightTrade(
                buy_date=buy_day,
                sell_date=sell_day,
                buy_price=buy_close,
                sell_price=sell_open,
                buy_bar_time=str(buy_day),
                sell_bar_time=str(sell_day),
                buy_price_source="daily_close",
                sell_price_source="daily_open",
            )
        )
    return trades


def backtest_overnight_daily_windowed(
    bars: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_trades: Optional[int] = None,
    min_trades: int = 1,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> Optional[BacktestResult]:
    """Backtest the overnight strategy on daily-bar fallback data."""
    all_trades = extract_overnight_daily_trades(bars)
    if not all_trades:
        return None
    if start_date is not None:
        all_trades = [t for t in all_trades if t.buy_date >= start_date]
    if end_date is not None:
        all_trades = [t for t in all_trades if t.buy_date <= end_date]
    if not all_trades:
        return None
    if max_trades is not None and len(all_trades) > max_trades:
        all_trades = all_trades[-max_trades:]
    if len(all_trades) < min_trades:
        return None
    return _summarize_trades(all_trades, starting_capital)


def backtest_overnight(
    bars: pd.DataFrame,
    hold_count: int,
    min_trades: int = MIN_TRADES_REQUIRED,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> Optional[BacktestResult]:
    """
    Backtest the overnight strategy with day-to-day compounding.

    Each night's P&L is reinvested: equity *= (1 + nightly_return).
    Ranking uses compounded_return_pct, which equals ending/start - 1.
    """
    all_trades = extract_overnight_trades(bars)
    if not all_trades:
        return None

    if len(all_trades) > hold_count:
        all_trades = all_trades[-hold_count:]

    if len(all_trades) < min_trades:
        return None

    returns = [nightly_return(t.buy_price, t.sell_price) for t in all_trades]
    compounded = compound_returns(returns, starting_capital)
    pf = _profit_factor(returns)

    return BacktestResult(
        ticker="",
        trades=all_trades,
        compounded_return_pct=compounded.compounded_return_pct,
        simple_return_pct=float(sum(returns) * 100),
        avg_overnight_return_pct=float(sum(returns) / len(returns) * 100),
        median_overnight_return_pct=_median_pct(returns),
        std_overnight_return_pct=_sample_std_pct(returns),
        win_rate_pct=float(sum(1 for r in returns if r > 0) / len(returns) * 100),
        best_night_pct=float(max(returns) * 100),
        worst_night_pct=float(min(returns) * 100),
        max_drawdown_pct=compounded.max_drawdown_pct,
        profit_factor=pf if pf != float("inf") else 999.99,
        starting_capital=compounded.starting_capital,
        ending_capital=compounded.ending_capital,
        profit_usd=compounded.profit_usd,
        first_trade_date=all_trades[0].buy_date,
        last_trade_date=all_trades[-1].sell_date,
    )


def backtest_overnight_windowed(
    bars: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_trades: Optional[int] = None,
    min_trades: int = 1,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> Optional[BacktestResult]:
    """Backtest over a selected calendar bracket (both dates inclusive).

    Trades are matched with the standard close->pre-open pairing, then only
    the subset whose BUY day falls inside ``[start_date, end_date]`` is kept.
    ``max_trades`` keeps the most recent N (used by the last-N-days quick pick).
    Uses the same core as the full-scan path so the number is comparable.
    """
    all_trades = extract_overnight_trades(bars)
    if not all_trades:
        return None

    if start_date is not None:
        all_trades = [t for t in all_trades if t.buy_date >= start_date]
    if end_date is not None:
        all_trades = [t for t in all_trades if t.buy_date <= end_date]
    if not all_trades:
        return None
    if max_trades is not None and len(all_trades) > max_trades:
        all_trades = all_trades[-max_trades:]
    if len(all_trades) < min_trades:
        return None

    returns = [nightly_return(t.buy_price, t.sell_price) for t in all_trades]
    compounded = compound_returns(returns, starting_capital)
    pf = _profit_factor(returns)

    return BacktestResult(
        ticker="",
        trades=all_trades,
        compounded_return_pct=compounded.compounded_return_pct,
        simple_return_pct=float(sum(returns) * 100),
        avg_overnight_return_pct=float(sum(returns) / len(returns) * 100),
        median_overnight_return_pct=_median_pct(returns),
        std_overnight_return_pct=_sample_std_pct(returns),
        win_rate_pct=float(sum(1 for r in returns if r > 0) / len(returns) * 100),
        best_night_pct=float(max(returns) * 100),
        worst_night_pct=float(min(returns) * 100),
        max_drawdown_pct=compounded.max_drawdown_pct,
        profit_factor=pf if pf != float("inf") else 999.99,
        starting_capital=compounded.starting_capital,
        ending_capital=compounded.ending_capital,
        profit_usd=compounded.profit_usd,
        first_trade_date=all_trades[0].buy_date,
        last_trade_date=all_trades[-1].sell_date,
    )


def _median_pct(returns: list[float]) -> float:
    ordered = sorted(returns)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid] * 100)
    return float((ordered[mid - 1] + ordered[mid]) / 2 * 100)


def _sample_std_pct(returns: list[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    return float(var ** 0.5 * 100)


def _summarize_trades(
    trades: list[OvernightTrade],
    starting_capital: float,
) -> Optional[BacktestResult]:
    """Build a BacktestResult from a list of trades (compounding aware)."""
    if not trades:
        return None
    returns = [nightly_return(t.buy_price, t.sell_price) for t in trades]
    compounded = compound_returns(returns, starting_capital)
    pf = _profit_factor(returns)
    return BacktestResult(
        ticker="",
        trades=trades,
        compounded_return_pct=compounded.compounded_return_pct,
        simple_return_pct=float(sum(returns) * 100),
        avg_overnight_return_pct=float(sum(returns) / len(returns) * 100),
        median_overnight_return_pct=_median_pct(returns),
        std_overnight_return_pct=_sample_std_pct(returns),
        win_rate_pct=float(sum(1 for r in returns if r > 0) / len(returns) * 100),
        best_night_pct=float(max(returns) * 100),
        worst_night_pct=float(min(returns) * 100),
        max_drawdown_pct=compounded.max_drawdown_pct,
        profit_factor=pf if pf != float("inf") else 999.99,
        starting_capital=compounded.starting_capital,
        ending_capital=compounded.ending_capital,
        profit_usd=compounded.profit_usd,
        first_trade_date=trades[0].buy_date,
        last_trade_date=trades[-1].sell_date,
    )


def backtest_intraday_windowed(
    bars: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_trades: Optional[int] = None,
    min_trades: int = 1,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> Optional[BacktestResult]:
    """Backtest the intraday strategy (09:30 open -> same-day 16:00 close).

    Compounding still applies day over day: each day's P&L is reinvested,
    so intraday returns compound too and compare like-for-like with overnight.
    """
    all_trades = extract_intraday_trades(bars)
    if not all_trades:
        return None
    if start_date is not None:
        all_trades = [t for t in all_trades if t.buy_date >= start_date]
    if end_date is not None:
        all_trades = [t for t in all_trades if t.buy_date <= end_date]
    if not all_trades:
        return None
    if max_trades is not None and len(all_trades) > max_trades:
        all_trades = all_trades[-max_trades:]
    if len(all_trades) < min_trades:
        return None
    return _summarize_trades(all_trades, starting_capital)


def backtest_buyhold_windowed(
    bars: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
) -> Optional[BacktestResult]:
    """
    Backtest the Buy & Hold strategy over a window.

    A single net trade spans open of the first session to close of the last.
    The window is bounded by ``start_date``/``end_date`` when given; otherwise
    it spans every session present in the data. Because there is one hold,
    compounded == simple return by construction.
    """
    bars = normalize_bars(bars)
    trading_days = trading_days_with_session(bars)
    if start_date is not None:
        trading_days = [d for d in trading_days if d >= start_date]
    if end_date is not None:
        trading_days = [d for d in trading_days if d <= end_date]
    if len(trading_days) < 2:
        return None

    first = _day_slice(bars, trading_days[0])
    last = _day_slice(bars, trading_days[-1])
    open_point = select_session_open_buy(first)
    close_point = select_session_close_sell(last)
    if open_point is None or close_point is None:
        return None
    trades = [
        _trade_from_points(trading_days[0], trading_days[-1], open_point, close_point)
    ]
    return _summarize_trades(trades, starting_capital)


def _daily_intraday(
    bars: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    max_trades: Optional[int],
    starting_capital: float,
) -> Optional[BacktestResult]:
    """Intraday (open->close) on daily bars: one trade per trading day."""
    bars = normalize_bars(bars)
    if bars.empty:
        return None
    days = all_days_in_data(bars)
    trades: list[OvernightTrade] = []
    for d in days:
        day_bars = _day_slice(bars, d)
        if day_bars.empty:
            continue
        open_p = float(day_bars["Open"].iloc[0])
        close_p = float(day_bars["Close"].iloc[-1])
        if not (open_p > 0 and close_p > 0) or not (
            np.isfinite(open_p) and np.isfinite(close_p)
        ):
            continue
        trades.append(
            OvernightTrade(
                buy_date=d,
                sell_date=d,
                buy_price=open_p,
                sell_price=close_p,
                buy_bar_time=str(d),
                sell_bar_time=str(d),
                buy_price_source="daily_open",
                sell_price_source="daily_close",
            )
        )
    if not trades:
        return None
    if start_date is not None:
        trades = [t for t in trades if t.buy_date >= start_date]
    if end_date is not None:
        trades = [t for t in trades if t.buy_date <= end_date]
    if not trades:
        return None
    if max_trades is not None and len(trades) > max_trades:
        trades = trades[-max_trades:]
    return _summarize_trades(trades, starting_capital)


def _daily_buyhold(
    bars: pd.DataFrame,
    start_date: Optional[date],
    end_date: Optional[date],
    starting_capital: float,
) -> Optional[BacktestResult]:
    """Buy & Hold on daily bars: open of first day -> close of last day."""
    bars = normalize_bars(bars)
    days = all_days_in_data(bars)
    if start_date is not None:
        days = [d for d in days if d >= start_date]
    if end_date is not None:
        days = [d for d in days if d <= end_date]
    if len(days) < 2:
        return None
    first = _day_slice(bars, days[0])
    last = _day_slice(bars, days[-1])
    if first.empty or last.empty:
        return None
    open_p = float(first["Open"].iloc[0])
    close_p = float(last["Close"].iloc[-1])
    if not (open_p > 0 and close_p > 0) or not (
        np.isfinite(open_p) and np.isfinite(close_p)
    ):
        return None
    trade = OvernightTrade(
        buy_date=days[0],
        sell_date=days[-1],
        buy_price=open_p,
        sell_price=close_p,
        buy_bar_time=str(days[0]),
        sell_bar_time=str(days[-1]),
        buy_price_source="daily_open",
        sell_price_source="daily_close",
    )
    return _summarize_trades([trade], starting_capital)


def compare_strategies(
    bars: pd.DataFrame,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    max_trades: Optional[int] = None,
    starting_capital: float = DEFAULT_STARTING_CAPITAL,
    source: str = "5m_precise",
) -> dict[str, Optional[BacktestResult]]:
    """
    Compute Overnight vs Intraday vs Buy & Hold for the same data window.

    Returns ``{"overnight": ..., "intraday": ..., "buyhold": ...}``. ``None``
    means the strategy had no usable trades in the window. All three share the
    same start/end bracket and, where applicable, the same ``max_trades`` so
    the numbers are directly comparable.

    ``source`` selects the overnight extraction path:
    - ``"5m_precise"`` (default): 16:00 close -> 09:29 pre-open from 5-minute bars.
    - ``"daily_fallback"``: day-T close -> day-(T+1) open from daily bars
      (approximation; intraday/buy&hold still use the same daily bars for
      comparability).
    """
    if source == "daily_fallback":
        overnight = backtest_overnight_daily_windowed(
            bars,
            start_date=start_date,
            end_date=end_date,
            max_trades=max_trades,
            min_trades=1,
            starting_capital=starting_capital,
        )
        # Intraday and Buy&Hold on daily bars: a "day" holds open->close.
        intraday = _daily_intraday(bars, start_date, end_date, max_trades, starting_capital)
        buyhold = _daily_buyhold(bars, start_date, end_date, starting_capital)
        return {"overnight": overnight, "intraday": intraday, "buyhold": buyhold}
    return {
        "overnight": backtest_overnight_windowed(
            bars,
            start_date=start_date,
            end_date=end_date,
            max_trades=max_trades,
            min_trades=1,
            starting_capital=starting_capital,
        ),
        "intraday": backtest_intraday_windowed(
            bars,
            start_date=start_date,
            end_date=end_date,
            max_trades=max_trades,
            min_trades=1,
            starting_capital=starting_capital,
        ),
        "buyhold": backtest_buyhold_windowed(
            bars,
            start_date=start_date,
            end_date=end_date,
            starting_capital=starting_capital,
        ),
    }
