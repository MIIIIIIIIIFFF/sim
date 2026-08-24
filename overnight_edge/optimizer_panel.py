"""Optimizer panel UI: two animated circles (day vs night), slot table, day breakdown.

Self-contained Tkinter frame living inside the Overnight Edge app's Notebook.
It orchestrates:
* a date-range selector (calendar days back, up to ~60),
* a proper list editor (create / rename / delete lists, add / remove tickers),
* a clear optimization mode selector (Day only / Night only / Both / Crossed),
* the evaluation engine in ``overnight_edge.optimizer``,
* two Canvas "circles" animating the outcome polarity (profit / zero / loss)
  for the best day slot and best night slot,
* a prominent best-result banner per family and a per-ticker detail table.
"""

from __future__ import annotations

import math
import os
import threading
import time
from datetime import date, timedelta
from tkinter import StringVar, Tk, messagebox, ttk

from overnight_edge.optimizer import evaluate_all_slots, load_favorites, save_favorites

FONT_FAMILY = "Segoe UI"
DAY_COLOR = "#2e86c1"
NIGHT_COLOR = "#8e44ad"

_SEGMENT_COLORS = {"profit": "#22c55e", "zero": "#94a3b8", "loss": "#ef4444"}

# Optimization modes.
MODE_DAY = "Jour seulement"
MODE_NIGHT = "Nuit seulement"
MODE_BOTH = "Jour + Nuit (séparés)"
MODE_CROSS = "Jour + Nuit (croisés)"


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


