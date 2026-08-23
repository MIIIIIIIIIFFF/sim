# Timing Specification

This document is the authoritative reference for how Overnight Edge maps the
user's strategy onto Yahoo Finance 5-minute bars. Every rule below is enforced
in `overnight_edge/sessions.py` and covered by unit tests.

---

## Strategy (Plain English)

| Step | When (US Eastern) | Action |
|------|-------------------|--------|
| 1 | **Day T, 16:00** | Buy at the regular-session closing price |
| 2 | Overnight | Hold through after-hours and pre-market |
| 3 | **Day T+1, 09:29** | Sell at the last pre-market price before the open |
| 4 | Repeat | Every **trading day** (Mon-Fri, excluding market holidays) |

**Ranking:** Compounded return across N overnight holds (full reinvestment each night):

```
equity_0 = starting capital
equity_n = equity_{n-1} * (1 + r_n)
compounded = equity_N / equity_0 - 1
           = product(1 + r_i) - 1
where r_i = (sell_price / buy_price) - 1
```

This is **not** the arithmetic sum of nightly percentages.

---

## Yahoo Finance 5-Minute Bar Convention

| Fact | Detail |
|------|--------|
| Timestamp | Marks the **start** of each 5-minute bucket |
| 15:55 bar | Covers 15:55:00 - 15:59:59 ET |
| 16:00 bar | When present, is the last regular-session bar; Close = official daily close |
| 09:25 bar | Covers 09:25:00 - 09:29:59 ET; Close = best proxy for 09:29 exit |
| 09:30 bar | First regular-session bar; used only as fallback exit |
| Pre-market | Starts at 04:00 ET |
| Post-market | Starts after 16:00 ET (typically 16:05 bar) |

---

## Price Selection Rules (Code)

### Buy price (Day T, target 16:00 ET)

```
regular_bars = all bars where time is between 09:30 and 16:00 (inclusive)
buy_price    = Close of the LAST regular_bars row
```

- Post-market bars (16:05+) are **never** used for entry.
- If both 15:55 and 16:00 bars exist, the 16:00 bar is used (last in range).

### Sell price (Day T+1, target 09:29 ET)

```
premarket_bars = all bars where time is between 04:00 and 09:29 (inclusive)
sell_price     = Close of the LAST premarket_bars row  (usually 09:25 bar)
```

**Fallback** (no pre-market data):

```
sell_price = Open of the 09:30 bar
```

The 09:30 bar is **excluded** from pre-market selection (`09:29` cutoff).

---

## Trading-Day Pairing

Overnight holds are only created between **consecutive trading days** in the data:

```
Monday close  -> Tuesday pre-market   (valid)
Friday close  -> Monday pre-market    (valid; weekend skipped)
Thursday close -> Monday pre-market   (invalid if Friday is a holiday with no data)
```

A day counts as a trading day only if it has at least one regular-session bar
(09:30-16:00). Days with only extended-hours data are ignored.

---

## Calendar Days vs Trading Days

| Term | Meaning |
|------|---------|
| `--days 30` | 30 **trading-day** overnight holds (not 30 calendar days) |
| Lookback | Calendar days of 5m data downloaded from Yahoo |

**Lookback formula:**

```
lookback = min( ceil((trading_days + 1) * 7/5) + 15 , 60 )
```

For 30 trading days: `ceil(31 * 7/5) + 15 = ceil(43.4) + 15 = 59` calendar days.

The `+15` buffer covers weekends and US market holidays.

**Yahoo limit:** 5-minute bars are only available for the last **60 calendar days**.

---

## Quality Gate

By default, a stock must have exactly `--days` complete overnight trades to be
ranked. This ensures every stock is compared over the **same number of nights**.

Override with `--min-trades N` if needed.

---

## Audit Trail

Each trade in `top_trades_*.csv` includes:

| Field | Purpose |
|-------|---------|
| `buy_bar_time` | Exact bar timestamp used for entry |
| `sell_bar_time` | Exact bar timestamp used for exit |
| `buy_price_source` | e.g. `regular_close_1600` |
| `sell_price_source` | e.g. `premarket_0925` or `fallback_open_0930` |

Run `python scripts/validate_timing.py AAPL` to compare buy prices against
Yahoo daily closing prices.

---

## Known Limitations

1. **5-minute granularity** - Cannot capture exact 09:29:00 tick; 09:25 bar is the closest.
2. **No transaction costs** - Commissions, spread, slippage not modeled.
3. **Fallback exits** - Stocks without pre-market data use 09:30 open (flagged in trade log).
4. **60-day Yahoo cap** - Maximum ~32 trading-day holds at 5-minute resolution.
5. **Survivorship** - S&P 500 constituents as of today, not historical membership.

---

*Overnight Edge v2.1 - See also README.md and EXECUTIVE_BRIEF.md*
