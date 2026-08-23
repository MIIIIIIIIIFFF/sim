"""Market session constants (US Eastern Time)."""

from __future__ import annotations

from datetime import time

import pytz

EASTERN = pytz.timezone("America/New_York")

# Regular session
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)

# Extended hours
PREMARKET_START = time(4, 0)
PREOPEN_EXIT = time(9, 29)  # sell target: just before the opening bell

# Yahoo Finance 5-minute bar interval limits (days of history available)
INTRADAY_INTERVAL = "5m"
INTRADAY_MAX_CALENDAR_DAYS = 60

# Minimum completed overnight holds required to include a stock in rankings.
# By default this equals the hold window (set dynamically in run.py) so every
# ranked stock is compared over the exact same number of nights.
MIN_TRADES_REQUIRED = 30

# Default scan parameters
DEFAULT_HOLD_COUNT = 30
DEFAULT_TOP_N = 25
DEFAULT_WORKERS = 10
DEFAULT_STARTING_CAPITAL = 10_000.0
