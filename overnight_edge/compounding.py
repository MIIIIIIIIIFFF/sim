"""Day-to-day compounding: each night's profit is reinvested in the next hold.

Formula
-------
    equity_0 = starting_capital
    equity_{n} = equity_{n-1} * (1 + r_n)

    compounded_return = equity_N / equity_0 - 1
                      = product(1 + r_i) - 1

This is **not** the sum of nightly percentages. A +10% night followed by a
-10% night is -1% compounded, not 0%.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class CompoundResult:
    starting_capital: float
    ending_capital: float
    profit_usd: float
    compounded_return_pct: float
    equity_path: tuple[float, ...]  # length = 1 + number of nights

    @property
    def max_drawdown_pct(self) -> float:
        if len(self.equity_path) < 2:
            return 0.0
        peak = self.equity_path[0]
        worst = 0.0
        for equity in self.equity_path:
            if equity > peak:
                peak = equity
            if peak > 0:
                dd = (equity - peak) / peak
                if dd < worst:
                    worst = dd
        return worst * 100.0


def nightly_return(buy_price: float, sell_price: float) -> float:
    """Simple overnight return for one hold: (sell / buy) - 1."""
    if buy_price <= 0:
        raise ValueError("buy_price must be positive")
    return sell_price / buy_price - 1.0


def compound_returns(
    returns: Sequence[float],
    starting_capital: float = 10_000.0,
) -> CompoundResult:
    """Reinvest 100% of equity after every overnight hold."""
    if starting_capital <= 0:
        raise ValueError("starting_capital must be positive")

    equity = float(starting_capital)
    path: list[float] = [equity]

    for r in returns:
        if r <= -1.0:
            equity = 0.0
        else:
            equity *= 1.0 + r
        path.append(equity)

    compounded = equity / starting_capital - 1.0
    return CompoundResult(
        starting_capital=starting_capital,
        ending_capital=equity,
        profit_usd=equity - starting_capital,
        compounded_return_pct=compounded * 100.0,
        equity_path=tuple(path),
    )


def annotate_equity(
    trade_dicts: list[dict],
    starting_capital: float,
) -> list[dict]:
    """Attach running compounded equity to each trade row."""
    equity = float(starting_capital)
    annotated: list[dict] = []
    for trade in trade_dicts:
        r = float(trade["return_pct"]) / 100.0
        before = equity
        if r <= -1.0:
            equity = 0.0
        else:
            equity *= 1.0 + r
        row = dict(trade)
        row["equity_before"] = round(before, 4)
        row["equity_after"] = round(equity, 4)
        row["compounded_to_date_pct"] = round((equity / starting_capital - 1.0) * 100.0, 4)
        annotated.append(row)
    return annotated
