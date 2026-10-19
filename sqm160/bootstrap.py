from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
HOME = Path(os.environ.get("SQM160_HOME", Path.home() / ".sqm160"))


def venv_dir() -> Path:
    override = os.environ.get("SQM160_VENV")
    if override:
        return Path(override)
    parent = APP_DIR.parent
    if (parent / ".venv").exists() or (parent / ".git").exists():
        return parent / ".venv"
    return HOME / "venv"


VENV = venv_dir()
MARKER = "SQM160_BOOTSTRAPPED"
REQUIREMENTS = ["pyserial>=3.5", "PySide6-Essentials>=6.5", "pyqtgraph>=0.13",
                "matplotlib>=3.5"]
FALLBACK = {"PySide6-Essentials>=6.5": "PySide6>=6.5"}
MIN_PYTHON = (3, 9)


class Progress:
    def __init__(self, title: str = "Setting up the SQM-160 program"):
        self.gui = None
        try:
            import tkinter as tk
            from tkinter import ttk

            self.tk = tk
            self.root = tk.Tk()
            self.root.title(title)
            self.root.geometry("520x170")
            self.root.resizable(False, False)
            frame = ttk.Frame(self.root, padding=18)
            frame.pack(fill="both", expand=True)
            self.heading = ttk.Label(frame, text="Getting things ready",
                                     font=("", 13, "bold"))
            self.heading.pack(anchor="w")
            self.label = ttk.Label(frame, text="This happens once and takes a few minutes.",
                                   wraplength=470, justify="left")
            self.label.pack(anchor="w", pady=(8, 12))
            self.bar = ttk.Progressbar(frame, mode="indeterminate", length=470)
            self.bar.pack()
            self.bar.start(12)
            self.gui = True
            self.root.update()
        except Exception:
            self.gui = False

    def say(self, message: str) -> None:
        if self.gui:
            try:
                self.label.config(text=message)
                self.root.update()
                return
            except Exception:
                self.gui = False
        print(message, flush=True)

    def pump(self) -> None:
        if self.gui:
            try:
                self.root.update()
            except Exception:
                self.gui = False

    def close(self) -> None:
        if self.gui:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.gui = False


def show_error(title: str, message: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:
        print(f"\n{title}\n{'-' * len(title)}\n{message}\n", file=sys.stderr)
        try:
            input("Press Enter to close this window. ")
        except Exception:
            pass


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "pythonw.exe"
    return VENV / "bin" / "python"


def venv_python_console() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def have_everything() -> bool:
    try:
        import PySide6
        import pyqtgraph
        import serial
        return True
    except ImportError:
        return False


def pip_install(python: Path, packages: list, progress: Progress) -> str:
    for package in packages:
        progress.say(f"Installing {package.split('>')[0]}…")
        done = {}

        def work(pkg=package):
            try:
                out = subprocess.run(
                    [str(python), "-m", "pip", "install", "--disable-pip-version-check",
                     "--quiet", pkg],
                    capture_output=True, text=True, timeout=1800,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                done["code"], done["out"] = out.returncode, (out.stdout or "") + (out.stderr or "")
            except Exception as exc:
                done["code"], done["out"] = 1, str(exc)

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        while thread.is_alive():
            progress.pump()
            thread.join(0.1)
        if done.get("code"):
            alternative = FALLBACK.get(package)
            if alternative:
                progress.say(f"Trying {alternative.split('>')[0]} instead…")
                result = pip_install(python, [alternative], progress)
                if not result:
                    continue
            return (f"Could not install {package}.\n\n{done.get('out', '')[-800:]}")
    return ""


def make_environment(progress: Progress) -> tuple[Path | None, str]:
    python = venv_python_console()
    if not python.exists():
        progress.say("Making a private Python environment (this happens once)…")
        try:
            HOME.mkdir(parents=True, exist_ok=True)
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True,
                           capture_output=True, timeout=600)
        except Exception as exc:
            return None, (
                "A private Python environment could not be created.\n\n"
                f"{exc}\n\nThe program can still be started from a terminal with:\n"
                f"    pip install pyserial PySide6 pyqtgraph matplotlib\n"
                f"    python \"{APP_DIR / 'sqm160_gui.py'}\"")
    error = pip_install(python, REQUIREMENTS, progress)
    if error:
        return None, (error + "\n\nThis usually means the computer has no internet "
                      "connection, or a firewall is blocking it. The program can still "
                      "run on another computer and read a saved log file.")
    return python, ""


def launch(python: Path, args: list) -> int:
    env = dict(os.environ, **{MARKER: "1"})
    gui_python = venv_python() if venv_python().exists() else python
    command = [str(gui_python), str(APP_DIR / "sqm160_cli.py")] + args
    try:
        return subprocess.call(command, env=env, cwd=str(APP_DIR))
    except Exception as exc:
        show_error("Could not start the program", str(exc))
        return 1


def main() -> int:
    args = sys.argv[1:] or ["gui"]

    if sys.version_info < MIN_PYTHON:
        show_error(
            "Python is too old",
            f"This program needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer, but the "
            f"Python on this computer is {sys.version.split()[0]}.\n\n"
            "Install the latest Python from python.org (tick 'Add Python to PATH' "
            "during installation), then start the program again.")
        return 1

    if os.environ.get(MARKER) or have_everything():
        sys.path.insert(0, str(APP_DIR))
        os.environ[MARKER] = "1"
        from sqm160_cli import main as cli_main

        return cli_main(args)

    progress = Progress()
    progress.say("Checking what is installed…")
    python, error = make_environment(progress)
    progress.close()
    if error:
        show_error("Setup did not finish", error)
        return 1
    return launch(python, args)


if __name__ == "__main__":
    raise SystemExit(main())
