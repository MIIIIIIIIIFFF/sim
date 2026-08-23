# Overnight Edge Scanner

Ranks the largest US stocks by **day-to-day compounded overnight profit**.

**Buy 16:00 ET close → sell 09:29 ET next morning → reinvest 100% of equity every night.**

---

## Install on any Windows PC (no Python)

Give them the folder `dist\GiveToBoss\`:

1. **OvernightEdgeSetup.exe** — double-click (no administrator). Installs under the user profile, Start Menu, optional desktop shortcut.
2. Or double-click **OvernightEdge.exe** for a portable run (history still saved in `%APPDATA%\OvernightEdge`).

If Windows SmartScreen appears: **More info → Run anyway**.

On launch: birthday animation **Bonne fête Simon 2026**, then the daily S&P 500 scanner.

Run once per trading day. The full list shows **Δ Rank** and **Δ Compounded** vs the previous saved scan. Reports: `%APPDATA%\OvernightEdge\output`.

To rebuild both binaries: `python -m PyInstaller --noconfirm OvernightEdge.spec` then `python -m PyInstaller --noconfirm OvernightEdgeSetup.spec`.

---

## For developers

```powershell
pip install -r requirements.txt
python app.py                 # interactive GUI
python run.py --interactive   # terminal prompts
python run.py                 # S&P 500, 30 nights, $10,000 starting capital
pytest
```

### Compounding (the ranking number)

```
equity_0 = starting capital
equity_n = equity_{n-1} × (1 + nightly_return_n)
compounded % = equity_N / equity_0 − 1
```

This is **not** the sum of daily percentages. +10% then −10% = **−1%** compounded.

### Timing (Yahoo 5-minute bars)

See **TIMING.md**. Buy = last regular bar 09:30–16:00. Sell = last pre-market bar 04:00–09:29 (typically 09:25).

`--days 30` means **30 trading-day overnight holds**, not 30 calendar days. Lookback is 59 calendar days of 5-minute data (Yahoo cap: 60).

---

## Outputs (`output/`)

| File | Use |
|------|-----|
| `report_latest.html` | Dashboard with Ending $ and Profit $ |
| `rankings_latest.csv` | Full table for Excel |
| `top_trades_*.csv` | Night-by-night log with running compounded equity |
| `scan_latest.json` | Audit trail of parameters |

---

## CLI

```
python run.py --days 30 --capital 10000 --gui
python run.py --tickers AAPL,MSFT,NVDA --days 20 --capital 25000
```

---

*Overnight Edge v2.7.0 — research tool, not investment advice.*
