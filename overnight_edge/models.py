"""Typed domain models for overnight backtest results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class OvernightTrade:
    buy_date: date
    sell_date: date
    buy_price: float
    sell_price: float
    buy_bar_time: str = ""
    sell_bar_time: str = ""
    buy_price_source: str = ""
    sell_price_source: str = ""

    @property
    def return_pct(self) -> float:
        return (self.sell_price / self.buy_price - 1.0) * 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "buy_date": self.buy_date.isoformat(),
            "sell_date": self.sell_date.isoformat(),
            "buy_price": round(self.buy_price, 4),
            "sell_price": round(self.sell_price, 4),
            "return_pct": round(self.return_pct, 4),
            "buy_bar_time": self.buy_bar_time,
            "sell_bar_time": self.sell_bar_time,
            "buy_price_source": self.buy_price_source,
            "sell_price_source": self.sell_price_source,
        }


@dataclass
class BacktestResult:
    ticker: str
    trades: list[OvernightTrade]
    compounded_return_pct: float
    simple_return_pct: float
    avg_overnight_return_pct: float
    median_overnight_return_pct: float
    std_overnight_return_pct: float
    win_rate_pct: float
    best_night_pct: float
    worst_night_pct: float
    max_drawdown_pct: float
    profit_factor: float
    starting_capital: float = 10_000.0
    ending_capital: float = 10_000.0
    profit_usd: float = 0.0
    first_trade_date: date | None = None
    last_trade_date: date | None = None

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    def to_ranking_row(self) -> dict[str, Any]:
        row = asdict(self)
        row.pop("trades")
        row["trades"] = self.trade_count
        row["first_trade_date"] = self.first_trade_date.isoformat() if self.first_trade_date else ""
        row["last_trade_date"] = self.last_trade_date.isoformat() if self.last_trade_date else ""
        return row

    def trade_log_dicts(self) -> list[dict[str, Any]]:
        return [t.to_dict() for t in self.trades]


@dataclass
class ScanConfig:
    hold_count: int = 30
    lookback_days: int = 57
    max_workers: int = 10
    top_n: int = 25
    min_trades_required: int = 30  # defaults to full window; set in run.py
    max_retries: int = 3
    starting_capital: float = 10_000.0


@dataclass
class ScanResult:
    rankings: Any  # pd.DataFrame
    skipped: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    universe_size: int = 0
    scan_timestamp: str = ""
    lookback_calendar_days: int = 0
