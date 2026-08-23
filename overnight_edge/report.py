"""Report generation: console summary, CSV, HTML dashboard, and scan manifest."""

from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from tabulate import tabulate

from overnight_edge import __version__
from overnight_edge.constants import EASTERN

DISPLAY_COLUMNS = [
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
    "rank_change",
    "compounded_delta_pct",
]


def enrich_with_metadata(rankings: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    merged = rankings.merge(universe, on="ticker", how="left")
    merged["company"] = merged["company"].fillna("N/A")
    merged["sector"] = merged["sector"].fillna("N/A")
    return merged


def _format_pct(value: float) -> str:
    return f"{value:.2f}%"


def _format_profit_factor(value: float) -> str:
    return f"{value:.2f}" if value < 100 else "inf"


def print_summary(result_df: pd.DataFrame, hold_count: int, top_n: int) -> None:
    print(f"\n{'=' * 72}")
    print("  SCAN OVERNIGHT EDGE - RÉSUMÉ DES RÉSULTATS")
    print("  Stratégie : ACHAT au close 16:00 HE  |  VENTE 09:29 HE pré-ouverture")
    print(f"  Fenêtre :   {hold_count} dernières nuits de détention par valeur")
    print(f"{'=' * 72}\n")

    cols = [c for c in DISPLAY_COLUMNS if c in result_df.columns]
    top = result_df.head(top_n)[cols].copy()
    bottom = result_df.tail(min(10, len(result_df)))[cols].copy()

    for frame in (top, bottom):
        for col in ("compounded_return_pct", "avg_overnight_return_pct", "win_rate_pct", "max_drawdown_pct"):
            if col in frame.columns:
                frame[col] = frame[col].map(_format_pct)
        if "ending_capital" in frame.columns:
            frame["ending_capital"] = frame["ending_capital"].map(lambda x: f"${x:,.2f}")
        if "profit_usd" in frame.columns:
            frame["profit_usd"] = frame["profit_usd"].map(lambda x: f"${x:,.2f}")
        if "rank_change" in frame.columns:
            frame["rank_change"] = frame["rank_change"].map(
                lambda x: f"{int(x):+d}" if pd.notna(x) else "—"
            )
        if "compounded_delta_pct" in frame.columns:
            frame["compounded_delta_pct"] = frame["compounded_delta_pct"].map(
                lambda x: f"{x:+.2f} pp" if pd.notna(x) else "—"
            )

    print(f"Top {min(top_n, len(result_df))} performances :\n")
    print(tabulate(top, headers="keys", tablefmt="simple", showindex=False))
    print(f"\n{len(bottom)} moins performantes :\n")
    print(tabulate(bottom, headers="keys", tablefmt="simple", showindex=False))


def save_csv(df: pd.DataFrame, path: Path) -> None:
    export = df.drop(columns=["_trade_log"], errors="ignore")
    export.to_csv(path, index=False, float_format="%.4f", encoding="utf-8-sig")


def save_trade_logs(df: pd.DataFrame, path: Path, top_n: int = 10) -> None:
    rows: list[dict] = []
    for _, row in df.head(top_n).iterrows():
        log = row.get("_trade_log")
        if not log:
            continue
        for trade in log:
            rows.append(
                {
                    "ticker": row["ticker"],
                    "company": row.get("company", ""),
                    **trade,
                }
            )
    if rows:
        pd.DataFrame(rows).to_csv(path, index=False, float_format="%.4f", encoding="utf-8-sig")


def save_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def build_manifest(
    df: pd.DataFrame,
    *,
    hold_count: int,
    lookback_calendar_days: int,
    universe_label: str,
    elapsed_seconds: float,
    skipped: list[str],
    scan_timestamp: str,
    min_trades_required: int,
    starting_capital: float = 10_000.0,
) -> dict[str, Any]:
    positive = int((df["compounded_return_pct"] > 0).sum())
    best = df.iloc[0]
    return {
        "tool": "Overnight Edge Scanner",
        "version": __version__,
        "scan_timestamp_utc": scan_timestamp,
        "strategy": {
            "entry": "Buy at 16:00 ET regular-session close (last 5m bar 09:30-16:00)",
            "exit": "Sell at 09:29 ET pre-market (last 5m bar 04:00-09:29, typically 09:25 bar)",
            "exit_fallback": "09:30 ET opening print when pre-market data is unavailable",
            "ranking_metric": "Day-to-day compounded return: equity *= (1 + nightly_return)",
            "compounding": "100% of capital is reinvested after every overnight hold",
            "data_source": "Yahoo Finance 5-minute OHLC bars with extended hours",
            "bar_convention": "Timestamps mark the START of each 5-minute bucket",
        },
        "parameters": {
            "universe": universe_label,
            "hold_count_trading_days": hold_count,
            "lookback_calendar_days": lookback_calendar_days,
            "min_trades_required": min_trades_required,
            "starting_capital": starting_capital,
            "stocks_analyzed": len(df),
            "stocks_skipped": len(skipped),
        },
        "summary": {
            "profitable_stocks": positive,
            "profitable_pct": round(positive / len(df) * 100, 1) if len(df) else 0,
            "median_compounded_return_pct": round(float(df["compounded_return_pct"].median()), 4),
            "top_performer": {
                "ticker": best["ticker"],
                "company": best.get("company", ""),
                "compounded_return_pct": round(float(best["compounded_return_pct"]), 4),
                "ending_capital": round(float(best.get("ending_capital", 0)), 2),
                "profit_usd": round(float(best.get("profit_usd", 0)), 2),
            },
        },
        "elapsed_seconds": round(elapsed_seconds, 2),
        "skipped_tickers": skipped,
    }


def _fmt_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _row_class(value: float) -> str:
    if value >= 10:
        return "positive-strong"
    if value > 0:
        return "positive"
    if value <= -10:
        return "negative-strong"
    return "negative"


def _esc(value: Any) -> str:
    return html.escape(str(value))


def generate_html_report(
    df: pd.DataFrame,
    path: Path,
    *,
    hold_count: int,
    lookback_calendar_days: int,
    universe_label: str,
    elapsed_seconds: float,
    skipped_count: int,
    starting_capital: float = 10_000.0,
    previous_scan_date: str | None = None,
    scan_date: datetime | None = None,
) -> None:
    scan_date = scan_date or datetime.now(timezone.utc).astimezone(EASTERN)
    top = df.head(25)
    bottom = df.tail(10)

    def table_rows(frame: pd.DataFrame) -> str:
        lines = []
        for _, r in frame.iterrows():
            ret = r["compounded_return_pct"]
            pf = r.get("profit_factor", 0)
            try:
                pf_str = f"{float(pf):.2f}" if float(pf) < 100 else "inf"
            except (TypeError, ValueError):
                pf_str = "—"
            ending = float(r.get("ending_capital", 0) or 0)
            profit = float(r.get("profit_usd", 0) or 0)
            rank_ch = r.get("rank_change", 0)
            ret_ch = r.get("compounded_delta_pct", 0)
            try:
                rank_ch_s = f"{int(rank_ch):+d}" if pd.notna(rank_ch) else "—"
            except (TypeError, ValueError):
                rank_ch_s = "—"
            try:
                ret_ch_s = f"{float(ret_ch):+.2f} pp" if pd.notna(ret_ch) else "—"
            except (TypeError, ValueError):
                ret_ch_s = "—"
            rank_cls = _row_class(float(rank_ch) if pd.notna(rank_ch) else 0)
            ret_cls = _row_class(float(ret_ch) if pd.notna(ret_ch) else 0)
            lines.append(
                "<tr>"
                f"<td>{int(r['rank'])}</td>"
                f"<td><strong>{_esc(r['ticker'])}</strong></td>"
                f"<td>{_esc(r.get('company', 'N/A'))}</td>"
                f"<td>{_esc(r.get('sector', 'N/A'))}</td>"
                f'<td class="{_row_class(ret)}">{_fmt_pct(ret)}</td>'
                f'<td class="{rank_cls}">{rank_ch_s}</td>'
                f'<td class="{ret_cls}">{ret_ch_s}</td>'
                f'<td>${ending:,.2f}</td>'
                f'<td class="{_row_class(profit)}">${profit:,.2f}</td>'
                f"<td>{float(r['avg_overnight_return_pct']):.2f}%</td>"
                f"<td>{float(r['win_rate_pct']):.1f}%</td>"
                f"<td>{float(r['max_drawdown_pct']):.2f}%</td>"
                f"<td>{pf_str}</td>"
                f"<td>{int(r['trades'])}</td>"
                "</tr>"
            )
        return "\n".join(lines)

    positive = int((df["compounded_return_pct"] > 0).sum())
    median_ret = df["compounded_return_pct"].median()
    best = df.iloc[0]
    date_range = ""
    if "first_trade_date" in df.columns and "last_trade_date" in df.columns:
        date_range = (
            f"{df['first_trade_date'].min()} to {df['last_trade_date'].max()}"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Rapport Overnight Edge - {scan_date:%Y-%m-%d}</title>
  <style>
    :root {{
      --bg: #0b0f14; --card: #151b24; --border: #263244;
      --text: #e8edf4; --muted: #8b9cb3; --accent: #3b82f6;
      --green: #22c55e; --red: #ef4444;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg);
            color: var(--text); line-height: 1.55; padding: 2rem; }}
    .container {{ max-width: 1240px; margin: 0 auto; }}
    h1 {{ font-size: 1.85rem; font-weight: 700; letter-spacing: -0.02em; }}
    .subtitle {{ color: var(--muted); margin: 0.5rem 0 2rem; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
              gap: 1rem; margin-bottom: 2rem; }}
    .card {{ background: var(--card); border: 1px solid var(--border);
             border-radius: 12px; padding: 1.25rem; }}
    .card .label {{ font-size: 0.72rem; color: var(--muted); text-transform: uppercase;
                    letter-spacing: 0.06em; }}
    .card .value {{ font-size: 1.45rem; font-weight: 600; margin-top: 0.3rem; }}
    section {{ background: var(--card); border: 1px solid var(--border);
               border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }}
    h2 {{ font-size: 1.05rem; margin-bottom: 1rem; color: var(--accent); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th, td {{ padding: 0.65rem 0.75rem; text-align: left; border-bottom: 1px solid var(--border); }}
    th {{ color: var(--muted); font-weight: 500; font-size: 0.72rem; text-transform: uppercase; }}
    tbody tr:hover {{ background: rgba(59, 130, 246, 0.07); }}
    .positive-strong {{ color: #4ade80; font-weight: 600; }}
    .positive {{ color: var(--green); }}
    .negative {{ color: #f87171; }}
    .negative-strong {{ color: var(--red); font-weight: 600; }}
    .methodology {{ color: var(--muted); font-size: 0.86rem; padding-left: 1.2rem; }}
    .methodology li {{ margin-bottom: 0.45rem; }}
    .flow {{ display: flex; align-items: center; gap: 0.75rem; flex-wrap: wrap;
             margin: 1rem 0; font-size: 0.95rem; }}
    .flow .step {{ background: #1e2a3d; border: 1px solid var(--border);
                   border-radius: 8px; padding: 0.6rem 1rem; }}
    .flow .arrow {{ color: var(--muted); }}
    footer {{ margin-top: 2rem; color: var(--muted); font-size: 0.78rem; }}
  </style>
</head>
<body>
  <div class="container">
    <h1>Scanner Overnight Edge</h1>
    <p class="subtitle">
      Backtest de stratégie overnight sur grandes capitalisations &middot;
      Généré le {_esc(scan_date.strftime('%d/%m/%Y à %H:%M'))}
      {f' &middot; Vs scan précédent : {_esc(previous_scan_date)}' if previous_scan_date else ' &middot; Premier snapshot quotidien enregistré (relancez demain pour les variations)'}
    </p>

    <div class="cards">
      <div class="card"><div class="label">Univers</div><div class="value">{_esc(universe_label)}</div></div>
      <div class="card"><div class="label">Valeurs classées</div><div class="value">{len(df)}</div></div>
      <div class="card"><div class="label">Fenêtre de détention</div><div class="value">{hold_count} jours de bourse</div></div>
      <div class="card"><div class="label">Données (lookback)</div><div class="value">{lookback_calendar_days} jours calendaires</div></div>
      <div class="card"><div class="label">Rentables</div><div class="value">{positive} ({positive/len(df)*100:.0f}%)</div></div>
      <div class="card"><div class="label">Rendement médian</div><div class="value">{_fmt_pct(median_ret)}</div></div>
      <div class="card"><div class="label">Capital de départ</div><div class="value">${starting_capital:,.0f}</div></div>
      <div class="card"><div class="label">Meilleure valeur finale</div><div class="value">${float(best.get('ending_capital', 0)):,.0f}</div></div>
      <div class="card"><div class="label">Meilleure performance</div><div class="value">{_esc(best['ticker'])} {_fmt_pct(best['compounded_return_pct'])}</div></div>
    </div>

    <section>
      <h2>Déroulement de la stratégie</h2>
      <div class="flow">
        <span class="step"><strong>Jour T &mdash; 16:00 HE</strong><br>Achat au close du marché</span>
        <span class="arrow">&rarr;</span>
        <span class="step"><strong>Détention overnight</strong><br>Après-close, after-hours, pré-ouverture</span>
        <span class="arrow">&rarr;</span>
        <span class="step"><strong>Jour T+1 &mdash; 09:29 HE</strong><br>Vente avant l'ouverture</span>
        <span class="arrow">&rarr;</span>
        <span class="step"><strong>Répéter chaque jour</strong><br>Composition sur {hold_count} séances</span>
      </div>
      <ul class="methodology">
        <li><strong>Entrée (Jour T, 16:00 HE) :</strong> Close de la dernière barre 5 minutes entre 09:30 et 16:00 (généralement la barre 16:00 ou 15:55).</li>
        <li><strong>Sortie (Jour T+1, 09:29 HE) :</strong> Close de la dernière barre 5 minutes entre 04:00 et 09:29 (généralement la barre 09:25 couvrant 09:25-09:29:59).</li>
        <li><strong>Horodatage des barres</strong> = début de chaque intervalle de 5 minutes (convention Yahoo Finance).</li>
        <li><strong>Composition :</strong> Après chaque nuit, 100 % du capital est réinvesti. Valeur finale = ${starting_capital:,.0f} &times; produit(1 + rendement nocturne). Le classement utilise ce chiffre composé, pas la somme des pourcentages journaliers.</li>
        <li><strong>Lookback :</strong> {lookback_calendar_days} jours calendaires téléchargés pour capturer {hold_count} paires de jours de bourse (week-ends/fériés exclus).</li>
      </ul>
    </section>

    <section>
      <h2>Top 25 performances</h2>
      <table>
        <thead><tr>
          <th>#</th><th>Ticker</th><th>Société</th><th>Secteur</th>
          <th>Composé</th><th>Δ Rang</th><th>Δ Composé</th>
          <th>Capital final $</th><th>Profit $</th>
          <th>Moy/Nuit</th><th>Taux de réussite</th>
          <th>Tirage max</th><th>Facteur de profit</th><th>Nuits</th>
        </tr></thead>
        <tbody>{table_rows(top)}</tbody>
      </table>
    </section>

    <section>
      <h2>10 moins performantes</h2>
      <table>
        <thead><tr>
          <th>#</th><th>Ticker</th><th>Société</th><th>Secteur</th>
          <th>Composé</th><th>Δ Rang</th><th>Δ Composé</th>
          <th>Capital final $</th><th>Profit $</th>
          <th>Moy/Nuit</th><th>Taux de réussite</th>
          <th>Tirage max</th><th>Facteur de profit</th><th>Nuits</th>
        </tr></thead>
        <tbody>{table_rows(bottom)}</tbody>
      </table>
    </section>

    <section>
      <h2>Univers complet (recherche) — variations au quotidien</h2>
      <p class="methodology" style="padding-left:0;margin-bottom:0.8rem">
        Δ Rang : positif = la valeur a <em>monté</em> vs le scan précédent.
        Δ Composé = variation du rendement overnight composé (points de pourcentage).
      </p>
      <input id="q" type="search" placeholder="Filtrer par ticker, société ou secteur..."
             style="width:100%;margin-bottom:0.8rem;padding:0.6rem 0.8rem;border-radius:8px;border:1px solid var(--border);background:#0f1720;color:var(--text);">
      <div style="overflow-x:auto;max-height:640px;overflow-y:auto;">
      <table id="all">
        <thead><tr>
          <th>#</th><th>Ticker</th><th>Société</th><th>Secteur</th>
          <th>Composé</th><th>Δ Rang</th><th>Δ Composé</th>
          <th>Capital final $</th><th>Profit $</th>
          <th>Moy/Nuit</th><th>Taux de réussite</th>
          <th>Tirage max</th><th>Facteur de profit</th><th>Nuits</th>
        </tr></thead>
        <tbody>{table_rows(df)}</tbody>
      </table>
      </div>
    </section>

    <section>
      <h2>Méthodologie et limites</h2>
      <ul class="methodology">
        <li>Univers : constituants du S&P 500 (~500 plus grandes capitalisations américaines).</li>
        <li>Prix dérivés des barres 5 minutes ; une exécution réelle aux horodatages exacts peut différer.</li>
        <li>Hypothèse de remplissage instantané, sans commissions, slippage, spread ni coût d'emprunt.</li>
        <li>Les titres avec moins de {hold_count} nuits complètes dans la fenêtre sont exclus.</li>
        <li>Les performances passées ne garantissent pas les résultats futurs. Outil de recherche uniquement.</li>
        <li>Scan terminé en {elapsed_seconds:.1f}s. {skipped_count} ticker(s) ignoré(s).</li>
      </ul>
    </section>

    <footer>Overnight Edge v{__version__} - Outil de recherche. Ceci n'est pas un conseil en investissement. La composition suppose un réinvestissement complet chaque nuit, sans coûts. Les snapshots quotidiens utilisent la date calendaire de l'heure de New York (Eastern).</footer>
  </div>
  <script>
    document.getElementById('q').addEventListener('input', function () {{
      const q = this.value.toLowerCase();
      document.querySelectorAll('#all tbody tr').forEach(function (tr) {{
        tr.style.display = tr.innerText.toLowerCase().indexOf(q) >= 0 ? '' : 'none';
      }});
    }});
  </script>
</body>
</html>"""

    path.write_text(html_doc, encoding="utf-8")
