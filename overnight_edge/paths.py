"""User data locations: AppData when installed, project folder in development."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def application_dir() -> Path:
    """Folder that contains the EXE (frozen) or the project root (source)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """Writable location for daily history and reports (survives reinstalls)."""
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        root = Path.home() / ".overnight_edge"
    path = root / "OvernightEdge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> Path:
    path = user_data_dir() / "output"
    path.mkdir(parents=True, exist_ok=True)
    return path


def history_dir() -> Path:
    path = user_data_dir() / "history"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bars_cache_dir() -> Path:
    """Local 5-min bar cache. Accumulates over time so users can backtest
    further back than Yahoo's ~60-day 5-minute limit."""
    path = user_data_dir() / "bars_cache"
    path.mkdir(parents=True, exist_ok=True)
    return path
