"""Compare strategy buy prices against Yahoo official daily closes."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import yfinance as yf

from overnight_edge.data import normalize_bars
from overnight_edge.strategy import extract_overnight_trades


def main() -> int:
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    bars = normalize_bars(
        yf.download(ticker, period="15d", interval="5m", prepost=True, progress=False, auto_adjust=True)
    )
    trades = extract_overnight_trades(bars)
    daily = yf.Ticker(ticker).history(period="15d", interval="1d", auto_adjust=True)
    daily.index = pd.to_datetime(daily.index.date)

    print(f"=== Timing validation: {ticker} ({len(trades)} trades) ===\n")
    mismatches = 0
    for t in trades[-5:]:
        ts = pd.Timestamp(t.buy_date)
        if ts in daily.index:
            official = float(daily.loc[ts, "Close"])
            diff_pct = (t.buy_price - official) / official * 100
            ok = abs(diff_pct) < 0.1
            if not ok:
                mismatches += 1
            print(
                f"  BUY  {t.buy_date} @ {t.buy_bar_time} [{t.buy_price_source}]"
                f"\n       5m={t.buy_price:.4f}  daily={official:.4f}  diff={diff_pct:+.4f}%"
                f"  {'OK' if ok else 'CHECK'}"
            )
        print(
            f"  SELL {t.sell_date} @ {t.sell_bar_time} [{t.sell_price_source}]"
            f"  price={t.sell_price:.4f}  return={t.return_pct:+.4f}%\n"
        )

    print(f"Mismatches (>0.1%): {mismatches}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
