"""Launch animation: Bonne fête Simon 2026 (August 2026 only)."""

from __future__ import annotations

import math
import random
from datetime import date
from tkinter import Canvas, Tk, Toplevel


MESSAGE = "Bonne fête Simon 2026"
DISPLAY_MESSAGE = "Bonne fête Simon 2026"

# The birthday greeting only appears during August 2026.
# After September 1, 2026 the app launches directly, no splash.
CELEBRATION_YEAR = 2026
CELEBRATION_MONTH = 8


def _is_celebration_period(today: date | None = None) -> bool:
    today = today or date.today()
    return today.year == CELEBRATION_YEAR and today.month == CELEBRATION_MONTH


class BirthdaySplash:
    def __init__(self, master: Tk, on_close) -> None:
        self.master = master
        self.on_close = on_close
        self.win = Toplevel(master)
        self.win.title("Overnight Edge")
        self.win.geometry("920x560")
        self.win.configure(bg="#070b14")
        self.win.protocol("WM_DELETE_WINDOW", self._finish)
        self.win.lift()
        self.win.focus_force()
        try:
            self.win.attributes("-topmost", True)
            self.win.after(1500, lambda: self.win.attributes("-topmost", False))
        except Exception:
            pass
        self.win.bind("<Escape>", lambda _e: self._finish())
        self.win.bind("<Return>", lambda _e: self._finish())

        self.canvas = Canvas(self.win, width=920, height=520, bg="#070b14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        btn = Canvas(self.win, height=40, bg="#070b14", highlightthickness=0)
        btn.pack(fill="x")
        self._skip_id = btn.create_text(
            460, 18, text="Continuer vers Overnight Edge  →", fill="#f8e38c", font=("Segoe UI", 12, "bold")
        )
        btn.bind("<Button-1>", lambda _e: self._finish())
        btn.bind("<Enter>", lambda _e: btn.itemconfig(self._skip_id, fill="#ffffff"))
        btn.bind("<Leave>", lambda _e: btn.itemconfig(self._skip_id, fill="#f8e38c"))

        self.w, self.h = 920, 520
        self.t = 0
        self.confetti = [
            {
                "x": random.uniform(0, self.w),
                "y": random.uniform(-self.h, 0),
                "vy": random.uniform(2.2, 5.5),
                "vx": random.uniform(-1.2, 1.2),
                "size": random.randint(5, 11),
                "color": random.choice(["#f43f5e", "#fbbf24", "#38bdf8", "#a78bfa", "#34d399", "#fb7185"]),
                "spin": random.uniform(-0.2, 0.2),
                "angle": random.uniform(0, 6.28),
            }
            for _ in range(90)
        ]
        self.balloons = [
            {
                "x": 80 + i * 95,
                "y": 420 + (i % 3) * 30,
                "vy": random.uniform(0.6, 1.3),
                "color": random.choice(["#fb7185", "#60a5fa", "#facc15", "#c084fc", "#4ade80"]),
            }
            for i in range(9)
        ]
        self.title_id = None
        self.sub_id = None
        self._closed = False
        self._tick()
        self.win.update_idletasks()
        width, height = 920, 560
        x = max(0, (self.win.winfo_screenwidth() - width) // 2)
        y = max(0, (self.win.winfo_screenheight() - height) // 2)
        self.win.geometry(f"{width}x{height}+{x}+{y}")
        self.win.after(9000, self._finish)

    def _tick(self) -> None:
        if self._closed:
            return
        self.canvas.delete("all")
        self.t += 1

        # soft glow
        pulse = 0.55 + 0.45 * math.sin(self.t / 12)
        glow = int(30 + 40 * pulse)
        self.canvas.create_oval(
            260, 80, 660, 320,
            fill=f"#{glow:02x}{int(glow*0.4):02x}{int(glow*0.15):02x}",
            outline="",
        )

        for b in self.balloons:
            b["y"] -= b["vy"]
            if b["y"] < -40:
                b["y"] = 540
            x, y = b["x"], b["y"]
            self.canvas.create_oval(x - 22, y - 30, x + 22, y + 18, fill=b["color"], outline="")
            self.canvas.create_line(x, y + 18, x, y + 70, fill="#94a3b8")

        for c in self.confetti:
            c["y"] += c["vy"]
            c["x"] += c["vx"]
            c["angle"] += c["spin"]
            if c["y"] > self.h:
                c["y"] = -10
                c["x"] = random.uniform(0, self.w)
            s = c["size"]
            self.canvas.create_rectangle(
                c["x"], c["y"], c["x"] + s, c["y"] + s * 0.6,
                fill=c["color"], outline="",
            )

        scale = 1.0 + 0.04 * math.sin(self.t / 8)
        size = int(36 * scale)
        self.canvas.create_text(
            460, 210,
            text=DISPLAY_MESSAGE,
            fill="#fde68a",
            font=("Segoe UI", size, "bold"),
        )
        self.canvas.create_text(
            460, 270,
            text="Overnight Edge  ·  Classement quotidien du S&P 500 (overnight)",
            fill="#cbd5e1",
            font=("Segoe UI", 14),
        )
        self.canvas.create_text(
            460, 310,
            text="Achat 16:00 (close)  →  vente 09:29 (pré-ouverture)  →  composition chaque nuit",
            fill="#94a3b8",
            font=("Segoe UI", 11),
        )
        self.win.after(33, self._tick)

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.win.grab_release()
        except Exception:
            pass
        try:
            self.win.destroy()
        except Exception:
            pass
        self.on_close()


def show_birthday_then(master: Tk, start_app) -> None:
    # Outside August 2026, skip the birthday splash and start the app directly.
    if not _is_celebration_period():
        start_app()
        return

    master.withdraw()
    try:
        master.update_idletasks()
    except Exception:
        pass

    started = {"done": False}

    def _go() -> None:
        if started["done"]:
            return
        started["done"] = True
        try:
            master.deiconify()
            master.lift()
        except Exception:
            pass
        start_app()

    try:
        BirthdaySplash(master, on_close=_go)
    except Exception:
        _go()
