from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

from sqm160_engine import Monitor, RunInfo, Sample

TXT_COLUMNS = ("Time_s", "Rate", "Thickness", "Shutter", "Deposit_s")
TXT_SENSOR_COLUMNS = ("Freq{i}", "Rate{i}", "Thick{i}")


def _timestamp(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))


def safe_name(text: str) -> str:
    keep = [c if (c.isalnum() or c in "-_. ") else "_" for c in text.strip()]
    name = "".join(keep).strip(". ") or "run"
    return name[:80]


def default_log_dir() -> Path:
    for candidate in (Path.home() / "Documents", Path.home()):
        if candidate.is_dir():
            return candidate / "SQM-160 logs"
    return Path.cwd() / "SQM-160 logs"


class LogWriter:

    def __init__(self, path: str | Path, fmt: str = "csv", *, sensors: int = 1,
                 film=None, capabilities=None, run: RunInfo | None = None,
                 note: str = ""):
        self.path = Path(path)
        self.fmt = fmt.lower().lstrip(".")
        if self.fmt not in ("csv", "txt"):
            raise ValueError("fmt must be 'csv' or 'txt'")
        self.sensors = max(1, sensors)
        self.film = film
        self.capabilities = capabilities
        self.run = run
        self.note = note
        self.rows = 0
        self._fh = None
        self._csv = None

    def open(self) -> "LogWriter":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("w", newline="", encoding="utf-8")
        if self.fmt == "csv":
            self._csv = csv.writer(self._fh)
            self._csv.writerow(self._csv_header())
        else:
            self._fh.write(self._txt_header())
        self._fh.flush()
        return self

    def close(self) -> None:
        if self._fh:
            if self.fmt == "txt":
                self._fh.write(f"\n# Finished {_timestamp(time.time())}, {self.rows} readings\n")
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "LogWriter":
        return self.open() if self._fh is None else self

    def __exit__(self, *exc) -> None:
        self.close()

    def _csv_header(self) -> list:
        head = ["timestamp", "unix_time", "elapsed_s", "deposit_s",
                "avg_rate_A_per_s", "avg_thickness_kA", "shutter_open"]
        for i in range(1, self.sensors + 1):
            head += [f"rate{i}_A_per_s", f"thickness{i}_kA", f"frequency{i}_Hz",
                     f"life{i}_percent"]
        return head

    def _txt_header(self) -> str:
        lines = ["INFICON SQM-160 deposition log",
                 f"Started          {_timestamp(time.time())}"]
        if self.run and self.run.label:
            lines.append(f"Run              {self.run.label}")
        if self.note:
            lines.append(f"Note             {self.note}")
        if self.film is not None:
            lines += [
                f"Film             {self.film.name}",
                f"Density          {self.film.density:.2f} g/cm3",
                f"Tooling          {self.film.tooling} %",
                f"Z-Ratio          {self.film.z_ratio:.3f}",
                f"Final thickness  {self.film.final_thickness:.3f} kA",
                f"Sensors          {', '.join(str(s) for s in self.film.sensors)}",
            ]
        if self.capabilities is not None:
            lines.append(f"Instrument       {self.capabilities.summary()}")
        lines += [
            "",
            "Rate in A/s, thickness in kA, frequency in Hz, time in seconds.",
            "Columns: time, average rate, average thickness, shutter (1 = open), "
            "deposition time,",
            f"then frequency, rate and thickness for each of the {self.sensors} sensor(s).",
            "",
        ]
        header = "\t".join(TXT_COLUMNS)
        per_sensor = "".join("\t" + "\t".join(c.format(i=i) for c in TXT_SENSOR_COLUMNS)
                             for i in range(1, self.sensors + 1))
        return "\n".join(lines) + header + per_sensor + "\n"

    def write(self, sample: Sample) -> None:
        if self._fh is None:
            self.open()
        if self.fmt == "csv":
            row = [_timestamp(sample.t), f"{sample.t:.3f}", f"{sample.elapsed:.2f}",
                   f"{sample.deposit_time:.2f}", f"{sample.avg_rate:.3f}",
                   f"{sample.avg_thickness:.5f}", int(sample.shutter)]
            for i in range(self.sensors):
                row += [_fmt(sample.rates, i, 3), _fmt(sample.thicknesses, i, 5),
                        _fmt(sample.frequencies, i, 3), _fmt(sample.lives, i, 2)]
            self._csv.writerow(row)
        else:
            cells = [f"{sample.elapsed:.2f}", f"{sample.avg_rate:.3f}",
                     f"{sample.avg_thickness:.5f}", str(int(sample.shutter)),
                     f"{sample.deposit_time:.2f}"]
            for i in range(self.sensors):
                cells += [_num(sample.frequencies, i, 3), _num(sample.rates, i, 3),
                          _num(sample.thicknesses, i, 5)]
            self._fh.write("\t".join(cells) + "\n")
        self.rows += 1
        self._fh.flush()

    def attach(self, monitor: Monitor):
        def listener(event, payload):
            if event == "sample":
                try:
                    self.write(payload)
                except OSError:
                    pass
        self._listener = listener
        monitor.add_listener(listener)
        return listener

    def detach(self, monitor: Monitor) -> None:
        listener = getattr(self, "_listener", None)
        if listener:
            monitor.remove_listener(listener)