class _CrossRings:
    """Two separate scatter-plot circles (day on the left, night on the right).

    Each circle is a dot per ticker in that family:
    - green dots above zero (positive compounded return),
    - red dots below zero (negative compounded return),
    - gray dots near zero,
    - dot size scales with the magnitude of the return,
    - the zero line is drawn as a faint horizontal diameter so the green/red
      split reads at a glance; the center shows the family's average return.
    """

    def __init__(self, parent, color_day: str, color_night: str) -> None:
        from tkinter import Frame, LabelFrame

        self.color_day = color_day
        self.color_night = color_night
        self.box = LabelFrame(parent, text="Rendement par titre (jour / nuit)",
                              font=(FONT_FAMILY, 10))
        self.box.pack(fill="x", expand=True, padx=6, pady=4)

        self.frame = Frame(self.box)
        self.frame.pack(fill="both", expand=True)

        self.day = self._Scatter(self.frame, "Jour", color_day)
        self.night = self._Scatter(self.frame, "Nuit", color_night)

        self._crossover = False

    class _Scatter:
        """A scatter circle: one dot per ticker, placed around the circle."""

        def __init__(self, parent, title: str, accent: str) -> None:
            from tkinter import Canvas, Frame, Label

            self.accent = accent
            holder = Frame(parent)
            holder.pack(side="left", fill="both", expand=True, padx=6, pady=4)
            Label(holder, text=title, font=(FONT_FAMILY, 11, "bold"),
                  fg="#e2e8f0", bg="#0f172a").pack()
            self.canvas = Canvas(holder, width=220, height=220, bg="#0f172a",
                                 highlightthickness=0)
            self.canvas.pack(fill="both", expand=True, padx=4, pady=4)

            self._points: list[tuple[str, float]] = []   # (ticker, return%)
            self._shown = 0
            self._anim_id: str | None = None

        def set_data(self, points, _label: str = "", animate: bool = True) -> None:
            """Set the scatter for this family.

            ``points`` is a list of ``(ticker, return_pct)``; ``animate`` reveals
            the dots one-by-one (final render) vs all at once (live optimization).
            """
            if self._anim_id is not None:
                try:
                    self.canvas.after_cancel(self._anim_id)
                except Exception:  # noqa: BLE001
                    pass
                self._anim_id = None
            self._points = list(points or [])
            self.canvas.delete("all")
            if animate:
                self._shown = 0
                self._draw()
            else:
                self._shown = len(self._points)
                self._draw(static=True)

        def _draw(self, static: bool = False) -> None:
            """Draw the zero-line circle + the dots revealed so far."""
            self.canvas.delete("all")
            w = self.canvas.winfo_width() or 220
            h = self.canvas.winfo_height() or 220
            cx, cy = w / 2, h / 2
            r = min(w, h) / 2 - 16
            # Outline + zero baseline (faint horizontal diameter).
            self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                    outline=self.accent, width=2)
            self.canvas.create_line(cx - r, cy, cx + r, cy, fill="#334155",
                                    width=1, dash=(3, 3))

            pts = self._points[: self._shown]
            if pts:
                max_abs = max((abs(v) for _, v in pts), default=1.0) or 1.0
                n = len(self._points)
                for i, (ticker, value) in enumerate(pts):
                    # Place around the circle, evenly spaced.
                    angle = (i / n) * 2 * 3.141592653589793
                    # Radial offset proportional to |return| (further from zero
                    # line = bigger |return|), clamped inside the disk.
                    frac = 0.25 + 0.7 * (abs(value) / max_abs)
                    px = cx + r * frac * math.cos(angle)
                    py = cy - (r * frac * (1 if value >= 0 else -1)) * math.sin(angle) * 0.6
                    if abs(value) < 1e-9:
                        fill = "#94a3b8"
                    elif value > 0:
                        fill = "#22c55e"
                    else:
                        fill = "#ef4444"
                    sz = 3 + 5 * (abs(value) / max_abs)
                    self.canvas.create_oval(px - sz, py - sz, px + sz, py + sz,
                                             fill=fill, outline="", tags="dot")

            # Center: average return + count.
            if pts:
                avg = sum(v for _, v in pts) / len(pts)
            else:
                avg = 0.0
            self.canvas.create_text(cx, cy - 6, text=f"{avg:+.1f}%",
                                     fill="#f8fafc", font=(FONT_FAMILY, 14, "bold"))
            self.canvas.create_text(cx, cy + 12, text=f"{len(pts)} titres",
                                     fill="#94a3b8", font=(FONT_FAMILY, 8))

            if not static and self._shown < len(self._points):
                delay = max(6, min(25, 1200 // max(len(self._points), 1)))

                def _step(_self=self) -> None:
                    try:
                        if not _self.canvas.winfo_exists():
                            _self._anim_id = None
                            return
                        _self._shown += 1
                        _self._draw()
                        if _self._shown >= len(_self._points):
                            _self._anim_id = None
                    except Exception:  # noqa: BLE001
                        _self._anim_id = None

                self._anim_id = self.canvas.after(delay, _step)

        def set_segments(self, segments, offset=(0, 0), dash=None) -> None:
            self.set_data(segments, animate=False)

    # ------------------------------------------------------------------
    def set_rings(self, day_points, night_points, crossover=False,
                  day_label: str = "", night_label: str = "",
                  animate: bool = True) -> None:
        """Redraw both scatter circles from per-ticker return lists.

        ``day_points``/``night_points`` are ``[(ticker, return_pct), ...]``.
        ``crossover``/labels are accepted for API compatibility and ignored.
        """
        self._crossover = crossover
        self.day.set_data(day_points or [], animate=animate)
        self.night.set_data(night_points or [], animate=animate)

    # Kept for API compatibility with audit/old callers.
    @property
    def canvas(self):
        return self.day.canvas

    def set_segments(self, day_segments, night_segments, offset=(0, 0), dash=None) -> None:
        self.set_rings(day_segments, night_segments, crossover=self._crossover)


class OptimizerPanel:
    """Tkinter frame owning the optimizer interface."""

    def __init__(self, parent, root, universe_df=None, app=None) -> None:
        self.parent = parent
        self.root = root
        self.universe_df = universe_df
        self.app = app
        self._favorites_store = load_favorites()
        self._thread: threading.Thread | None = None
        self._crossover = False

        today = date.today()
        self.range_days = StringVar(value="30")
        self.range_to = StringVar(value=today.isoformat())
        self.mode = StringVar(value=MODE_BOTH)
        self.list_name = StringVar(value="")
        self.new_ticker = StringVar(value="")
        self.status = StringVar(value="Prêt. Choisissez une liste, un mode, puis cliquez Optimiser.")
        self.progress = StringVar(value="")

        # Ensure a default personal list exists.
        if "Personnel" not in self._favorites_store:
            self._favorites_store["Personnel"] = []

        self._build()
        self._refresh_list_combo()
        self._populate_ticker_listbox()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build(self) -> None:
        # Split the optimizer tab into two sub-pages so the list editor no
        # longer eats the circles' vertical space.
        self._pages = ttk.Notebook(self.parent)
        self._pages.pack(fill="both", expand=True, padx=6, pady=6)

        list_page = ttk.Frame(self._pages)
        opt_page = ttk.Frame(self._pages)
        self._pages.add(list_page, text="①  Listes de titres")
        self._pages.add(opt_page, text="②  Optimiser")
        self._pages.bind("<<NotebookTabChanged>>", self._on_page_change)

        # ---- Page 1: List editor (full height) ----------------------
        list_frame = ttk.LabelFrame(list_page, text="Liste de titres")
        list_frame.pack(fill="both", expand=True, padx=6, pady=(6, 2))

        list_top = ttk.Frame(list_frame)
        list_top.pack(fill="x", padx=8, pady=4)
        ttk.Label(list_top, text="Liste :").pack(side="left", padx=(0, 4))
        self._list_combo = ttk.Combobox(
            list_top, textvariable=self.list_name,
            values=list(self._favorites_store.keys()), state="readonly", width=16,
        )
        self._list_combo.pack(side="left", padx=4)
        self._list_combo.bind("<<ComboboxSelected>>", lambda _e: self._populate_ticker_listbox())
        ttk.Button(list_top, text="Nouvelle", command=self._new_list).pack(side="left", padx=4)
        ttk.Button(list_top, text="Renommer", command=self._rename_list).pack(side="left", padx=4)
        ttk.Button(list_top, text="Supprimer", command=self._delete_list).pack(side="left", padx=4)
        ttk.Button(list_top, text="S&P 500", command=self._load_sp500).pack(side="left", padx=4)
        _tip(list_top, "Créez, renommez ou supprimez vos listes de titres.\n« S&P 500 » charge les 500 plus grandes valeurs US.")

        list_mid = ttk.Frame(list_frame)
        list_mid.pack(fill="both", expand=True, padx=8, pady=4)
        self._ticker_listbox = ttk.Treeview(
            list_mid, columns=("ticker",), show="headings", height=14,
        )
        self._ticker_listbox.heading("ticker", text="Titres dans la liste")
        self._ticker_listbox.column("ticker", width=140, anchor="center")
        self._ticker_listbox.pack(side="left", fill="both", expand=True)
        list_scroll = ttk.Scrollbar(list_mid, orient="vertical",
                                    command=self._ticker_listbox.yview)
        list_scroll.pack(side="left", fill="y")
        self._ticker_listbox.configure(yscrollcommand=list_scroll.set)

        list_side = ttk.Frame(list_frame)
        list_side.pack(side="right", padx=8, fill="y")
        ttk.Label(list_side, text="Ajouter :").pack(anchor="w")
        ttk.Entry(list_side, textvariable=self.new_ticker, width=14).pack(anchor="w", pady=2)
        ttk.Button(list_side, text="+ Ajouter", command=self._add_ticker).pack(anchor="w", pady=2)
        ttk.Button(list_side, text="− Retirer", command=self._remove_ticker).pack(anchor="w", pady=2)

        # ---- Page 2: Optimize (config + run + banners + circles + detail) --
        # ---- Section 2: Date range + mode -----------------------------
        cfg_frame = ttk.LabelFrame(opt_page, text="Plage de dates et mode")
        cfg_frame.pack(fill="x", padx=6, pady=2)

        cfg_top = ttk.Frame(cfg_frame)
        cfg_top.pack(fill="x", padx=8, pady=4)
        ttk.Label(cfg_top, text="Jours à remonter (0–60)").pack(side="left", padx=(0, 4))
        ttk.Entry(cfg_top, textvariable=self.range_days, width=6).pack(side="left", padx=4)
        ttk.Label(cfg_top, text="Jusqu'au").pack(side="left", padx=(10, 4))
        ttk.Entry(cfg_top, textvariable=self.range_to, width=11).pack(side="left", padx=4)
        ttk.Label(cfg_top, text="(AAAA-MM-JJ)").pack(side="left", padx=4)

        cfg_mode = ttk.Frame(cfg_frame)
        cfg_mode.pack(fill="x", padx=8, pady=4)
        ttk.Label(cfg_mode, text="Mode :").pack(side="left", padx=(0, 8))
        for label, val in [
            ("Jour", MODE_DAY),
            ("Nuit", MODE_NIGHT),
            ("Jour + Nuit", MODE_BOTH),
            ("Croisés", MODE_CROSS),
        ]:
            ttk.Radiobutton(cfg_mode, text=label, variable=self.mode, value=val).pack(side="left", padx=6)
        _tip(cfg_mode,
             "Jour : optimise uniquement les créneaux intraday (achat matin, vente après-midi).\n"
             "Nuit : optimise uniquement les créneaux overnight (achat clôture, vente pré-ouverture).\n"
             "Jour + Nuit : optimise les deux séparément et affiche les deux cercles.\n"
             "Croisés : les familles peuvent utiliser les heures étendues de l'autre (pré-marché, after-marché, etc.).")

        # ---- Section 3: Run button + status ---------------------------
        actions = ttk.Frame(opt_page)
        actions.pack(fill="x", padx=6, pady=4)
        self.run_btn = ttk.Button(actions, text="⚙  Optimiser", command=self._on_optimize)
        self.run_btn.pack(side="left")
        ttk.Label(actions, textvariable=self.status, wraplength=400).pack(side="left", padx=12)
        ttk.Label(actions, textvariable=self.progress).pack(side="right", padx=12)

        # ---- Section 4: Best-result banners ---------------------------
        banner = ttk.Frame(opt_page)
        banner.pack(fill="x", padx=6, pady=2)
        self.day_banner = StringVar(value="Jour : en attente")
        self.night_banner = StringVar(value="Nuit : en attente")
        self.day_banner_lbl = ttk.Label(banner, textvariable=self.day_banner,
                                        font=(FONT_FAMILY, 12, "bold"), foreground=DAY_COLOR)
        self.day_banner_lbl.pack(anchor="w", padx=8)
        self.night_banner_lbl = ttk.Label(banner, textvariable=self.night_banner,
                                          font=(FONT_FAMILY, 12, "bold"), foreground=NIGHT_COLOR)
        self.night_banner_lbl.pack(anchor="w", padx=8)

        # ---- Section 5: Interactive profit/loss circles --------------
        circles = ttk.Frame(opt_page)
        circles.pack(fill="x", padx=6, pady=4)
        self.rings = _CrossRings(circles, DAY_COLOR, NIGHT_COLOR)

        # ---- Section 6: Per-ticker detail -----------------------------
        detail_box = ttk.LabelFrame(opt_page, text="Détail par titre (meilleur créneau)")
        detail_box.pack(fill="both", expand=True, padx=6, pady=4)
        detail_inner = ttk.Frame(detail_box)
        detail_inner.pack(fill="both", expand=True, padx=6, pady=6)
        self.detail_tree = ttk.Treeview(
            detail_inner,
            columns=("ticker", "family", "slot", "compounded", "win"),
            show="headings",
            height=10,
        )
        self._detail_sort: tuple[str, bool] = ("compounded", False)  # (col, descending)
        for col, head, width in (
            ("ticker", "Titre", 110),
            ("family", "Famille", 90),
            ("slot", "Créneau achat → vente", 220),
            ("compounded", "Composé %", 120),
            ("win", "Taux de réussite", 150),
        ):
            self.detail_tree.heading(col, text=head, command=lambda c=col: self._sort_detail_by(c))
            self.detail_tree.column(col, width=width, anchor="center")
        self.detail_tree.tag_configure("pos", foreground="#15803d")
        self.detail_tree.tag_configure("neg", foreground="#dc2626")
        self.detail_tree.pack(side="left", fill="both", expand=True)
        detail_scroll = ttk.Scrollbar(detail_inner, orient="vertical",
                                     command=self.detail_tree.yview)
        detail_scroll.pack(side="left", fill="y")
        self.detail_tree.configure(yscrollcommand=detail_scroll.set)

    def _on_page_change(self, _event) -> None:
        """Re-sync widget sizes when the sub-notebook page changes."""
        self.parent.update_idletasks()

    def _sort_detail_by(self, col: str) -> None:
        """Sort the detail table by ``col``; click again to reverse direction."""
        cur_col, cur_desc = self._detail_sort
        if cur_col == col:
            desc = not cur_desc
        else:
            desc = False  # default ascending on a new column
        self._detail_sort = (col, desc)
        self._resort_detail()

    def _resort_detail(self) -> None:
        """Reorder existing detail rows by the current sort column/direction."""
        col, desc = self._detail_sort
        det = self.detail_tree
        items = det.get_children()
        keyed = []
        for item in items:
            vals = det.set(item)
            raw = vals.get(col, "")
            try:
                key = float(raw.rstrip("%").replace("—", "nan") or "nan")
            except ValueError:
                key = raw
            keyed.append((key, item))
        # NaNs (failed tickers) always sink to the bottom regardless of direction.
        keyed.sort(key=lambda kv: (1 if isinstance(kv[0], float) and kv[0] != kv[0] else 0,
                                   kv[0]),
                   reverse=desc)
        for _, item in keyed:
            det.move(item, "", "end")

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list_combo(self) -> None:
        names = list(self._favorites_store.keys())
        self._list_combo.configure(values=names)
        if not names:
            self.list_name.set("")
        elif self.list_name.get() not in names:
            self.list_name.set(names[0])

    def _populate_ticker_listbox(self) -> None:
        """Refresh the ticker listbox from the currently selected list."""
        for item in self._ticker_listbox.get_children():
            self._ticker_listbox.delete(item)
        name = self.list_name.get()
        tickers = self._favorites_store.get(name, [])
        for t in tickers:
            self._ticker_listbox.insert("", "end", values=(t,))

    def _current_list_name(self) -> str:
        return self.list_name.get().strip()

    def _new_list(self) -> None:
        """Create a new named list via a simple dialog."""
        name = self._simple_dialog("Nouvelle liste", "Nom de la liste :")
        if not name:
            return
        if name in self._favorites_store:
            messagebox.showinfo("Existe", f"La liste « {name} » existe déjà.")
            return
        self._favorites_store[name] = []
        save_favorites(self._favorites_store)
        self.list_name.set(name)
        self._refresh_list_combo()
        self._populate_ticker_listbox()

    def _rename_list(self) -> None:
        old = self._current_list_name()
        if not old:
            return
        new = self._simple_dialog("Renommer", f"Nouveau nom pour « {old} » :")
        if not new or new == old:
            return
        if new in self._favorites_store:
            messagebox.showinfo("Existe", f"La liste « {new} » existe déjà.")
            return
        self._favorites_store[new] = self._favorites_store.pop(old)
        save_favorites(self._favorites_store)
        self.list_name.set(new)
        self._refresh_list_combo()
        self._populate_ticker_listbox()

    def _delete_list(self) -> None:
        name = self._current_list_name()
        if not name:
            return
        if len(self._favorites_store) <= 1:
            messagebox.showinfo("Impossible", "Au moins une liste doit exister.")
            return
        if not messagebox.askyesno("Confirmer", f"Supprimer la liste « {name} » ?"):
            return
        del self._favorites_store[name]
        save_favorites(self._favorites_store)
        self._refresh_list_combo()
        self._populate_ticker_listbox()

    def _load_sp500(self) -> None:
        """Load the S&P 500 ticker list into the current list."""
        name = self._current_list_name() or "S&P 500"
        try:
            from overnight_edge.universe import fetch_sp500_universe
            universe = fetch_sp500_universe()
            tickers = [str(t).upper() for t in universe["ticker"].tolist()]
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Erreur", f"Impossible de charger le S&P 500 :\n{exc}")
            return
        self._favorites_store[name] = tickers
        save_favorites(self._favorites_store)
        self.list_name.set(name)
        self._refresh_list_combo()
        self._populate_ticker_listbox()
        self.status.set(f"{len(tickers)} titres S&P 500 chargés dans « {name} ».")

    def _add_ticker(self) -> None:
        ticker = self.new_ticker.get().strip().upper()
        if not ticker:
            self.status.set("Entrez un ticker à ajouter.")
            return
        name = self._current_list_name()
        if not name:
            name = "Personnel"
            self.list_name.set(name)
        current = self._favorites_store.get(name, [])
        if ticker not in current:
            current.append(ticker)
            self._favorites_store[name] = current
            save_favorites(self._favorites_store)
        self.new_ticker.set("")
        self._populate_ticker_listbox()
        self.status.set(f"{ticker} ajouté à « {name} ».")

    def _remove_ticker(self) -> None:
        sel = self._ticker_listbox.selection()
        if not sel:
            self.status.set("Sélectionnez un titre à retirer.")
            return
        name = self._current_list_name()
        for item_id in sel:
            vals = self._ticker_listbox.item(item_id, "values")
            if vals:
                ticker = vals[0].upper()
                current = self._favorites_store.get(name, [])
                if ticker in current:
                    current.remove(ticker)
                self._favorites_store[name] = current
        save_favorites(self._favorites_store)
        self._populate_ticker_listbox()
        self.status.set("Titre(s) retiré(s).")

    def _simple_dialog(self, title: str, prompt: str) -> str:
        """A tiny input dialog (avoids simpledialog dependency in frozen builds)."""
        from tkinter import Toplevel

        dlg = Toplevel(self.root)
        dlg.title(title)
        dlg.geometry("340x110")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        result = {"value": ""}

        ttk.Label(dlg, text=prompt, font=(FONT_FAMILY, 10)).pack(pady=(16, 8), padx=16)
        entry_var = StringVar()
        entry = ttk.Entry(dlg, textvariable=entry_var, width=30)
        entry.pack(padx=16)
        entry.focus_set()

        def _ok(_event=None) -> None:
            result["value"] = entry_var.get().strip()
            dlg.destroy()

        def _cancel(_event=None) -> None:
            dlg.destroy()

        btns = ttk.Frame(dlg)
        btns.pack(pady=10)
        ttk.Button(btns, text="OK", command=_ok).pack(side="left", padx=8)
        ttk.Button(btns, text="Annuler", command=_cancel).pack(side="left", padx=8)
        dlg.bind("<Return>", _ok)
        dlg.bind("<Escape>", _cancel)
        self.root.wait_window(dlg)
        return result["value"]

    # ------------------------------------------------------------------
    # Run logic
    # ------------------------------------------------------------------

    def _resolve_tickers(self) -> list[str]:
        name = self._current_list_name()
        tickers = self._favorites_store.get(name, [])
        if tickers:
            return [str(t).upper() for t in tickers]
        # Fallback: try app's last scan.
        if self.app is not None and getattr(self.app, "_df", None) is not None:
            try:
                return [str(t).upper() for t in self.app._df["ticker"].tolist()]
            except (KeyError, AttributeError):
                pass
        return []

    def _on_optimize(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        try:
            days_back = int(self.range_days.get().strip() or "30")
        except ValueError:
            self.status.set("Jours de remontée invalide (nombre entier 0–30).")
            return
        days_back = max(0, min(60, days_back))
        try:
            end = date.fromisoformat(self.range_to.get().strip())
        except ValueError:
            self.status.set("Date de fin invalide (AAAA-MM-JJ).")
            return
        start = end - timedelta(days=days_back) if days_back > 0 else end - timedelta(days=10)

        tickers = self._resolve_tickers()
        if not tickers:
            self.status.set("Aucun titre dans la liste. Ajoutez-en ou chargez le S&P 500.")
            return

        mode = self.mode.get()
        crossover = mode == MODE_CROSS
        self._crossover = crossover

        self.run_btn.configure(state="disabled")
        self.progress.set("0 / 0")
        self.day_banner.set("Jour : optimisation en cours...")
        self.night_banner.set("Nuit : optimisation en cours...")
        self.status.set(
            f"Optimisation de {len(tickers)} titres sur {days_back} jours — {mode}..."
        )
        self._thread = threading.Thread(
            target=self._optimize_worker,
            args=(tickers, start, end, days_back, mode, crossover),
            daemon=True,
        )
        self._thread.start()

    def _optimize_worker(self, tickers: list[str], start: date, end: date, days_back: int,
                         mode: str, crossover: bool) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from overnight_edge.data import clear_memory_cache

        # Clear any stale memory cache from a previous run.
        clear_memory_cache()

        self._crossover = crossover
        self._mode = mode
        self._agg: dict[tuple, dict] = {}
        self._per_ticker: list[dict] = []

        # Use at least 4 workers, scale with CPU count, cap at len(tickers).
        cpu = os.cpu_count() or 4
        n_workers = max(4, min(cpu * 2, len(tickers)))
        # Throttle UI updates: update every N completions, but at most every ~250ms
        # to avoid swamping the Tk main loop (which causes the hang).
        throttle = max(1, len(tickers) // 40)

        self._render_partial(0, len(tickers), days_back)
        done = 0
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(self._analyze_ticker, t, start, end, crossover, mode): t for t in tickers}
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
                    self.root.after(0, lambda d=done: self._render_partial(d, len(tickers), days_back))

        self.root.after(0, lambda: self._render_partial(done, len(tickers), days_back, final=True))

    def _analyze_ticker(self, ticker: str, start: date, end: date,
                        crossover: bool, mode: str) -> tuple[dict, list]:
        """Fetch + evaluate all slots for a single ticker (runs in pool thread).

        Only returns slots for the requested family(ies) based on the mode.
        """
        from overnight_edge.data import download_intraday_cached
        from overnight_edge.optimizer import evaluate_all_slots

        bars, _source = download_intraday_cached(ticker, 60)
        slots = evaluate_all_slots(bars, start=start, end=end, crossover=crossover)

        # Filter by mode: keep only the relevant family's slots.
        if mode == MODE_DAY:
            slots = [s for s in slots if s.family == "day"]
        elif mode == MODE_NIGHT:
            slots = [s for s in slots if s.family == "night"]
        # MODE_BOTH and MODE_CROSS keep both families.

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
        rows = self._aggregate_rows()
        # During optimization, only refresh the (expensive) circles at most once
        # per second; the progress label and detail table still update every
        # batch. The final render always redraws everything, animated.
        now = time.monotonic()
        last = getattr(self, "_last_ring_ms", 0.0)
        ring_due = final or (now - last) >= 1.0
        if ring_due:
            self._last_ring_ms = now
        self._render_results(rows, self._per_ticker, days_back,
                             partial=not final, refresh_rings=ring_due)
        self.progress.set(f"{done} / {total}")

    def _trade_segments(self, row: dict | None = None) -> list[tuple[str, float]]:
        """Build circle dots from a slot row's cycle-by-cycle trades."""
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
        comp = row.get("compounded", 0.0)
        kind = "profit" if comp >= 0 else "loss"
        return [(kind, abs(comp))]

    def _render_results(
        self,
        rows: list[dict],
        per_ticker: list[dict],
        days_back: int,
        partial: bool = False,
        refresh_rings: bool = True,
    ) -> None:
        if not partial:
            self.run_btn.configure(state="normal")

        mode = getattr(self, "_mode", MODE_BOTH)

        # Find best day and best night rows.
        best_day = next((r for r in rows if r["family"] == "Jour"), None)
        best_night = next((r for r in rows if r["family"] == "Nuit"), None)

        # Update banners with the single best buy/sell hour per family.
        def _fmt_slot(slot: str) -> str:
            """Extract a readable 'achat XX:XX → vente XX:XX' from a slot string.

            Slots look like 'JOUR 10:00 → 15:00' or 'NUIT 16:00 → 09:10'.
            """
            if "→" in slot:
                left, right = slot.split("→", 1)
                buy = left.strip().split(" ")[-1]
                sell = right.strip().split(" ")[0]
                return f"achat {buy}  →  vente {sell}"
            return slot

        if mode in (MODE_DAY, MODE_BOTH, MODE_CROSS):
            if best_day:
                self.day_banner.set(
                    f"Jour :  {_fmt_slot(best_day['slot'])}  |  "
                    f"{best_day['compounded']:+.2f}% composé"
                )
            elif not partial:
                self.day_banner.set("Jour : aucun créneau exploitable")
        else:
            self.day_banner.set("Jour : non optimisé (mode Nuit)")

        if mode in (MODE_NIGHT, MODE_BOTH, MODE_CROSS):
            if best_night:
                self.night_banner.set(
                    f"Nuit :  {_fmt_slot(best_night['slot'])}  |  "
                    f"{best_night['compounded']:+.2f}% composé"
                )
            elif not partial:
                self.night_banner.set("Nuit : aucun créneau exploitable")
        else:
            self.night_banner.set("Nuit : non optimisé (mode Jour)")

        # Update the interactive per-ticker scatter circles.
        # Each circle gets one dot per ticker in that family (green = positive
        # return, red = negative, gray = ~0). Static during optimization
        # (no per-dot after() animation → no lag); animated only on the final
        # render. Skipped when refresh_rings is False (throttled to ~1/s).
        if refresh_rings:
            day_pts = [(p["ticker"], p["compounded"]) for p in per_ticker
                        if p.get("family") == "Jour" and p.get("compounded") == p.get("compounded")]
            night_pts = [(p["ticker"], p["compounded"]) for p in per_ticker
                          if p.get("family") == "Nuit" and p.get("compounded") == p.get("compounded")]
            self.rings.set_rings(
                day_pts, night_pts,
                crossover=bool(getattr(self, "_crossover", False)),
                animate=not partial,
            )

        # Update per-ticker detail table.
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

        # Reapply the user's current sort so re-population during optimization
        # doesn't yank the table back to insertion order.
        if hasattr(self, "_detail_sort"):
            self._resort_detail()

        if not rows and not partial:
            self.status.set("Aucun créneau exploitable sur cette plage pour ces titres.")
            return
        if not partial:
            best_row = rows[0] if rows else None
            if best_row:
                self.status.set(
                    f"Terminé. Meilleur créneau global : {best_row['slot']} "
                    f"({best_row['compounded']:+.2f}% composé) sur {days_back} jours."
                )
