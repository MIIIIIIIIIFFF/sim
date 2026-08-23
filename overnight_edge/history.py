"""Persist daily S&P 500 scans and compute rank/return variances vs a prior run."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import pytz

from overnight_edge.constants import EASTERN
from overnight_edge.paths import history_dir

SNAPSHOT_COLUMNS = [
    "rank",
    "ticker",
    "company",
    "sector",
    "compounded_return_pct",
    "ending_capital",
    "profit_usd",
    "avg_overnight_return_pct",
    "win_rate_pct",
    "max_drawdown_pct",
    "trades",
]


def _scan_date(stamp: str | None = None) -> str:
    """Calendar date in US Eastern — the market's date, not UTC."""
    if stamp:
        try:
            dt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(EASTERN).date().isoformat()
        except ValueError:
            pass
    return datetime.now(timezone.utc).astimezone(EASTERN).date().isoformat()


def current_scan_date(stamp: str = "") -> str:
    return _scan_date(stamp or None)


def snapshot_path(scan_date: str):
    return history_dir() / f"{scan_date}.json"


def save_daily_snapshot(df: pd.DataFrame, scan_timestamp: str = "") -> str:
    """Write today's ranking snapshot. Overwrites if you re-run the same day."""
    day = _scan_date(scan_timestamp)
    cols = [c for c in SNAPSHOT_COLUMNS if c in df.columns]
    payload = {
        "scan_date": day,
        "scan_timestamp": scan_timestamp,
        "rows": json.loads(df[cols].to_json(orient="records")),
    }
    text = json.dumps(payload, indent=2)
    snapshot_path(day).write_text(text, encoding="utf-8")
    (history_dir() / "latest.json").write_text(text, encoding="utf-8")
    return day


def list_snapshot_dates() -> list[str]:
    return sorted(path.stem for path in history_dir().glob("????-??-??.json"))


def load_snapshot(scan_date: str) -> Optional[pd.DataFrame]:
    path = snapshot_path(scan_date)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("rows", [])
    if not rows:
        return None
    return pd.DataFrame(rows)


def load_previous_snapshot(current_date: str) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """Most recent saved scan strictly before current_date."""
    prior = [d for d in list_snapshot_dates() if d < current_date]
    if not prior:
        return None, None
    day = prior[-1]
    return load_snapshot(day), day


def attach_variance(current: pd.DataFrame, previous: Optional[pd.DataFrame]) -> pd.DataFrame:
    """
    Add day-to-day columns.

    rank_change > 0 means the stock moved UP (better rank number, smaller).
    compounded_delta_pct is today minus previous compounded return (percentage points).
    """
    out = current.copy()
    out["prev_rank"] = pd.NA
    out["rank_change"] = 0
    out["prev_compounded_return_pct"] = pd.NA
    out["compounded_delta_pct"] = 0.0
    out["is_new"] = False

    if previous is None or previous.empty or "ticker" not in previous.columns:
        return out

    prev = previous.drop_duplicates(subset="ticker").set_index("ticker")
    for idx, row in out.iterrows():
        ticker = row["ticker"]
        if ticker not in prev.index:
            out.at[idx, "is_new"] = True
            continue
        if "rank" in prev.columns:
            prev_rank = int(prev.at[ticker, "rank"])
            out.at[idx, "prev_rank"] = prev_rank
            out.at[idx, "rank_change"] = prev_rank - int(row["rank"])
        if "compounded_return_pct" in prev.columns:
            prev_ret = float(prev.at[ticker, "compounded_return_pct"])
            out.at[idx, "prev_compounded_return_pct"] = prev_ret
            out.at[idx, "compounded_delta_pct"] = float(row["compounded_return_pct"]) - prev_ret
    return out


def movers_summary(df: pd.DataFrame, top_n: int = 10) -> dict[str, pd.DataFrame]:
    empty = df.head(0)
    if "rank_change" not in df.columns:
        return {"climbers": empty, "fallers": empty}
    moved = df[df["rank_change"].fillna(0).astype(float) != 0]
    if moved.empty:
        return {"climbers": empty, "fallers": empty}
    up = moved[moved["rank_change"].astype(float) > 0]
    down = moved[moved["rank_change"].astype(float) < 0]
    climbers = up.sort_values(["rank_change", "compounded_return_pct"], ascending=[False, False]).head(top_n)
    fallers = down.sort_values(["rank_change", "compounded_return_pct"], ascending=[True, True]).head(top_n)
    return {"climbers": climbers, "fallers": fallers}
