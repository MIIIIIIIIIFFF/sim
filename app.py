"""Overnight Edge desktop application — daily S&P 500 overnight compounder."""

from __future__ import annotations

import os
import sys
import threading
import webbrowser
from pathlib import Path
from tkinter import END, DoubleVar, StringVar, Tk, ttk, messagebox, scrolledtext

from overnight_edge.bootstrap import install_exception_hook, log_crash, prepare_runtime
from overnight_edge import __version__
from overnight_edge.calendar import max_trading_days_available
from overnight_edge.celebration import show_birthday_then
from overnight_edge.constants import (
    DEFAULT_HOLD_COUNT,
    DEFAULT_STARTING_CAPITAL,
    DEFAULT_WORKERS,
)
from overnight_edge.history import (
    attach_variance,
    list_snapshot_dates,
    load_previous_snapshot,
    load_snapshot,
    movers_summary,
)
from overnight_edge.paths import default_output_dir, user_data_dir

FONT_FAMILY = "Segoe UI"
FONT_SIZE_DEFAULT = 11
FONT_SIZE_MIN = 8
FONT_SIZE_MAX = 20


def _apply_font_size(size: int, root: Tk | None = None) -> None:
    """Apply a base font size to all standard Tk/ttk fonts (and thus all widgets)."""
    from tkinter import font as tkfont
    if root is not None:
        try:
            root.option_add("*Font", (FONT_FAMILY, size))
        except Exception:
            pass
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        try:
            tkfont.nametofont(name).configure(family=FONT_FAMILY, size=size)
        except Exception:
            pass
    # Treeview uses a named font in some themes; force it to follow the base size.
    try:
        tkfont.nametofont("TkDefaultFont").configure(size=size)
    except Exception:
        pass


def _watchlist_tickers(df, search: str = "", sort_col: str = "rank", sort_desc: bool = False) -> list[str]:
    """Ordered ticker symbols from a ranking DataFrame for a TradingView watchlist."""
    if df is None or df.empty:
        return []
    q = (search or "").strip().lower()
    view = df
    if q:
        mask = (
            view["ticker"].astype(str).str.lower().str.contains(q, na=False)
            | view["company"].astype(str).str.lower().str.contains(q, na=False)
            | view["sector"].astype(str).str.lower().str.contains(q, na=False)
        )
        view = view[mask]
    key_map = {
        "rank": "rank",
        "delta_rank": "rank_change",
        "ticker": "ticker",
        "company": "company",
        "sector": "sector",
        "compounded": "compounded_return_pct",
        "delta_ret": "compounded_delta_pct",
        "ending": "ending_capital",
        "profit": "profit_usd",
        "avg": "avg_overnight_return_pct",
        "win": "win_rate_pct",
        "dd": "max_drawdown_pct",
        "trades": "trades",
    }
    col = key_map.get(sort_col, "rank")
    ordered = view.sort_values(col if col in view.columns else "rank", ascending=not sort_desc)
    return [str(t).strip().upper() for t in ordered["ticker"].tolist() if str(t).strip()]

COLUMNS = (
    "rank", "delta_rank", "ticker", "company", "sector",
    "compounded", "delta_ret", "ending", "profit", "avg", "win", "dd", "trades",
)
HEADINGS = {
    "rank": "#",
    "delta_rank": "Δ Rang",
    "ticker": "Ticker",
    "company": "Société",
    "sector": "Secteur",
    "compounded": "Composé %",
    "delta_ret": "Δ vs veille",
    "ending": "Capital final $",
    "profit": "Profit $",
    "avg": "Moy/nuit",
    "win": "Gains %",
    "dd": "Tirage max",
    "trades": "Nuits",
}
WIDTHS = {
    "rank": 48, "delta_rank": 70, "ticker": 72, "company": 180, "sector": 150,
    "compounded": 100, "delta_ret": 110, "ending": 100, "profit": 95,
    "avg": 80, "win": 70, "dd": 75, "trades": 60,
}


def _equity_path(result, starting_capital: float = 10_000.0) -> list[float]:
    """Running compounded equity across a BacktestResult's trades."""
    equity = float(starting_capital)
    path = [equity]
    for t in result.trades:
        r = t.return_pct / 100.0
        equity = equity * (1.0 + r) if r > -1.0 else 0.0
        path.append(equity)
    return path


class OvernightEdgeApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(f"Overnight Edge  v{__version__}")
        self.root.geometry("1280x820")
        self.root.minsize(1020, 680)
        self._running = False
        self._html_path: Path | None = None
        self._output_dir: Path | None = default_output_dir()
        self._df = None
        self._sort_col = "rank"
        self._sort_desc = False
        self.font_size = FONT_SIZE_DEFAULT
        _apply_font_size(self.font_size, root)

        self.days = StringVar(value=str(DEFAULT_HOLD_COUNT))
        self.capital = StringVar(value=str(int(DEFAULT_STARTING_CAPITAL)))
        self.workers = StringVar(value=str(DEFAULT_WORKERS))
        self.tickers = StringVar(value="")
        self.search = StringVar(value="")
        self.status = StringVar(
            value="Lancez un scan quotidien du S&P 500. Laissez « Tickers » vide pour la liste complète."
        )
        self.progress = StringVar(value="0 / 0")
        self._pvar = DoubleVar(value=0)

        self._build()
        self.search.trace_add("write", lambda *_: self._refresh_table())
        self._load_saved_scan()

    def _build(self) -> None:
        pad = {"padx": 10, "pady": 5}

        header = ttk.Frame(self.root)
        header.pack(fill="x", **pad)
        ttk.Label(header, text="Overnight Edge", font=(FONT_FAMILY, int(18 * (self.font_size / FONT_SIZE_DEFAULT)) + 2, "bold")).pack(anchor="w")
        ttk.Label(
            header,
            text=(
                "Chaque jour de bourse : achat au close de 16:00 (HE), vente à 09:29 (HE) le lendemain matin. "
                "Le profit est composé nuit après nuit. Lancez le scan quotidiennement pour voir l'évolution du rang et du rendement vs la veille."
            ),
            wraplength=1240,
        ).pack(anchor="w")

        form = ttk.LabelFrame(self.root, text="Scan quotidien")
        form.pack(fill="x", **pad)
        row1 = ttk.Frame(form)
        row1.pack(fill="x", padx=8, pady=6)
        self._labeled_entry(row1, "Nuits de bourse (jours)", self.days, 8)
        self._labeled_entry(row1, "Capital de départ ($)", self.capital, 12)
        self._labeled_entry(row1, "Téléchargements simultanés", self.workers, 6)
        ttk.Label(row1, text="Tickers (vide = S&P 500 complet)").pack(side="left", padx=(16, 4))
        ttk.Entry(row1, textvariable=self.tickers, width=42).pack(side="left", fill="x", expand=True)

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.run_btn = ttk.Button(actions, text="Lancer le scan du jour (S&P 500)", command=self._on_run)
        self.run_btn.pack(side="left")
        ttk.Button(actions, text="Ouvrir le rapport HTML", command=self._open_html).pack(side="left", padx=6)
        ttk.Button(actions, text="Ouvrir le dossier des rapports", command=self._open_folder).pack(side="left")
        ttk.Button(actions, text="Copier la Watchlist (TradingView)", command=self._copy_watchlist).pack(side="left", padx=6)

        font_box = ttk.Frame(actions)
        font_box.pack(side="right")
        ttk.Label(font_box, text="Police :").pack(side="left", padx=(0, 4))
        ttk.Button(font_box, text="A−", width=3, command=self._font_smaller).pack(side="left")
        self.font_label = StringVar(value=f"{self.font_size} pt")
        ttk.Label(font_box, textvariable=self.font_label, width=8).pack(side="left", padx=4)
        ttk.Button(font_box, text="A+", width=3, command=self._font_bigger).pack(side="left")
        ttk.Label(actions, textvariable=self.progress).pack(side="right", padx=(12, 0))

        ttk.Progressbar(self.root, mode="determinate", maximum=100, variable=self._pvar).pack(
            fill="x", padx=10
        )
        ttk.Label(self.root, textvariable=self.status).pack(anchor="w", padx=12)

        filter_row = ttk.Frame(self.root)
        filter_row.pack(fill="x", padx=10, pady=(4, 0))
        ttk.Label(filter_row, text="Rechercher dans la liste").pack(side="left")
        ttk.Entry(filter_row, textvariable=self.search, width=40).pack(side="left", padx=8)
        ttk.Label(
            filter_row,
            text="Δ Rang > 0 = montée vs le dernier scan enregistré.  Δ vs veille = variation du % composé.",
        ).pack(side="left", padx=12)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=6)

        rank_tab = ttk.Frame(notebook)
        movers_tab = ttk.Frame(notebook)
        stock_tab = ttk.Frame(notebook)
        log_tab = ttk.Frame(notebook)
        notebook.add(rank_tab, text="Classement complet du S&P 500")
        notebook.add(movers_tab, text="Plus grands mouvements au quotidien")
        notebook.add(stock_tab, text="Analyse d'une valeur")
        notebook.add(log_tab, text="Journal")

        self.tree = self._make_tree(rank_tab)
        self.movers_up = self._make_tree(self._labeled(movers_tab, "Plus fortes montées de rang"))
        self.movers_down = self._make_tree(self._labeled(movers_tab, "Plus fortes chutes de rang"))

        self._build_stock_tab(stock_tab)

        self.log = scrolledtext.ScrolledText(log_tab, height=8, wrap="word")
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_stock_tab(self, parent) -> None:
        top = ttk.LabelFrame(parent, text="Choisissez une valeur et une période — recalculé à partir des données en direct")
        top.pack(fill="x", padx=6, pady=6)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text="Ticker").pack(side="left", padx=(8, 4))
        self.stock_ticker = StringVar(value="")
        ttk.Entry(row, textvariable=self.stock_ticker, width=10).pack(side="left", padx=4)

        per = ttk.Frame(row)
        per.pack(side="left", padx=10)
        boxes = ttk.Frame(per)
        boxes.pack(side="left")
        ttk.Label(boxes, text="Période").pack(side="left", padx=(0, 6))
        self.stock_period = StringVar(value="30 dernières nuits (auto)")
        combo = ttk.Combobox(
            boxes,
            textvariable=self.stock_period,
            values=(
                "5 dernières nuits",
                "10 dernières nuits",
                "15 dernières nuits",
                "30 dernières nuits (auto)",
                "Tout l'historique",
            ),
            state="readonly",
            width=26,
        )
        combo.pack(side="left")

        ttk.Label(row, text="Du").pack(side="left", padx=(8, 2))
        self.stock_from = StringVar(value="")
        ttk.Entry(row, textvariable=self.stock_from, width=11).pack(side="left")
        ttk.Label(row, text="Au").pack(side="left", padx=(8, 2))
        self.stock_to = StringVar(value="")
        ttk.Entry(row, textvariable=self.stock_to, width=11).pack(side="left")
        ttk.Label(row, text="(AAAA-MM-JJ)", foreground="#94a3b8").pack(side="left", padx=6)

        self.stock_btn = ttk.Button(row, text="Analyser", command=self._on_stock_analyze)
        self.stock_btn.pack(side="left", padx=12)

        result = ttk.Frame(parent)
        result.pack(fill="x", padx=6, pady=4)
        self.stock_summary = StringVar(value="Entrez un ticker, puis cliquez sur Analyser.")
        ttk.Label(result, textvariable=self.stock_summary, wraplength=1180, foreground="#0f172a").pack(
            anchor="w", fill="x"
        )

        meta_box = ttk.LabelFrame(parent, text="Transaction par transaction")
        meta_box.pack(fill="x", padx=6, pady=4)
        self.stock_meta = StringVar(
            value="Chaque ligne = une nuit de détention : achat (close) -> vente (pré-ouverture). Le capital se compose nuit après nuit."
        )
        ttk.Label(meta_box, textvariable=self.stock_meta, wraplength=1200, foreground="#475569").pack(
            anchor="w", fill="x"
        )

        self.stock_table = ttk.Frame(parent)
        self.stock_table.pack(fill="both", expand=True, padx=6, pady=6)

        cols = ("buy_date", "sell_date", "buy", "sell", "ret", "source")
        heads = {
            "buy_date": "Achat (16:00 close)",
            "sell_date": "Vente (09:29)",
            "buy": "Achat $",
            "sell": "Vente $",
            "ret": "Rendement %",
            "source": "Source du prix",
        }
        widths = {"buy_date": 118, "sell_date": 118, "buy": 90, "sell": 90, "ret": 92, "source": 210}
        tree = ttk.Treeview(self.stock_table, columns=cols, show="headings", height=12)
        for c in cols:
            tree.heading(c, text=heads[c])
            tree.column(c, width=widths[c], anchor="w" if c == "source" else "center")
        yscroll = ttk.Scrollbar(self.stock_table, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        tree.tag_configure("pos", foreground="#15803d")
        tree.tag_configure("neg", foreground="#b91c1c")
        self.stock_tree = tree

        compare_box = ttk.LabelFrame(parent, text="Overnight vs Intraday vs Buy & Hold — même période, même capital")
        compare_box.pack(fill="x", padx=6, pady=4)
        self.strategy_meta = StringVar(
            value="Cliquez sur Analyser pour comparer les trois stratégies sur la même période et le même capital de départ."
        )
        ttk.Label(compare_box, textvariable=self.strategy_meta, wraplength=1200, foreground="#475569").pack(
            anchor="w", fill="x"
        )
        scols = ("strategy", "settle", "compounded", "win", "dd", "trades", "dates", "profit")
        sheads = {
            "strategy": "Stratégie",
            "settle": "Capital final $",
            "compounded": "Composé %",
            "win": "Gains %",
            "dd": "Tirage max %",
            "trades": "Nuits / Jours",
            "dates": "Période",
            "profit": "Profit $",
        }
        swidths = {
            "strategy": 120, "settle": 110, "compounded": 110, "win": 90,
            "dd": 100, "trades": 90, "dates": 180, "profit": 110,
        }
        self.strategy_tree = ttk.Treeview(compare_box, columns=scols, show="headings", height=3)
        for c in scols:
            self.strategy_tree.heading(c, text=sheads[c])
            self.strategy_tree.column(c, width=swidths[c], anchor="w" if c in ("strategy", "dates") else "center")
        self.strategy_tree.tag_configure("best", background="#f0fdf4")
        self.strategy_tree.tag_configure("pos", foreground="#15803d")
        self.strategy_tree.tag_configure("neg", foreground="#b91c1c")
        self.strategy_tree.pack(fill="x", padx=6, pady=2)

    def _on_stock_analyze(self) -> None:
        ticker = self.stock_ticker.get().strip().upper()
        if not ticker:
            self.stock_summary.set("Entrez un ticker (ex. NVDA), puis cliquez sur Analyser.")
            return
        # Read all Tk variables on the main thread (Tcl isn't thread-safe).
        period = self.stock_period.get()
        try:
            auto_holds = int(self.days.get().strip())
        except ValueError:
            auto_holds = 30
        raw_from = self.stock_from.get().strip()
        raw_to = self.stock_to.get().strip()
        self.stock_btn.configure(state="disabled")
        self.stock_summary.set(f"Téléchargement de {ticker} ...")
        threading.Thread(
            target=self._stock_worker,
            args=(ticker, period, auto_holds, raw_from, raw_to),
            daemon=True,
        ).start()

    def _stock_worker(
        self, ticker: str, period: str, auto_holds: int, raw_from: str, raw_to: str
    ) -> None:
        try:
            from datetime import date
            from overnight_edge.data import download_intraday_bars
            from overnight_edge.strategy import compare_strategies

            lookback = 60
            max_trades = None
            if period == "5 dernières nuits":
                max_trades = 5
            elif period == "10 dernières nuits":
                max_trades = 10
            elif period == "15 dernières nuits":
                max_trades = 15
            elif period == "30 dernières nuits (auto)":
                # Match the main scan exactly so per-stock numbers are comparable.
                from overnight_edge.calendar import calendar_days_for_trading_days
                lookback = calendar_days_for_trading_days(auto_holds)
                max_trades = auto_holds

            start = end = None
            if raw_from or raw_to:
                try:
                    if raw_from:
                        start = date.fromisoformat(raw_from)
                    if raw_to:
                        end = date.fromisoformat(raw_to)
                except ValueError:
                    self.root.after(
                        0,
                        lambda: self._stock_done("Les dates doivent être au format AAAA-MM-JJ (ex. 2026-08-01)."),
                    )
                    return
                if start is not None and end is not None and start > end:
                    self.root.after(
                        0,
                        lambda: self._stock_done("« Du » doit être antérieur ou égal à « Au »."),
                    )
                    return
                # If the user's bracket exceeds Yahoo's 5-minute window, grow
                # the lookback so the daily fallback kicks in for the older part.
                if start is not None and end is not None:
                    span = (end - start).days
                    if span > lookback:
                        lookback = span + 10

            from overnight_edge.data import download_intraday_cached
            bars, source = download_intraday_cached(ticker, lookback)
            start_capital = float(
                self.capital.get().replace(",", "").replace("$", "").strip()
                if self.capital.get().strip()
                else DEFAULT_STARTING_CAPITAL
            )
            strategies = compare_strategies(
                bars,
                start_date=start,
                end_date=end,
                max_trades=max_trades,
                starting_capital=start_capital,
                source=source,
            )
            result = strategies["overnight"]
            if result is None:
                self.root.after(0, lambda t=ticker: self._stock_done(f"{t} : aucune nuit dans cette période."))
                return
            self.root.after(0, lambda r=result, s=strategies, src=source: self._stock_render(ticker, r, s, src))
        except BaseException as exc:  # noqa: BLE001
            self.root.after(0, lambda: self._stock_done(f"{ticker}: {exc}"))

    def _render_strategy_table(self, strategies: dict, source: str = "5m_precise") -> None:
        """Fill the Overnight vs Intraday vs Buy & Hold comparison table."""
        tree = self.strategy_tree
        for item in tree.get_children():
            tree.delete(item)

        names = {
            "overnight": "Overnight (16:00 → 09:29)",
            "intraday": "Intraday (09:30 → 16:00)",
            "buyhold": "Buy & Hold (open → close)",
        }
        # First pass: capture the best compounded outcome for highlighting.
        best: dict[str, float] = {}
        for key in ("overnight", "intraday", "buyhold"):
            res = strategies.get(key)
            if res is not None and res.trade_count:
                best[key] = float(res.compounded_return_pct)
        best_key = max(best, key=best.get) if best else None

        for key in ("overnight", "intraday", "buyhold"):
            res = strategies.get(key)
            if res is None or res.trade_count == 0:
                tree.insert("", END, values=(names[key], "—", "—", "—", "—", "—", "—", "—"))
                continue
            dates = (
                f"{res.first_trade_date} → {res.last_trade_date}"
                if res.first_trade_date and res.last_trade_date
                else "—"
            )
            values = (
                names[key],
                f"${res.ending_capital:,.2f}",
                f"{res.compounded_return_pct:+.2f}%",
                f"{res.win_rate_pct:.1f}%",
                f"{res.max_drawdown_pct:.2f}%",
                f"{res.trade_count}",
                dates,
                f"${res.profit_usd:,.2f}",
            )
            tags = ("best",) if key == best_key else ("pos" if res.compounded_return_pct >= 0 else "neg",)
            tree.insert("", END, values=values, tags=tags)

        if source == "daily_fallback":
            precision_note = (
                " ⚠ Approximatif : barres quotidiennes (pas de pré-marché). "
                "Achat = close du jour T, vente = open du jour T+1."
            )
        else:
            precision_note = ""
        self.strategy_meta.set(
            "Comparaison sur la même période et le même capital de départ. "
            "a) Overnight = tous les soirs 16:00 → 09:29 ; "
            "b) Intraday = chaque séance 09:30 → 16:00 ; "
            "c) Buy & Hold = achat au 1er open, vente au dernier close (un seul hold). "
            "Le composé réinvestit chaque nuit (ou chaque jour pour Intraday)."
            + precision_note
        )

    def _stock_render(self, ticker: str, result, strategies=None, source: str = "5m_precise") -> None:
        self.stock_btn.configure(state="normal")
        if strategies:
            self._render_strategy_table(strategies, source)
        self.stock_btn.configure(state="normal")
        n = len(result.trades)
        precision = (
            "Précis (barres 5 min)"
            if source == "5m_precise"
            else "Approximatif (barres quotidiennes — pas de pré-marché)"
        )
        head = (
            f"{ticker}  |  {n} nuits de détention  "
            f"({result.first_trade_date} → {result.last_trade_date})  ·  {precision}"
        )
        stats = (
            f"Composé : {result.compounded_return_pct:+.2f}%   "
            f"Moy/nuit : {result.avg_overnight_return_pct:+.3f}%   "
            f"Taux de réussite : {result.win_rate_pct:.0f}%   "
            f"Meilleure : {result.best_night_pct:+.2f}%   "
            f"Pire : {result.worst_night_pct:+.2f}%"
        )
        cap = (
            f"${result.starting_capital:,.0f} → ${result.ending_capital:,.2f} "
            f"(profit ${result.profit_usd:,.2f})"
        )
        self.stock_summary.set(f"{head}\n{stats}\n{cap}")
        self.stock_meta.set(
            "Capital composé (capital = capital × (1 + rendement), nuit après nuit) : "
            + " → ".join(f"${p:,.0f}" for p in _equity_path(result, result.starting_capital))
        )
        tree = self.stock_tree
        for item in tree.get_children():
            tree.delete(item)
        for t in result.trades:
            tag = "pos" if t.return_pct >= 0 else "neg"
            tree.insert(
                "",
                END,
                values=(
                    t.buy_date,
                    t.sell_date,
                    f"${t.buy_price:,.2f}",
                    f"${t.sell_price:,.2f}",
                    f"{t.return_pct:+.3f}%",
                    f"{t.buy_price_source} / {t.sell_price_source}",
                ),
                tags=(tag,),
            )

    def _stock_done(self, message: str) -> None:
        self.stock_btn.configure(state="normal")
        self.stock_summary.set(message)

    def _labeled(self, parent, title: str) -> None:
        box = ttk.LabelFrame(parent, text=title)
        box.pack(fill="both", expand=True, padx=6, pady=6)
        return box

    def _make_tree(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=COLUMNS, show="headings", height=14)
        for col in COLUMNS:
            tree.heading(col, text=HEADINGS[col], command=lambda c=col, t=tree: self._sort_by(c, t))
            tree.column(col, width=WIDTHS[col], anchor="w" if col in ("company", "sector") else "center")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=yscroll.set)
        tree.pack(side="left", fill="both", expand=True)
        yscroll.pack(side="right", fill="y")
        tree.tag_configure("up", foreground="#15803d")
        tree.tag_configure("down", foreground="#b91c1c")
        tree.tag_configure("new", foreground="#1d4ed8")
        return tree

    def _labeled_entry(self, parent, label: str, var: StringVar, width: int) -> None:
        box = ttk.Frame(parent)
        box.pack(side="left", padx=8)
        ttk.Label(box, text=label).pack(anchor="w")
        ttk.Entry(box, textvariable=var, width=width).pack(anchor="w")

    def _log(self, message: str) -> None:
        self.log.insert(END, message + "\n")
        self.log.see(END)

    def _load_saved_scan(self) -> None:
        dates = list_snapshot_dates()
        if not dates:
            self._log(f"Dossier de données : {user_data_dir()}")
            self._log("Aucun scan antérieur. Cliquez « Lancer le scan du jour (S&P 500) ».")
            return
        latest = dates[-1]
        df = load_snapshot(latest)
        if df is None:
            return
        prev, prev_date = load_previous_snapshot(latest)
        df = attach_variance(df, prev)
        self._df = df
        self._refresh_table()
        vs = f" vs {prev_date}" if prev_date else " (premier scan — relancez demain pour les variations)"
        self.status.set(f"Scan enregistré du {latest}{vs}. Relancez aujourd'hui pour actualiser.")
        html = default_output_dir() / "report_latest.html"
        if html.exists():
            self._html_path = html
        self._log(f"Chargé : {len(df)} valeurs depuis {latest}{vs}")

    def _row_values(self, r) -> tuple:
        def _num(v, default=0.0):
            try:
                f = float(v)
                if f != f:  # NaN guard
                    return default
                return f
            except (TypeError, ValueError):
                return default

        def rank_delta():
            v = r.get("rank_change", 0)
            try:
                return f"{int(v):+d}"
            except (TypeError, ValueError):
                return "—"

        def ret_delta():
            v = _num(r.get("compounded_delta_pct", 0))
            return f"{v:+.2f} pp"

        def rank():
            try:
                return int(_num(r["rank"], 0))
            except (TypeError, ValueError):
                return 0

        return (
            rank(),
            rank_delta(),
            r["ticker"],
            r.get("company", ""),
            r.get("sector", ""),
            f"{_num(r['compounded_return_pct']):+.2f}%",
            ret_delta(),
            f"${_num(r.get('ending_capital', 0)):,.2f}",
            f"${_num(r.get('profit_usd', 0)):,.2f}",
            f"{_num(r.get('avg_overnight_return_pct', 0)):.2f}%",
            f"{_num(r.get('win_rate_pct', 0)):.1f}%",
            f"{_num(r.get('max_drawdown_pct', 0)):.2f}%",
            int(_num(r.get("trades", 0))),
        )

    def _tag_for(self, r) -> str:
        if bool(r.get("is_new", False)):
            return "new"
        try:
            ch = int(r.get("rank_change", 0) or 0)
        except (TypeError, ValueError):
            return ""
        if ch > 0:
            return "up"
        if ch < 0:
            return "down"
        return ""

    def _refresh_table(self) -> None:
        if self._df is None:
            return
        q = self.search.get().strip().lower()
        view = self._df
        if q:
            mask = (
                view["ticker"].astype(str).str.lower().str.contains(q, na=False)
                | view["company"].astype(str).str.lower().str.contains(q, na=False)
                | view["sector"].astype(str).str.lower().str.contains(q, na=False)
            )
            view = view[mask]
        for tree in (self.tree,):
            for item in tree.get_children():
                tree.delete(item)
            for _, r in view.iterrows():
                tree.insert("", END, values=self._row_values(r), tags=(self._tag_for(r),))

        movers = movers_summary(self._df, top_n=15)
        for tree, frame in ((self.movers_up, movers["climbers"]), (self.movers_down, movers["fallers"])):
            for item in tree.get_children():
                tree.delete(item)
            for _, r in frame.iterrows():
                tree.insert("", END, values=self._row_values(r), tags=(self._tag_for(r),))

    def _sort_by(self, col: str, tree) -> None:
        if self._df is None:
            return
        key_map = {
            "rank": "rank",
            "delta_rank": "rank_change",
            "ticker": "ticker",
            "company": "company",
            "sector": "sector",
            "compounded": "compounded_return_pct",
            "delta_ret": "compounded_delta_pct",
            "ending": "ending_capital",
            "profit": "profit_usd",
            "avg": "avg_overnight_return_pct",
            "win": "win_rate_pct",
            "dd": "max_drawdown_pct",
            "trades": "trades",
        }
        field = key_map.get(col, "rank")
        if self._sort_col == col:
            self._sort_desc = not self._sort_desc
        else:
            self._sort_col = col
            self._sort_desc = False
        if field in self._df.columns:
            self._df = self._df.sort_values(field, ascending=not self._sort_desc)
            self._refresh_table()

    def _on_run(self) -> None:
        if self._running:
            return
        try:
            days = int(self.days.get().strip())
            capital = float(self.capital.get().replace(",", "").replace("$", "").strip())
            workers = int(self.workers.get().strip())
        except ValueError:
            messagebox.showerror("Vérifiez vos chiffres", "« Nuits », « Capital » et « Téléchargements » doivent être des nombres.")
            return

        max_days = max_trading_days_available()
        if days < 5 or days > max_days:
            messagebox.showerror("Nuits de bourse", f"Choisissez entre 5 et {max_days} jours de bourse.")
            return
        if capital <= 0:
            messagebox.showerror("Capital de départ", "Le capital de départ doit être supérieur à zéro.")
            return
        if workers < 1 or workers > 32:
            messagebox.showerror("Téléchargements", "Choisissez entre 1 et 32 téléchargements simultanés.")
            return

        self._running = True
        self.run_btn.configure(state="disabled")
        self._pvar.set(0)
        self.progress.set("0 / 0")
        self.status.set("Téléchargement des barres 5 minutes Yahoo Finance pour le S&P 500...")
        self._log(
            f"Scan démarré : {days} nuits, ${capital:,.0f} de capital de départ, "
            "composition chaque nuit."
        )

        threading.Thread(
            target=self._scan_worker,
            args=(days, capital, workers, self.tickers.get()),
            daemon=True,
        ).start()

    def _scan_worker(self, days: int, capital: float, workers: int, tickers: str) -> None:
        try:
            from overnight_edge.pipeline import run_and_export

            def on_progress(done: int, total: int) -> None:
                self.root.after(0, lambda d=done, t=total: self._update_progress(d, total))

            result, df, paths = run_and_export(
                hold_count=days,
                starting_capital=capital,
                workers=workers,
                top_n=25,
                min_trades=days,
                tickers_csv=tickers,
                write_html=True,
                on_progress=on_progress,
            )
            self.root.after(0, lambda: self._on_success(df, paths, result.elapsed_seconds, capital))
        except BaseException as exc:  # noqa: BLE001
            message = str(exc)
            self.root.after(0, lambda m=message: self._on_error(m))

    def _update_progress(self, done: int, total: int) -> None:
        self._pvar.set(100.0 * done / total if total else 0)
        self.progress.set(f"{done} / {total}")
        self.status.set(f"Scan de {done} sur {total} valeurs...")

    def _on_success(self, df, paths: dict, elapsed: float, capital: float) -> None:
        self._running = False
        self.run_btn.configure(state="normal")
        self._html_path = paths.get("html_latest")
        self._output_dir = paths.get("output_dir")
        self._df = df
        self._refresh_table()
        self.status.set(
            f"Terminé en {elapsed:.1f}s. {len(df)} valeurs classées. "
            "La liste complète est ci-dessous ; les colonnes Δ comparent au scan précédent."
        )
        self._log(f"Terminé en {elapsed:.1f}s. Rapport : {self._html_path}")
        best = df.iloc[0]
        messagebox.showinfo(
            "Scan du jour terminé",
            (
                f"Meilleur titre (composé) : {best['ticker']}\n"
                f"{float(best['compounded_return_pct']):+.2f}%  |  "
                f"${capital:,.0f} → ${float(best['ending_capital']):,.2f}\n\n"
                "Le classement complet du S&P 500 et les variations au quotidien "
                "se trouvent dans la fenêtre principale et le rapport HTML."
            ),
        )

    def _on_error(self, message: str) -> None:
        self._running = False
        self.run_btn.configure(state="normal")
        self.status.set("Échec du scan — voir l'onglet « Journal ».")
        self._log("ERREUR : " + message)
        messagebox.showerror("Échec du scan", message)

    def _open_html(self) -> None:
        path = self._html_path or (default_output_dir() / "report_latest.html")
        if not Path(path).exists():
            messagebox.showinfo("Aucun rapport", "Lancez d'abord le scan du jour, ou chargez un jour antérieur après un premier scan.")
            return
        webbrowser.open(Path(path).resolve().as_uri())

    def _open_folder(self) -> None:
        folder = self._output_dir or default_output_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))  # noqa: S606

    def _font_bigger(self) -> None:
        self._font_set(self.font_size + 1)

    def _font_smaller(self) -> None:
        self._font_set(self.font_size - 1)

    def _copy_watchlist(self) -> None:
        """Copy the ranked tickers as a TradingView watchlist (comma-separated, uppercase).

        Uses the currently sorted/filtered row order so the watchlist mirrors
        what the user sees. The source-of-truth ranking lives in ``self._df``.
        """
        if self._df is None or self._df.empty:
            messagebox.showinfo("Aucune donnée", "Lancez d'abord le scan du jour pour générer la watchlist.")
            return
        tickers = _watchlist_tickers(
            self._df,
            search=self.search.get().strip(),
            sort_col=self._sort_col,
            sort_desc=self._sort_desc,
        )
        watchlist = ", ".join(tickers)
        if not watchlist:
            messagebox.showinfo("Aucune donnée", "Aucun ticker à copier.")
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(watchlist)
            self.root.update()
        except Exception:  # noqa: BLE001
            messagebox.showerror("Presse-papiers", "Impossible d'écrire dans le presse-papiers.")
            return
        self.status.set(
            f"Watchlist copiée : {len(tickers)} valeurs (collez dans TradingView via « Paste symbols »)."
        )
        self._log(f"Watchlist TradingView copiée : {len(tickers)} valeurs dans l'ordre {self._sort_col}.")

    def _font_set(self, size: int) -> None:
        size = max(FONT_SIZE_MIN, min(FONT_SIZE_MAX, int(size)))
        if size == self.font_size:
            return
        self.font_size = size
        self.font_label.set(f"{size} pt")
        _apply_font_size(size, self.root)
        # Re-apply the big title font explicitly (it uses a fixed size).
        self._refresh_table()



