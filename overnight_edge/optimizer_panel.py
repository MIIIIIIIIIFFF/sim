"""Optimizer panel UI: two animated circles (day vs night), slot table, day breakdown.

Self-contained Tkinter frame living inside the Overnight Edge app's Notebook.
It orchestrates:
* a date-range selector (calendar days back, up to ~60),
* universe selection (S&P 500 list, a saved watchlist, a free ticker list,
  plus the ability to add a ticker not in the list),
* the evaluation engine in ``overnight_edge.optimizer``,
* two Canvas "circles" animating the outcome polarity (profit / zero / loss)
  for the currently highlighted day slot and night slot,
* a slot table (best-first) and a per-day trade detail table.

The panel needs a ``root`` (for ``after`` scheduling off the worker thread),
the S&P 500 universe DataFrame (optional) and a reference to the app main
window object to read shared settings such as the starting capital.
"""

from __future__ import annotations

import math
import threading
from datetime import date, timedelta
from tkinter import StringVar, ttk

from overnight_edge.optimizer import evaluate_all_slots, load_favorites, save_favorites

FONT_FAMILY = "Segoe UI"
DAY_COLOR = "#2e86c1"
NIGHT_COLOR = "#8e44ad"


def _slot_label(family: str, bm: int, sm: int) -> str:
    b = f"{bm // 60:02d}:{bm % 60:02d}"
    s = f"{sm // 60:02d}:{sm % 60:02d}"
    return f"{'JOUR' if family == 'day' else 'NUIT'} {b}→{s}"


def _tip(widget, text: str) -> None:
    """Minimal hover tooltip bound to a widget (safe, best-effort)."""
    tip: dict = {"label": None}

    def show(_event=None) -> None:
        try:
            if tip["label"] is not None:
                return
            label = ttk.Label(None, text=text, background="#0f172a", foreground="#e2e8f0",
                              justify="left", padding=6)
            label.place(in_=widget, x=6, y=-40)
            label.lift()
            tip["label"] = label
        except Exception:  # noqa: BLE001
            pass

    def hide(_event=None) -> None:
        try:
            if tip["label"] is not None:
                tip["label"].destroy()
                tip["label"] = None
        except Exception:  # noqa: BLE001
            tip["label"] = None

    widget.bind("<Enter>", show, add="+")
    widget.bind("<Leave>", hide, add="+")
    widget.bind("<ButtonPress>", hide, add="+")