def _fmt(values, index: int, digits: int) -> str:
    try:
        value = values[index]
    except (IndexError, TypeError):
        return ""
    return "" if value != value else f"{value:.{digits}f}"


def _num(values, index: int, digits: int) -> str:
    try:
        value = values[index]
    except (IndexError, TypeError):
        return f"{0:.{digits}f}"
    return f"{0:.{digits}f}" if value != value else f"{value:.{digits}f}"


def export_samples(samples, path: str | Path, fmt: str = "csv", **kwargs) -> Path:
    sensors = max((len(s.rates) for s in samples), default=1)
    writer = LogWriter(path, fmt, sensors=sensors, **kwargs)
    with writer:
        for sample in samples:
            writer.write(sample)
    return writer.path


def export_run_settings(path: str | Path, *, run: RunInfo | None = None, film=None,
                        system1=None, system2=None, capabilities=None,
                        extra: dict | None = None) -> Path:
    data = {
        "written": _timestamp(time.time()),
        "run": {k: v for k, v in asdict(run).items() if k != "film"} if run else None,
        "film": asdict(film) if film else None,
        "system1": asdict(system1) if system1 else None,
        "system2": asdict(system2) if system2 else None,
        "instrument": asdict(capabilities) if capabilities else None,
    }
    if extra:
        data.update(extra)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def read_csv(path: str | Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def plot_samples(samples, path: str | Path, *, title: str = "SQM-160 run",
                 dpi: int = 150) -> Path:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RuntimeError(
            "Saving a picture of the graph needs the 'matplotlib' package, which is "
            "not installed. The data can still be saved as CSV.") from exc

    if not samples:
        raise RuntimeError("There is nothing to plot yet.")

    t0 = samples[0].t
    minutes = [(s.t - t0) / 60 for s in samples]
    rate = [s.avg_rate for s in samples]
    thickness = [s.avg_thickness for s in samples]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(minutes, rate, color="#1f77b4", linewidth=1.2, label="Rate")
    ax.set_xlabel("Time (minutes)")
    ax.set_ylabel("Rate (Å/s)", color="#1f77b4")
    ax.tick_params(axis="y", labelcolor="#1f77b4")
    ax.grid(alpha=0.3)

    ax2 = ax.twinx()
    ax2.plot(minutes, thickness, color="#d62728", linewidth=1.4, label="Thickness")
    ax2.set_ylabel("Thickness (kÅ)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")

    start = None
    for m, s in zip(minutes, samples):
        if s.shutter and start is None:
            start = m
        elif not s.shutter and start is not None:
            ax.axvspan(start, m, color="#2ca02c", alpha=0.08)
            start = None
    if start is not None:
        ax.axvspan(start, minutes[-1], color="#2ca02c", alpha=0.08)

    ax.set_title(title)
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
    return path