def launch_gui() -> int:
    prepare_runtime()
    install_exception_hook()

    root = Tk()

    def _tk_hook(exc, val, tb) -> None:  # noqa: ANN001, ARG001
        try:
            path = log_crash(val)
            messagebox.showerror(
                "Overnight Edge",
                f"Une erreur est survenue.\n\nLes détails ont été enregistrés dans :\n{path}",
            )
        except Exception:
            pass

    root.report_callback_exception = _tk_hook
    try:
        root.call("tk", "scaling", 1.15)
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    # Bigger, more readable default font for all widgets.
    _apply_font_size(FONT_SIZE_DEFAULT, root)

    def start_app() -> None:
        OvernightEdgeApp(root)

    show_birthday_then(root, start_app)
    root.mainloop()
    return 0


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    prepare_runtime()
    install_exception_hook()
    try:
        if not getattr(sys, "frozen", False) and "--cli" in sys.argv:
            sys.argv = [a for a in sys.argv if a != "--cli"]
            from run import main as cli_main
            return cli_main()
        return launch_gui()
    except Exception as exc:  # noqa: BLE001
        path = log_crash(exc)
        try:
            err = Tk()
            err.withdraw()
            messagebox.showerror(
                "Overnight Edge n'a pas pu démarrer",
                f"Les détails ont été enregistrés dans :\n{path}",
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
