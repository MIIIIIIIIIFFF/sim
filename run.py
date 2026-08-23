#!/usr/bin/env python3
"""Overnight Edge CLI, interactive wizard, and GUI launcher."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from overnight_edge import __version__
from overnight_edge.calendar import max_trading_days_available
from overnight_edge.constants import (
    DEFAULT_HOLD_COUNT,
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_TOP_N,
    DEFAULT_WORKERS,
)
from overnight_edge.paths import default_output_dir
from overnight_edge.pipeline import run_and_export
from overnight_edge.report import print_summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="overnight-edge",
        description=(
            "Classe les grandes capitalisations par rendement overnight composé au quotidien : "
            "achat au close 16:00 HE, vente à 09:29 HE pré-ouverture."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--gui", action="store_true", help="Ouvrir l'application bureautique interactive")
    parser.add_argument("--interactive", action="store_true", help="Demander les paramètres dans le terminal")
    parser.add_argument("--days", type=int, default=DEFAULT_HOLD_COUNT, help="Nuits de bourse (jours)")
    parser.add_argument(
        "--capital",
        type=float,
        default=DEFAULT_STARTING_CAPITAL,
        help="Capital de départ en USD (composé nuit après nuit)",
    )
    parser.add_argument("--top", type=int, default=DEFAULT_TOP_N, help="Top N valeurs à afficher")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="Threads de téléchargement parallèles")
    parser.add_argument("--output-dir", type=str, default="", help="Dossier de sortie")
    parser.add_argument("--tickers", type=str, default="", help="Tickers séparés par virgules (défaut : S&P 500)")
    parser.add_argument("--min-trades", type=int, default=None, help="Trades minimum (défaut : même que --days)")
    parser.add_argument("--no-html", action="store_true", help="Passer le rapport HTML")
    parser.add_argument("--quiet", action="store_true", help="Supprimer les tableaux console")
    return parser


def _ask(prompt: str, default: str) -> str:
    raw = input(f"{prompt} [{default}]: ").strip()
    return raw if raw else default


def interactive_settings(args: argparse.Namespace) -> argparse.Namespace:
    print()
    print("=" * 64)
    print("  OVERNIGHT EDGE  |  Scan interactif")
    print("  Achat 16:00 HE (close) -> vente 09:29 HE le lendemain matin")
    print("  Le profit est composé jour après jour (réinvesti chaque nuit)")
    print("=" * 64)
    print()
    args.days = int(_ask("Combien de nuits de bourse (jours) ?", str(args.days)))
    args.capital = float(_ask("Capital de départ en USD ?", str(int(args.capital))))
    args.tickers = _ask("Tickers (vide = S&P 500 complet)", args.tickers)
    args.workers = int(_ask("Téléchargements simultanés", str(args.workers)))
    args.top = int(_ask("Afficher le top N", str(args.top)))
    return args


def _validate(args: argparse.Namespace) -> None:
    max_days = max_trading_days_available()
    if args.days < 5 or args.days > max_days:
        raise SystemExit(f"Erreur : --days doit être entre 5 et {max_days}.")
    if args.capital <= 0:
        raise SystemExit("Erreur : --capital doit être positif.")
    if args.workers < 1 or args.workers > 32:
        raise SystemExit("Erreur : --workers doit être entre 1 et 32.")
    min_trades = args.min_trades if args.min_trades is not None else args.days
    if min_trades < 1 or min_trades > args.days:
        raise SystemExit("Erreur : --min-trades doit être entre 1 et --days.")
    args.min_trades = min_trades


def _progress(done: int, total: int) -> None:
    if done % 25 == 0 or done == total:
        print(f"  Progression : {done}/{total}")


def main() -> int:
    args = build_parser().parse_args()

    if args.gui:
        from app import launch_gui
        return launch_gui()

    if args.interactive:
        args = interactive_settings(args)

    _validate(args)
    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir()

    print(f"Overnight Edge v{__version__}")
    print("-" * 40)
    print("Stratégie : ACHAT 16:00 HE (close) -> VENTE 09:29 HE pré-ouverture")
    print("P&L :      composé nuit après nuit (réinvestissement complet)")
    print(f"Capital :  ${args.capital:,.2f} de départ")
    print(f"Fenêtre :  {args.days} nuits de détention")
    print("-" * 40)

    try:
        result, df, paths = run_and_export(
            hold_count=args.days,
            starting_capital=args.capital,
            workers=args.workers,
            top_n=args.top,
            min_trades=args.min_trades,
            tickers_csv=args.tickers,
            output_dir=output_dir,
            write_html=not args.no_html,
            on_progress=_progress,
        )
    except RuntimeError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    if result.skipped:
        print(f"\n{len(result.skipped)} ticker(s) ignoré(s).")
    if not args.quiet:
        print_summary(df, args.days, args.top)
        best = df.iloc[0]
        print(
            f"\nSi vous aviez commencé avec ${args.capital:,.2f} sur {best['ticker']} : "
            f"valeur finale ${best['ending_capital']:,.2f}  "
            f"(profit ${best['profit_usd']:,.2f}, {best['compounded_return_pct']:+.2f}% composé)"
        )

    print(f"\n{'-' * 40}")
    print("Exports :")
    print(f"  Classement   : {paths['csv_latest']}")
    print(f"  Journal trades: {paths['trades']}")
    print(f"  Manifeste    : {paths['manifest_latest']}")
    if not args.no_html:
        print(f"  Rapport HTML : {paths['html_latest']}")
    print(f"\nTerminé en {result.elapsed_seconds:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
