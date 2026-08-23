"""Stock universe loading (S&P 500 large-cap constituents)."""

from __future__ import annotations

import pandas as pd
import requests

WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
GITHUB_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "master/data/constituents.csv"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MIN_CONSTITUENTS = 450


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper().replace(".", "-")


def _constituents_from_table(raw: pd.DataFrame) -> pd.DataFrame:
    if "Symbol" not in raw.columns:
        raise ValueError(f"S&P list missing Symbol column: {list(raw.columns)}")
    name_col = next((c for c in ("Security", "Name", "Company") if c in raw.columns), None)
    sector_col = next((c for c in ("GICS Sector", "Sector") if c in raw.columns), None)
    df = pd.DataFrame(
        {
            "ticker": raw["Symbol"].map(_normalize_symbol),
            "company": raw[name_col].astype(str) if name_col else raw["Symbol"].astype(str),
            "sector": raw[sector_col].astype(str) if sector_col else "",
        }
    )
    df = df.drop_duplicates(subset="ticker").reset_index(drop=True)
    df = df[df["ticker"].str.len() > 0]
    if len(df) < MIN_CONSTITUENTS:
        raise ValueError(f"S&P list too short ({len(df)} names; expected ~500)")
    return df


def _from_github() -> pd.DataFrame:
    response = requests.get(GITHUB_CSV_URL, headers=_HEADERS, timeout=30)
    response.raise_for_status()
    raw = pd.read_csv(pd.io.common.StringIO(response.text))
    return _constituents_from_table(raw)


def _from_wikipedia() -> pd.DataFrame:
    response = requests.get(WIKI_SP500_URL, headers=_HEADERS, timeout=30)
    response.raise_for_status()
    table = pd.read_html(response.text)[0]
    return _constituents_from_table(table)


def fetch_sp500_universe() -> pd.DataFrame:
    """
    Return S&P 500 constituents with ticker and company name.

    The S&P 500 is the standard proxy for the largest ~500 US-listed companies
    by float-adjusted market capitalization.
    """
    errors: list[str] = []
    for loader, label in ((_from_github, "GitHub"), (_from_wikipedia, "Wikipedia")):
        try:
            return loader()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: {exc}")
    raise RuntimeError(
        "Could not download the S&P 500 list. Check internet access. " + " | ".join(errors)
    )


def parse_ticker_list(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in raw.split(","):
        norm = _normalize_symbol(t)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out
