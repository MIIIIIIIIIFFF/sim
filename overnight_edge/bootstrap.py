"""Process startup for source runs and the frozen Windows EXE."""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def prepare_runtime() -> Path:
    """
    Make the frozen EXE safe on any PC:

    * writable working directory (not Program Files)
    * crash log under AppData
    * cache dir for Yahoo Finance
    """
    from overnight_edge.paths import user_data_dir

    data = user_data_dir()
    cache = data / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("XDG_CACHE_HOME", str(cache))
    os.environ.setdefault("YFINANCE_CACHE_DIR", str(cache / "yfinance"))
    try:
        os.chdir(data)
    except OSError:
        pass
    return data


def log_crash(exc: BaseException) -> Path:
    from overnight_edge.paths import user_data_dir

    path = user_data_dir() / "crash.log"
    path.write_text(
        "".join(
            traceback.format_exception(
                type(exc) if isinstance(exc, BaseException) else RuntimeError,
                exc if isinstance(exc, BaseException) else RuntimeError(repr(exc)),
                getattr(exc, "__traceback__", None) if isinstance(exc, BaseException) else None,
            )
        ),
        encoding="utf-8",
    )
    return path


def install_exception_hook() -> None:
    def _hook(exc_type, exc, tb) -> None:
        try:
            path = log_crash(exc)
            sys.stderr.write(f"Overnight Edge crashed. Details: {path}\n")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook
