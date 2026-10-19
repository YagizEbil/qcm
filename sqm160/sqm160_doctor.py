from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

OK, WARN, FAIL, INFO = "ok", "warning", "problem", "info"

PROLIFIC_HELP_WINDOWS = (
    "In Device Manager, under 'Ports (COM & LPT)', the entry should read "
    "'Prolific USB-to-Serial Comm Port (COMx)'. If it shows a yellow warning "
    "triangle or says 'PHASED OUT SINCE 2012', Windows has installed the newest "
    "Prolific driver, which refuses to work with this age of chip. The fix is to "
    "install driver version 3.3.2.102, which is the ser2pl.inf file next to this "
    "program."
)
PROLIFIC_HELP_MACOS = (
    "macOS needs Prolific's own driver. Install 'PL2303 Serial' from the Mac App "
    "Store (free, by Prolific Technology), then allow it in System Settings > "
    "Privacy & Security and restart the Mac. Whether that App Store driver covers "
    "the older PL2303 chip in this instrument is not something we could confirm "
    "without the hardware - if the port still never appears, a USB-to-RS-232 "
    "adapter with an FTDI chip, into the instrument's RS-232 socket, always works."
)
PROLIFIC_HELP_LINUX = (
    "Linux has the driver built in; no installation is needed. If the port appears "
    "but cannot be opened, the user account is usually missing from the 'dialout' "
    "group: run  sudo usermod -a -G dialout $USER  and log out and back in."
)


@dataclass
class Check:
    name: str
    status: str
    message: str
    fix: str = ""
    action: str = ""
    data: dict = field(default_factory=dict)

    @property
    def icon(self) -> str:
        return {OK: "[ OK ]", WARN: "[ ?? ]", FAIL: "[FAIL]", INFO: "[ -- ]"}[self.status]


@dataclass
class Report:
    checks: list = field(default_factory=list)
    connected: bool = False
    port: str = ""
    baud: int = 0
    summary: str = ""

    def add(self, *args, **kwargs) -> Check:
        check = Check(*args, **kwargs)
        self.checks.append(check)
        return check

    @property
    def worst(self) -> str:
        for level in (FAIL, WARN, OK):
            if any(c.status == level for c in self.checks):
                return level
        return INFO

    def text(self) -> str:
        lines = ["SQM-160 connection check", "=" * 60,
                 time.strftime("%Y-%m-%d %H:%M:%S"), ""]
        for c in self.checks:
            lines.append(f"{c.icon} {c.name}")
            lines.append(f"       {c.message}")
            if c.fix:
                lines.append(f"       What to do: {c.fix}")
            lines.append("")
        lines.append(self.summary)
        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {"when": time.strftime("%Y-%m-%d %H:%M:%S"),
                "system": system_info(), "connected": self.connected,
                "port": self.port, "baud": self.baud, "summary": self.summary,
                "checks": [asdict(c) for c in self.checks]}

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")
        return path


def system_info() -> dict:
    return {"python": sys.version.split()[0], "platform": platform.platform(),
            "machine": platform.machine(), "executable": sys.executable}


def _run(command: list, timeout: float = 15.0) -> str:
    try:
        out = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (out.stdout or "") + (out.stderr or "")
    except Exception:
        return ""


def windows_serial_devices() -> list[dict]:
    if platform.system() != "Windows":
        return []
    script = ("Get-PnpDevice -Class Ports -ErrorAction SilentlyContinue | "
              "Select-Object FriendlyName,Status,InstanceId,Problem | ConvertTo-Json -Compress")
    raw = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])
    start = raw.find("[") if "[" in raw else raw.find("{")
    if start < 0:
        return []
    try:
        data = json.loads(raw[start:raw.rfind("]") + 1 if "[" in raw else raw.rfind("}") + 1])
    except ValueError:
        return []
    return data if isinstance(data, list) else [data]


def macos_prolific_driver() -> bool | None:
    if platform.system() != "Darwin":
        return None
    text = _run(["kextstat"]) + _run(["systemextensionsctl", "list"])
    if not text:
        return None
    return "prolific" in text.lower() or "pl2303" in text.lower()


def linux_serial_permission(device: str) -> str:
    try:
        return "ok" if os.access(device, os.R_OK | os.W_OK) else "denied"
    except OSError:
        return "unknown"


def install_windows_driver(inf_path: str | Path) -> tuple[bool, str]:
    inf = Path(inf_path).resolve()
    if platform.system() != "Windows":
        return False, "This fix only applies to Windows."
    if not inf.is_file():
        return False, f"The driver file was not found: {inf}"
    command = (f"Start-Process pnputil -ArgumentList '/add-driver',"
               f"'\"{inf}\"','/install' -Verb RunAs -Wait")
    out = _run(["powershell", "-NoProfile", "-Command", command], timeout=180)
    if "denied" in out.lower() or "canceled" in out.lower():
        return False, ("Windows did not get permission to install the driver. "
                       "Press Yes on the Windows prompt, or ask whoever has the "
                       "administrator password on this computer.")
    return True, ("The driver was sent to Windows for installation. Unplug the "
                  "instrument's USB cable, plug it back in, and try again.")


def run_checks(*, try_connect: bool = True, progress=None, inf_path: str | Path | None = None) -> Report:
    say = progress or (lambda _m: None)
    report = Report()
    system = platform.system()

    say("Checking Python...")
    if sys.version_info >= (3, 9):
        report.add("Python version", OK, f"Python {sys.version.split()[0]} - fine.")
    else:
        report.add("Python version", FAIL,
                   f"Python {sys.version.split()[0]} is too old for this program.",
                   "Install Python 3.9 or newer from python.org, then start the program again.")

    say("Checking the serial library...")
    try:
        import serial
        report.add("Serial library", OK, "The 'pyserial' package is installed.")
    except ImportError:
        report.add("Serial library", FAIL,
                   "The 'pyserial' package is missing, so no serial port can be opened.",
                   "Run:  pip install pyserial   (or start the program with the "
                   "'Start SQM-160' shortcut, which installs it for you).",
                   action="install_pyserial")
        report.summary = "Stopped early: the serial library is missing."
        return report

    say("Listing serial ports...")
    from sqm160 import list_candidates

    candidates = list_candidates()
    prolific = [c for c in candidates if c.is_prolific]
    listing = ", ".join(f"{c.device} ({c.description or c.ids})" for c in candidates)
    if not candidates:
        report.add("Serial ports", FAIL,
                   "This computer is not showing any serial ports at all.",
                   "Check that the USB cable is plugged into both the computer and the "
                   "SQM-160, and that the instrument is switched on. Then press Check again.",
                   data={"ports": []})
    elif prolific:
        report.add("Serial ports", OK,
                   f"Found the instrument's USB chip: {prolific[0].device} "
                   f"({prolific[0].description or 'Prolific PL2303'}).",
                   data={"ports": listing})
    else:
        report.add("Serial ports", WARN,
                   f"Serial ports exist but none of them is the SQM-160's Prolific chip. "
                   f"Found: {listing}.",
                   "If the instrument is connected by USB, this usually means the USB "
                   "driver is missing or the cable is in the wrong socket. "
                   "If it is connected through an RS-232 adapter instead, that is fine - "
                   "the program will try every port.",
                   data={"ports": listing})

    say("Checking the USB driver...")
    if system == "Windows":
        devices = windows_serial_devices()
        broken = [d for d in devices
                  if str(d.get("Status", "")).upper() not in ("OK", "UNKNOWN")
                  or d.get("Problem") not in (None, 0, "CM_PROB_NONE")]
        phased = [d for d in devices if "PHASED OUT" in str(d.get("FriendlyName", "")).upper()]
        if phased:
            report.add("Windows USB driver", FAIL,
                       "Windows has loaded the newest Prolific driver, which deliberately "
                       "refuses to work with the chip inside this instrument. This is the "
                       "single most common reason the SQM-160 will not connect on Windows.",
                       PROLIFIC_HELP_WINDOWS, action="install_driver",
                       data={"devices": phased})
        elif broken:
            names = ", ".join(str(d.get("FriendlyName", "?")) for d in broken)
            report.add("Windows USB driver", WARN,
                       f"Windows reports a problem with: {names}.",
                       PROLIFIC_HELP_WINDOWS, action="install_driver",
                       data={"devices": broken})
        elif devices:
            report.add("Windows USB driver", OK,
                       "Windows reports every serial port as working normally.")
        else:
            report.add("Windows USB driver", INFO,
                       "Could not ask Windows about the driver (PowerShell did not answer). "
                       "This is not itself a problem.")
    elif system == "Darwin":
        loaded = macos_prolific_driver()
        if loaded is True:
            report.add("macOS USB driver", OK, "A Prolific driver is loaded.")
        elif loaded is False:
            report.add("macOS USB driver", WARN,
                       "No Prolific driver appears to be loaded on this Mac.",
                       PROLIFIC_HELP_MACOS, data={"help": PROLIFIC_HELP_MACOS})
        else:
            report.add("macOS USB driver", INFO,
                       "Could not tell whether a Prolific driver is loaded.",
                       PROLIFIC_HELP_MACOS)
    else:
        denied = [c.device for c in candidates
                  if linux_serial_permission(c.device) == "denied"]
        if denied:
            report.add("Port permissions", FAIL,
                       f"This user account is not allowed to open {', '.join(denied)}.",
                       PROLIFIC_HELP_LINUX, action="linux_group")
        else:
            report.add("Port permissions", OK,
                       "The serial ports can be opened by this user account.")

    say("Checking whether another program has the port...")
    busy = []
    for c in candidates:
        try:
            serial.Serial(c.device).close()
        except Exception as exc:
            text = str(exc).lower()
            if "access is denied" in text or "permission" in text or "busy" in text:
                busy.append(c.device)
    if busy:
        report.add("Port in use", FAIL,
                   f"Another program is already using {', '.join(busy)}. A serial port "
                   "can only be open in one program at a time.",
                   "Close INFICON's Comm software (and any other copy of this program), "
                   "then press Check again.")
    elif candidates:
        report.add("Port in use", OK, "No other program is holding the ports open.")

    if try_connect and candidates:
        say("Trying to talk to the instrument...")
        from sqm160 import SQM160Error, SQM160NotFound, discover

        try:
            port, baud = discover(progress=say)
            report.connected, report.port, report.baud = True, port, baud
            report.add("Instrument", OK,
                       f"The SQM-160 answered on {port} at {baud} baud.",
                       data={"port": port, "baud": baud})
        except SQM160NotFound as exc:
            report.add("Instrument", FAIL, str(exc), exc.detail)
        except SQM160Error as exc:
            report.add("Instrument", FAIL, f"The instrument did not answer: {exc}")
        except Exception as exc:
            report.add("Instrument", FAIL, f"Unexpected error while connecting: {exc}")

    if report.connected:
        report.summary = (f"All good. The SQM-160 is on {report.port} at {report.baud} baud "
                          "and the program will find it by itself from now on.")
    else:
        causes = [c for c in report.checks if c.fix and c.name != "Instrument"
                  and c.status in (FAIL, WARN)]
        causes.sort(key=lambda c: 0 if c.status == FAIL else 1)
        if causes:
            report.summary = f"Most likely cause: {causes[0].name.lower()}. {causes[0].fix}"
        else:
            report.summary = ("The instrument was not found, and no obvious cause showed up. "
                              "Check that the SQM-160 is switched on, that its USB cable is "
                              "connected, and that the BAUDRATE in its System menu is 19200.")
    return report


def bundled_inf() -> Path | None:
    here = Path(__file__).resolve().parent
    for name in ("ser2pl.inf", "driver/ser2pl.inf"):
        if (here / name).is_file():
            return here / name
    return None


def _main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    fix = "--fix-driver" in sys.argv
    report = run_checks(progress=lambda m: print(f"  ... {m}"))
    print()
    print(report.text())
    if fix and any(c.action == "install_driver" for c in report.checks):
        inf = bundled_inf()
        if inf:
            ok, message = install_windows_driver(inf)
            print(("Driver: " if ok else "Driver (not done): ") + message)
    path = Path.home() / ".sqm160" / "last-check.json"
    try:
        report.save(path)
        print(f"\nA copy of this check was saved to {path}")
    except OSError:
        pass
    return 0 if report.connected else 1


if __name__ == "__main__":
    raise SystemExit(_main())
