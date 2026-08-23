"""Day-to-day compounding tests — the ranking metric of this product."""

from __future__ import annotations

import pytest

from overnight_edge.compounding import annotate_equity, compound_returns, nightly_return


def test_compound_is_not_the_sum_of_percentages():
    """+10% then -10% is -1% compounded, not 0%."""
    result = compound_returns([0.10, -0.10], starting_capital=10_000)
    assert result.compounded_return_pct == pytest.approx(-1.0)
    assert result.ending_capital == pytest.approx(9_900.0)
    assert result.profit_usd == pytest.approx(-100.0)


def test_two_winning_nights_reinvest():
    # Night 1 +2%, night 2 +3% on the new equity
    result = compound_returns([0.02, 0.03], starting_capital=10_000)
    assert result.ending_capital == pytest.approx(10_000 * 1.02 * 1.03)
    assert result.compounded_return_pct == pytest.approx(5.06)
    assert result.equity_path == pytest.approx((10_000, 10_200, 10_506))


def test_drawdown_from_first_loss():
    result = compound_returns([-0.10, 0.10], starting_capital=10_000)
    assert result.max_drawdown_pct == pytest.approx(-10.0)
    assert result.ending_capital == pytest.approx(9_900.0)


def test_nightly_return():
    assert nightly_return(100, 105) == pytest.approx(0.05)
    assert nightly_return(200, 190) == pytest.approx(-0.05)


def test_annotate_equity_running_balance():
    trades = [
        {"return_pct": 2.0},
        {"return_pct": 3.0},
    ]
    rows = annotate_equity(trades, 10_000)
    assert rows[0]["equity_before"] == 10_000
    assert rows[0]["equity_after"] == pytest.approx(10_200)
    assert rows[1]["equity_after"] == pytest.approx(10_506)
    assert rows[1]["compounded_to_date_pct"] == pytest.approx(5.06)