class _Circle:
    """A Canvas circle built from animated dots — one dot per cycle (trade).

    Each dot represents one evaluated cycle: green = profit, red = loss,
    gray = zero. Dots appear one-by-one around the ring, animating the circle
    into existence as cycles accumulate. The net compounded return is shown
    at the center.
    """

    def __init__(self, parent, title: str, color: str) -> None:
        from tkinter import Canvas, LabelFrame

        self.color = color
        self.box = LabelFrame(parent, text=title, font=(FONT_FAMILY, 10))
        self.box.pack(side="left", fill="both", expand=True, padx=6, pady=4)
        self.canvas = Canvas(self.box, width=160, height=160, bg="#0f172a", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._anim_id: str | None = None
        self._dots: list[tuple[str, float]] = []
        self._shown: int = 0

    def set_segments(self, segments: list[tuple[str, float]], offset=(0, 0), dash=None) -> None:
        """Set the cycle list and begin the dot-by-dot build animation.

        ``offset`` and ``dash`` are accepted for API compatibility but ignored
        — the crossover option is a logic toggle, not a visual one, so both
        circles always render side-by-side as solid dot rings.
        """
        # Cancel any pending animation frame.
        if self._anim_id is not None:
            try:
                self.canvas.after_cancel(self._anim_id)
            except Exception:  # noqa: BLE001
                pass
            self._anim_id = None

        self._dots = list(segments or [])
        self._shown = 0
        self.canvas.delete("all")
        self._draw_frame()
        self._schedule_next()

    def _draw_frame(self) -> None:
        """Draw the static center label (updated as dots appear)."""
        # Center text is redrawn each tick; nothing static needed here.
        pass

    def _schedule_next(self) -> None:
        """Reveal the next dot, then schedule the following tick."""
        if self._shown >= len(self._dots):
            self._draw_center()
            self._anim_id = None
            return
        self._reveal_dot(self._shown)
        self._shown += 1
        self._draw_center()
        # Pace: ~25ms per dot, but cap total animation at ~1.2s.
        delay = max(8, min(25, 1200 // max(len(self._dots), 1)))
        self._anim_id = self.canvas.after(delay, self._schedule_next)

    def _reveal_dot(self, index: int) -> None:
        """Draw a single dot on the ring at the angle for its index."""
        w = self.canvas.winfo_width() or 160
        h = self.canvas.winfo_height() or 160
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2 - 14
        n = max(len(self._dots), 1)
        # Distribute dots evenly around the full circle, starting at top.
        angle = (index / n) * 2 * math.pi - math.pi / 2
        x = cx + radius * math.cos(angle)
        y = cy + radius * math.sin(angle)

        kind, value = self._dots[index]
        colors = {"profit": "#22c55e", "zero": "#64748b", "loss": "#ef4444"}
        fill = colors.get(kind, "#64748b")
        # Dot size scales slightly with magnitude (clamped).
        mag = abs(value)
        sz = max(3.0, min(7.0, 3.0 + math.log1p(max(mag, 0)) * 0.8))
        self.canvas.create_oval(x - sz, y - sz, x + sz, y + sz, fill=fill, outline="")

    def _draw_center(self) -> None:
        """Draw / refresh the center label with net compounded + cycle count."""
        self.canvas.delete("center")
        w = self.canvas.winfo_width() or 160
        h = self.canvas.winfo_height() or 160
        cx, cy = w / 2, h / 2
        net = sum(v for _, v in self._dots)
        total = len(self._dots)
        shown = self._shown
        self.canvas.create_text(
            cx, cy - 6, text=f"{net:+.1f}%", fill="#e2e8f0",
            font=(FONT_FAMILY, 13, "bold"), tags="center",
        )
        self.canvas.create_text(
            cx, cy + 14, text=f"{shown}/{total} cycles", fill="#94a3b8",
            font=(FONT_FAMILY, 8), tags="center",
        )


class OptimizerPanel:
    """Tkinter frame owning the optimizer interface."""

    def __init__(self, parent, root, universe_df=None, app=None) -> None:
        self.parent = parent
        self.root = root
        self.universe_df = universe_df
        self.app = app
        self._favorites_store = load_favorites()
        self._thread: threading.Thread | None = None

        today = date.today()
        self.range_days = StringVar(value="30")
        self.range_to = StringVar(value=today.isoformat())
        self.universe_mode = StringVar(value="S&P 500 complet")
        self.fav_name = StringVar(value="")
        self.new_ticker = StringVar(value="")
        self.status = StringVar(value="Prêt. Choisissez une plage et un univers, puis cliquez Optimiser.")
        self.progress = StringVar(value="0 / 0")

        self._build()
        self._refresh_fav_combo()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        top = ttk.LabelFrame(self.parent, text="Optimiseur jour / nuit — plage de dates")
        top.pack(fill="x", padx=6, pady=6)
        row = ttk.Frame(top)
        row.pack(fill="x", padx=8, pady=6)

        ttk.Label(row, text="Jours à remonter (0–30)").pack(side="left", padx=(0, 4))
        ttk.Entry(row, textvariable=self.range_days, width=6).pack(side="left", padx=4)
        ttk.Label(row, text="Jusqu'au").pack(side="left", padx=(10, 4))
        ttk.Entry(row, textvariable=self.range_to, width=11).pack(side="left", padx=4)
        ttk.Label(row, text="(AAAA-MM-JJ)").pack(side="left", padx=4)

        univ = ttk.Frame(row)
        univ.pack(side="left", padx=10)
        ttk.Label(univ, text="Univers").pack(side="left", padx=(0, 4))
        self.mode_combo = ttk.Combobox(
            univ,
            textvariable=self.universe_mode,
            values=("S&P 500 complet", "Favoris", "Liste libre"),
            state="readonly",
            width=14,
        )
        self.mode_combo.pack(side="left")

        self._fav_combo = ttk.Combobox(
            univ,
            textvariable=self.fav_name,
            values=list(self._favorites_store.keys()),
            state="readonly",
            width=16,
        )
        self._fav_combo.pack(side="left", padx=4)

        ttk.Label(row, text="Ticker libre").pack(side="left", padx=(10, 4))
        ttk.Entry(row, textvariable=self.new_ticker, width=8).pack(side="left", padx=4)
        ttk.Button(row, text="Ajouter", command=self._add_ticker).pack(side="left", padx=4)

        self.cross_var = StringVar(value="0")
        cross_box = ttk.LabelFrame(row, text="Croiser les cercles", padding=(6, 2))
        cross_box.pack(side="left", padx=14)
        ttk.Combobox(
            cross_box, textvariable=self.cross_var, values=("Non", "Oui"), state="readonly", width=5,
        ).pack(side="left")
        _tip(cross_box,
             "Quand actif, le Jour peut acheter en pré-marché / vendre en after-marché,\net la Nuit peut acheter avant la clôture / vendre après l'ouverture.\nLes deux cercles se croisent.")

        actions = ttk.Frame(self.parent)
        actions.pack(fill="x", padx=6, pady=4)
        self.run_btn = ttk.Button(actions, text="Optimiser", command=self._on_optimize)
        self.run_btn.pack(side="left")
        ttk.Label(actions, textvariable=self.status).pack(side="left", padx=12)
        ttk.Label(actions, textvariable=self.progress).pack(side="right", padx=12)

        circles = ttk.Frame(self.parent)
        circles.pack(fill="x", padx=6, pady=4)
        self.day_circle = _Circle(circles, "Comportement jour", DAY_COLOR)
        self.night_circle = _Circle(circles, "Comportement nuit", NIGHT_COLOR)

        slots_box = ttk.LabelFrame(self.parent, text="Créneaux évalués (moyenne composée sur les titres)")
        slots_box.pack(fill="x", padx=6, pady=4)
        self.slots_tree = ttk.Treeview(
            slots_box,
            columns=("slot", "family", "compounded", "simple", "win", "avg", "dd", "days"),
            show="headings",
            height=7,
        )
        for col, head, width in (
            ("slot", "Créneau", 150),
            ("family", "Famille", 70),
            ("compounded", "Composé %", 100),
            ("simple", "Simple %", 90),
            ("win", "Gains %", 80),
            ("avg", "Moy %", 80),
            ("dd", "Tirage max %", 90),
            ("days", "Jours", 60),
        ):
            self.slots_tree.heading(col, text=head)
            self.slots_tree.column(col, width=width, anchor="center")
        self.slots_tree.tag_configure("best", background="#f0fdf4")
        self.slots_tree.tag_configure("day", foreground=DAY_COLOR)
        self.slots_tree.tag_configure("night", foreground=NIGHT_COLOR)
        self.slots_tree.pack(fill="x", padx=6, pady=2)

        detail_box = ttk.LabelFrame(self.parent, text="Détail des titres (meilleurs créneaux par famille)")
        detail_box.pack(fill="both", expand=True, padx=6, pady=4)
        self.detail_tree = ttk.Treeview(
            detail_box,
            columns=("ticker", "family", "slot", "compounded", "win"),
            show="headings",
            height=8,
        )
        for col, head, width in (
            ("ticker", "Titre", 90),
            ("family", "Famille", 70),
            ("slot", "Créneau", 150),
            ("compounded", "Composé %", 100),
            ("win", "Gains %", 80),
        ):
            self.detail_tree.heading(col, text=head)
            self.detail_tree.column(col, width=width, anchor="center")
        self.detail_tree.tag_configure("pos", foreground="#15803d")
        self.detail_tree.tag_configure("neg", foreground="#dc2626")
        self.detail_tree.pack(fill="both", expand=True, padx=6, pady=2)

    # ------------------------------------------------------------------
    # Favorites management
    # ------------------------------------------------------------------

    def _refresh_fav_combo(self) -> None:
        names = list(self._favorites_store.keys())
        self._fav_combo.configure(values=names)
        if not names:
            self._fav_combo.set("")
        elif self.fav_name.get() not in names:
            self.fav_name.set(names[0])

    def _add_ticker(self) -> None:
        ticker = self.new_ticker.get().strip().upper()
        if not ticker:
            self.status.set("Entrez un ticker à ajouter.")
            return
        current = self._favorites_store.get("Personnel", [])
        if ticker not in current:
            current.append(ticker)
        self._favorites_store["Personnel"] = current
        save_favorites(self._favorites_store)
        self._refresh_fav_combo()
        self.new_ticker.set("")
        self.status.set(f"{ticker} ajouté à la liste « Personnalisé ».")

    # ------------------------------------------------------------------
    # Run logic
    # ------------------------------------------------------------------

    def _resolve_tickers(self) -> list[str]:
        mode = self.universe_mode.get().strip()
        if mode == "Liste libre":
            return [self.new_ticker.get().strip().upper()] if self.new_ticker.get().strip() else []
        if mode == "Favoris":
            return self._favorites_store.get(self.fav_name.get(), [])
        # S&P 500 complet: use the last scan's tickers if we have one, else pull the list.
        if self.app is not None and getattr(self.app, "_df", None) is not None:
            try:
                return [str(t).upper() for t in self.app._df["ticker"].tolist()]
            except (KeyError, AttributeError):
                pass
        if self.universe_df is not None and not self.universe_df.empty:
            return [str(t).upper() for t in self.universe_df["ticker"].tolist()]
        try:
            from overnight_edge.universe import fetch_sp500_universe
            universe = fetch_sp500_universe()
            self.universe_df = universe
            return [str(t).upper() for t in universe["ticker"].tolist()]
        except Exception:  # noqa: BLE001
            return []

    def _on_optimize(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        try:
            days_back = int(self.range_days.get().strip() or "30")
        except ValueError:
            self.status.set("Jours de remontée invalide (nombre entier 0–30).")
            return
        days_back = max(0, min(30, days_back))
        try:
            end = date.fromisoformat(self.range_to.get().strip())
        except ValueError:
            self.status.set("Date de fin invalide (AAAA-MM-JJ).")
            return
        start = end - timedelta(days=days_back) if days_back > 0 else end - timedelta(days=10)

        tickers = self._resolve_tickers()
        if not tickers:
            self.status.set("Aucun titre à optimiser. Vérifiez l'univers ou la liste de favoris.")
            return

        self.run_btn.configure(state="disabled")
        self.progress.set("0 / 0")
        crossover = self.cross_var.get().strip() == "Oui"
        self.status.set(
            f"Optimisation de {len(tickers)} titres sur {days_back} jours"
            + (" (créneaux croisés)" if crossover else "") + "..."
        )
        self._thread = threading.Thread(
            target=self._optimize_worker,
            args=(tickers, start, end, days_back, crossover),
            daemon=True,
        )
        self._thread.start()

    def _optimize_worker(self, tickers: list[str], start: date, end: date, days_back: int, crossover: bool = False) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self._crossover = crossover
        self._agg: dict[tuple, dict] = {}
        self._per_ticker: list[dict] = []
        throttle = max(1, min(len(tickers) // 20, 8))
        n_workers = max(4, min(10, len(tickers)))
        self._render_partial(0, len(tickers), days_back)
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(self._analyze_ticker, t, start, end, crossover): t for t in tickers}
            for future in as_completed(futures):
                ticker = futures[future]
                try:
                    pt, slots = future.result()
                except Exception:  # noqa: BLE001
                    pt = {"ticker": ticker, "family": "—", "slot": "échec",
                          "compounded": float("nan"), "win": float("nan")}
                    slots = []
                self._per_ticker.append(pt)
                for slot in slots:
                    key = (slot.family, slot.buy_minute, slot.sell_minute)
                    bucket = self._agg.setdefault(key, {"n": 0, "compounded": 0.0, "simple": 0.0,
                                                        "win": 0.0, "avg": 0.0, "dd": 0.0,
                                                        "days": set(), "trades": []})
                    bucket["n"] += 1
                    bucket["compounded"] += slot.compounded_return_pct
                    bucket["simple"] += slot.simple_return_pct
                    bucket["win"] += slot.win_rate_pct
                    bucket["avg"] += slot.avg_return_pct
                    bucket["dd"] += slot.max_drawdown_pct
                    bucket["days"].update(t.buy_date for t in slot.trades)
                    bucket["trades"].extend(slot.trades)
                done += 1
                if done % throttle == 0:
                    self.root.after(0, lambda: self._render_partial(done, len(tickers), days_back))

        self.root.after(0, lambda: self._render_partial(done, len(tickers), days_back, final=True))

    def _analyze_ticker(self, ticker: str, start: date, end: date, crossover: bool = False) -> tuple[dict, list]:
        """Fetch + evaluate all slots for a single ticker (runs in pool thread)."""
        from overnight_edge.data import download_intraday_cached
        from overnight_edge.optimizer import evaluate_all_slots

        bars, _source = download_intraday_cached(ticker, 60)
        slots = evaluate_all_slots(bars, start=start, end=end, crossover=crossover)
        best = max(slots, key=lambda s: s.compounded_return_pct) if slots else None
        pt = {
            "ticker": ticker,
            "family": best.family if best else "—",
            "slot": best.slot_name if best else "—",
            "compounded": best.compounded_return_pct if best else float("nan"),
            "win": best.win_rate_pct if best else float("nan"),
        }
        return pt, slots

    def _aggregate_rows(self) -> list[dict]:
        rows: list[dict] = []
        for (family, bm, sm), bucket in self._agg.items():
            n = bucket["n"]
            if n == 0:
                continue
            rows.append(
                {
                    "slot": _slot_label(family, bm, sm),
                    "family": "Jour" if family == "day" else "Nuit",
                    "compounded": bucket["compounded"] / n,
                    "simple": bucket["simple"] / n,
                    "win": bucket["win"] / n,
                    "avg": bucket["avg"] / n,
                    "dd": bucket["dd"] / n,
                    "days": min(bucket["days"]) if bucket["days"] else 0,
                    "trades": bucket["trades"],
                }
            )
        rows.sort(key=lambda r: r["compounded"], reverse=True)
        return rows

    def _render_partial(self, done: int, total: int, days_back: int, final: bool = False) -> None:
        self._render_slots(self._aggregate_rows(), self._per_ticker, days_back, partial=not final)
        self.progress.set(f"{done} / {total}")

    def _trade_segments(self, row: dict | None = None) -> list[tuple[str, float]]:
        """Build circle segments from a slot row's day-by-day trades.

        Each segment is (kind, |return_pct|) colored profit/zero/loss so the
        circle visually conveys the spread between winning, flat and losing
        days of the best slot. Falls back to the aggregated compounded value
        when the row carries no trade detail.
        """
        if not row:
            return []
        trades = row.get("trades") or []
        if trades:
            segs: list[tuple[str, float]] = []
            for t in trades:
                r = t.return_pct
                kind = "profit" if r > 0 else ("loss" if r < 0 else "zero")
                segs.append((kind, abs(r)))
            return segs
        # Fallback: a single colored arc from the aggregate compounded value.
        comp = row.get("compounded", 0.0)
        kind = "profit" if comp >= 0 else "loss"
        return [(kind, abs(comp))]

    def _render_slots(
        self,
        rows: list[dict],
        per_ticker: list[dict],
        days_back: int,
        partial: bool = False,
    ) -> None:
        if not partial:
            self.run_btn.configure(state="normal")
        tree = self.slots_tree
        for item in tree.get_children():
            tree.delete(item)
        best_row = rows[0] if rows else None
        for r in rows:
            tag = "best" if best_row and r["slot"] == best_row["slot"] else ("day" if r["family"] == "Jour" else "night")
            tree.insert(
                "",
                "end",
                values=(
                    r["slot"],
                    r["family"],
                    f"{r['compounded']:+.2f}%",
                    f"{r['simple']:+.2f}%",
                    f"{r['win']:.1f}%",
                    f"{r['avg']:+.3f}%",
                    f"{r['dd']:.2f}%",
                    r["days"],
                ),
                tags=(tag,),
            )

        # Circles show the cycle-by-cycle outcome polarity of the best slot per family.
        # Each dot = one trade; green = profit, red = loss, gray = zero. Dots
        # animate in one-by-one to build the circle.
        best_day = next((r for r in rows if r["family"] == "Jour"), None)
        best_night = next((r for r in rows if r["family"] == "Nuit"), None)
        self.day_circle.set_segments(self._trade_segments(best_day))
        self.night_circle.set_segments(self._trade_segments(best_night))

        det = self.detail_tree
        for item in det.get_children():
            det.delete(item)
        for p in per_ticker:
            if p.get("compounded") != p.get("compounded"):  # NaN check
                tag = ""
                comp = "—"
                win = "—"
            else:
                tag = "pos" if p["compounded"] >= 0 else "neg"
                comp = f"{p['compounded']:+.2f}%"
                win = f"{p['win']:.1f}%"
            det.insert(
                "",
                "end",
                values=(p["ticker"], p["family"], p["slot"], comp, win),
                tags=(tag,),
            )

        if not rows:
            self.status.set("Aucun créneau exploitable sur cette plage pour ces titres.")
            return
        self.status.set(f"Meilleur créneau global : {best_row['slot']} ({best_row['compounded']:+.2f}% composé) sur {days_back} jours.")