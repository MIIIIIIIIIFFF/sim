"""Overnight Edge Windows installer (no third-party compiler required)."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox, ttk


APP_NAME = "Overnight Edge"
EXE_NAME = "OvernightEdge.exe"


def bundled_exe() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # noqa: SLF001
        candidate = base / EXE_NAME
        if candidate.exists():
            return candidate
        return Path(sys.executable).resolve().parent / EXE_NAME
    return Path(__file__).resolve().parent.parent / "dist" / EXE_NAME


def bundled_file(name: str) -> Path | None:
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys._MEIPASS) / name)  # noqa: SLF001
        candidates.append(Path(sys.executable).resolve().parent / name)
    root = Path(__file__).resolve().parent.parent
    candidates.extend(
        [
            root / name,
            root / "FOR_THE_BOSS.md" if name == "FOR_THE_BOSS.md" else root / name,
        ]
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home() / "AppData" / "Local"
    return base / "Programs" / APP_NAME


def user_start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME


def appdata_working_dir() -> Path:
    appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
    path = Path(appdata) / "OvernightEdge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def create_shortcut(link_path: Path, target: Path, working_dir: Path) -> None:
    link_path.parent.mkdir(parents=True, exist_ok=True)
    command = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({_ps_quote(link_path)}); "
        f"$s.TargetPath = {_ps_quote(target)}; "
        f"$s.WorkingDirectory = {_ps_quote(working_dir)}; "
        f"$s.IconLocation = {_ps_quote(target)}; "
        f"$s.Save()"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
            check=False,
        )
        if completed.returncode == 0 and link_path.exists():
            return
    except Exception:
        pass
    bat = link_path.with_suffix(".bat")
    bat.write_text(f'@echo off\nstart "" "{target}"\n', encoding="ascii")


def write_uninstaller(install_dir: Path, exe_path: Path) -> None:
    desktop_lnk = Path.home() / "Desktop" / f"{APP_NAME}.lnk"
    desktop_bat = Path.home() / "Desktop" / f"{APP_NAME}.bat"
    start_menu = user_start_menu_dir()
    script = install_dir / "Uninstall.bat"
    script.write_text(
        "\n".join(
            [
                "@echo off",
                "echo Désinstallation d'Overnight Edge...",
                f'del /q "{desktop_lnk}" 2>nul',
                f'del /q "{desktop_bat}" 2>nul',
                f'del /q "{start_menu}\\*.lnk" 2>nul',
                f'del /q "{start_menu}\\*.bat" 2>nul',
                f'rmdir "{start_menu}" 2>nul',
                f'del /q "{exe_path}" 2>nul',
                f'del /q "{install_dir}\\LICENSE.txt" 2>nul',
                f'del /q "{install_dir}\\LISEZ_MOI.txt" 2>nul',
                f'del /q "{install_dir}\\Uninstall.bat" 2>nul',
                f'rmdir /s /q "{install_dir}" 2>nul',
                'if exist "{install_dir}" echo Note : certains fichiers du dossier d\'installation n\'ont pas pu être supprimés.',
                "echo Terminé. L'historique des scans dans %APPDATA%\\OvernightEdge a été conservé.",
                "pause",
            ]
        ),
        encoding="ascii",
    )


class InstallerApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        root.title("Installer Overnight Edge")
        root.geometry("580x400")
        root.resizable(False, False)
        self.dest = StringVar(value=str(default_install_dir()))
        self.desktop = BooleanVar(value=True)
        self.status = StringVar(
            value="Installation pour cet utilisateur Windows. Aucun Python requis. Internet requis pour le scan."
        )

        pad = {"padx": 16, "pady": 6}
        ttk.Label(root, text="Installation d'Overnight Edge", font=("Segoe UI", 16, "bold")).pack(anchor="w", **pad)
        ttk.Label(
            root,
            text=(
                "Scanner quotidien du S&P 500 (overnight) : achat 16:00 (close), vente 09:29 le lendemain, "
                "composition chaque nuit. Message d'anniversaire : Bonne fête Simon 2026."
            ),
            wraplength=540,
        ).pack(anchor="w", padx=16)

        ttk.Label(root, text="Dossier d'installation (aucun droit administrateur requis)").pack(
            anchor="w", padx=16, pady=(12, 0)
        )
        ttk.Entry(root, textvariable=self.dest, width=72).pack(fill="x", padx=16)
        ttk.Checkbutton(root, text="Créer un raccourci sur le Bureau", variable=self.desktop).pack(
            anchor="w", padx=16, pady=8
        )
        ttk.Label(root, textvariable=self.status, wraplength=540).pack(anchor="w", padx=16)
        ttk.Label(
            root,
            text="Si Windows SmartScreen apparaît : Plus d'infos → Exécuter quand même.",
            wraplength=540,
        ).pack(anchor="w", padx=16, pady=(4, 0))
        btns = ttk.Frame(root)
        btns.pack(fill="x", padx=16, pady=16)
        self.install_btn = ttk.Button(btns, text="Installer", command=self._install)
        self.install_btn.pack(side="left")
        ttk.Button(btns, text="Annuler", command=root.destroy).pack(side="left", padx=8)

    def _install(self) -> None:
        self.install_btn.configure(state="disabled")
        src = bundled_exe()
        if not src.exists():
            self.install_btn.configure(state="normal")
            messagebox.showerror("Application introuvable", f"Impossible de trouver {EXE_NAME}.")
            return
        dest_dir = Path(self.dest.get().strip())
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_exe = dest_dir / EXE_NAME
            dest_exe.write_bytes(src.read_bytes())

            license_src = bundled_file("LICENSE.txt")
            if license_src is not None:
                (dest_dir / "LICENSE.txt").write_bytes(license_src.read_bytes())

            readme = bundled_file("FOR_THE_BOSS.md")
            if readme is not None:
                (dest_dir / "LISEZ_MOI.txt").write_text(readme.read_text(encoding="utf-8"), encoding="utf-8")

            write_uninstaller(dest_dir, dest_exe)
            work = appdata_working_dir()
            create_shortcut(user_start_menu_dir() / f"{APP_NAME}.lnk", dest_exe, work)
            if self.desktop.get():
                create_shortcut(Path.home() / "Desktop" / f"{APP_NAME}.lnk", dest_exe, work)
        except PermissionError:
            self.install_btn.configure(state="normal")
            messagebox.showerror(
                "Dossier non accessible en écriture",
                "Choisissez un dossier où vous pouvez écrire, ou gardez le dossier par défaut dans votre profil.\n"
                "« Program Files » nécessite « Exécuter en tant qu'administrateur ».",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.install_btn.configure(state="normal")
            messagebox.showerror("Échec de l'installation", f"{exc}\n\n{traceback.format_exc()[-500:]}")
            return

        self.status.set(f"Installé dans {dest_dir}")
        if messagebox.askyesno("Installé", "Overnight Edge est installé. Lancer maintenant ?"):
            os.startfile(str(dest_exe))  # noqa: S606
        self.root.destroy()


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    root = Tk()
    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    try:
        InstallerApp(root)
        root.mainloop()
    except Exception as exc:  # noqa: BLE001
        try:
            messagebox.showerror("Échec de l'installateur", str(exc))
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    raise SystemExit(main())
