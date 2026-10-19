from __future__ import annotations

import enum
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict

from sqm160 import (Capabilities, Film, InficonSQM160, SQM160ConnectionLost, SQM160Error,
                    SQM160NotFound, SQM160Timeout, SensorReading)


class State(enum.Enum):

    STOPPED = "stopped"
    SEARCHING = "searching"
    CONNECTED = "connected"
    LOST = "lost"

    @property
    def label(self) -> str:
        return {
            State.STOPPED: "Not started",
            State.SEARCHING: "Looking for the SQM-160...",
            State.CONNECTED: "Connected",
            State.LOST: "Connection lost - trying again",
        }[self]


@dataclass
class Sample:

    t: float
    elapsed: float
    deposit_time: float
    rates: list = field(default_factory=list)
    thicknesses: list = field(default_factory=list)
    frequencies: list = field(default_factory=list)
    lives: list = field(default_factory=list)
    avg_rate: float = 0.0
    avg_thickness: float = 0.0
    shutter: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunInfo:

    label: str = ""
    started: float = 0.0
    stopped: float | None = None
    film_number: int = 0
    film: Film | None = None

    @property
    def active(self) -> bool:
        return self.started > 0 and self.stopped is None


def default_connector(progress=None) -> InficonSQM160:
    return InficonSQM160.autoconnect(progress=progress)


def emulator_connector(progress=None) -> InficonSQM160:
    from sqm160_emulator import FakeSQM160

    if progress:
        progress("Starting the built-in demo instrument...")
    sqm = InficonSQM160(transport=FakeSQM160(), timeout=0.5)
    sqm.port = "demo"
    sqm.probe()
    return sqm


class Monitor:

    def __init__(self, *, interval: float = 0.5, history_seconds: float = 7200,
                 connector=default_connector, auto_reconnect: bool = True,
                 slow_every: int = 20):
        self.interval = max(0.05, interval)
        self.history_seconds = history_seconds
        self.connector = connector
        self.auto_reconnect = auto_reconnect
        self.slow_every = slow_every

        self.sqm: InficonSQM160 | None = None
        self.state = State.STOPPED
        self.last_error = ""
        self.last_error_detail = ""
        self.capabilities = Capabilities()
        self.film_number = 0
        self.film: Film | None = None
        self.run = RunInfo()

        self._samples: deque[Sample] = deque()
        self._listeners: list = []
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._command_queue: list = []
        self._poll_count = 0
        self._rate_window: deque[float] = deque(maxlen=20)
        self._deposit_time = 0.0
        self._last_poll_t: float | None = None

    def add_listener(self, callback) -> None:
        with self._lock:
            self._listeners.append(callback)

    def remove_listener(self, callback) -> None:
        with self._lock:
            if callback in self._listeners:
                self._listeners.remove(callback)

    def _emit(self, event: str, payload=None) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(event, payload)
            except Exception:
                pass

    def _set_state(self, state: State, error: str = "", detail: str = "") -> None:
        with self._lock:
            changed = state is not self.state
            self.state = state
            if error:
                self.last_error, self.last_error_detail = error, detail
        if changed:
            self._emit("state", state)
        if error:
            self._emit("error", error)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sqm160-monitor",
                                        daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)
        if self.sqm:
            self.sqm.close()
            self.sqm = None
        self._set_state(State.STOPPED)

    @property
    def connected(self) -> bool:
        return self.state is State.CONNECTED

    @property
    def latest(self) -> Sample | None:
        with self._lock:
            return self._samples[-1] if self._samples else None

    def history(self, seconds: float | None = None) -> list[Sample]:
        with self._lock:
            samples = list(self._samples)
        if seconds is None or not samples:
            return samples
        cutoff = samples[-1].t - seconds
        return [s for s in samples if s.t >= cutoff]

    def clear_history(self) -> None:
        with self._lock:
            self._samples.clear()

    def submit(self, func, *args, **kwargs):
        done = threading.Event()
        box: dict = {}

        def job(sqm):
            try:
                box["value"] = func(sqm, *args, **kwargs)
            except Exception as exc:
                box["error"] = exc
            finally:
                done.set()

        with self._lock:
            self._command_queue.append(job)
        return _Result(done, box)

    def open_shutter(self):
        return self.submit(lambda s: s.open_shutter())

    def close_shutter(self):
        return self.submit(lambda s: s.close_shutter())

    def zero_thickness(self):
        self._rate_window.clear()
        return self.submit(lambda s: s.zero())

    def zero_timer(self):
        self._deposit_time = 0.0
        return self.submit(lambda s: s.zero_time())

    def set_active_film(self, number: int):
        return self.submit(lambda s, n=number: s.set_active_film(n))

    def start_run(self, label: str = "", *, zero: bool = True) -> RunInfo:
        if zero:
            self.zero_thickness()
            self.zero_timer()
        self.clear_history()
        self._deposit_time = 0.0
        self._rate_window.clear()
        self.run = RunInfo(label=label or time.strftime("run_%Y%m%d_%H%M%S"),
                           started=time.time(), film_number=self.film_number,
                           film=self.film)
        self._emit("run", self.run)
        return self.run

    def stop_run(self) -> RunInfo:
        if self.run.active:
            self.run.stopped = time.time()
            self._emit("run", self.run)
        return self.run

    @property
    def smoothed_rate(self) -> float:
        with self._lock:
            window = list(self._rate_window)
        return statistics.fmean(window) if window else 0.0

    def time_remaining(self) -> float | None:
        sample = self.latest
        film = self.film
        if not sample or not film or film.final_thickness <= 0:
            return None
        rate = self.smoothed_rate
        if rate <= 0.01:
            return None
        remaining_ka = film.final_thickness - sample.avg_thickness
        if remaining_ka <= 0:
            return 0.0
        return remaining_ka * 1000.0 / rate

    def _loop(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            if self.sqm is None:
                self._set_state(State.SEARCHING)
                try:
                    self.sqm = self.connector(progress=lambda m: self._emit("progress", m))
                except SQM160NotFound as exc:
                    self._set_state(State.SEARCHING, str(exc), getattr(exc, "detail", ""))
                except SQM160Error as exc:
                    self._set_state(State.SEARCHING, str(exc))
                except Exception as exc:
                    self._set_state(State.SEARCHING, f"{type(exc).__name__}: {exc}")
                if self.sqm is None:
                    if not self.auto_reconnect:
                        break
                    self._stop.wait(backoff)
                    backoff = min(10.0, backoff * 1.6)
                    continue
                backoff = 1.0
                self.capabilities = self.sqm.capabilities
                self._poll_count = 0
                self._last_poll_t = None
                self._set_state(State.CONNECTED)
                self._emit("capabilities", self.capabilities)

            started = time.monotonic()
            try:
                self._drain_commands()
                self._poll_once()
            except (SQM160ConnectionLost, OSError) as exc:
                self._drop_connection(f"The connection to the SQM-160 was lost ({exc}).")
            except SQM160Timeout as exc:
                self._drop_connection(f"The SQM-160 stopped answering ({exc}).")
            except SQM160Error as exc:
                self._emit("error", str(exc))
            wait = self.interval - (time.monotonic() - started)
            if wait > 0:
                self._stop.wait(wait)

    def _drop_connection(self, message: str) -> None:
        if self.sqm:
            self.sqm.close()
        self.sqm = None
        self._set_state(State.LOST, message)
        if not self.auto_reconnect:
            self._stop.set()

    def _drain_commands(self) -> None:
        while True:
            with self._lock:
                if not self._command_queue:
                    return
                job = self._command_queue.pop(0)
            job(self.sqm)

    def _poll_once(self) -> None:
        sqm = self.sqm
        assert sqm is not None
        now = time.time()
        self._poll_count += 1
        slow = self._poll_count % self.slow_every == 1

        try:
            readings = sqm.read_all()
        except SQM160Error:
            readings = self._read_each(sqm)

        rates = [r.rate for r in readings]
        thicknesses = [r.thickness for r in readings]
        frequencies = [r.frequency for r in readings]

        shutter = sqm.shutter_is_open()
        avg_rate = sqm.avg_rate()
        avg_thickness = sqm.avg_thickness()

        lives = self._lives if hasattr(self, "_lives") else []
        if slow or not lives:
            lives = []
            for i in range(1, len(readings) + 1):
                try:
                    lives.append(sqm.crystal_life(i))
                except SQM160Error:
                    lives.append(float("nan"))
            self._lives = lives
            self._refresh_film(sqm)

        if not self.capabilities.w_scale_confirmed and self._poll_count % 4 == 0:
            if sqm.calibrate_thickness_scale():
                self._emit("capabilities", self.capabilities)

        if self._last_poll_t is not None and shutter:
            self._deposit_time += now - self._last_poll_t
        self._last_poll_t = now

        sample = Sample(
            t=now,
            elapsed=now - self.run.started if self.run.started else 0.0,
            deposit_time=self._deposit_time,
            rates=rates, thicknesses=thicknesses, frequencies=frequencies,
            lives=list(lives), avg_rate=avg_rate, avg_thickness=avg_thickness,
            shutter=shutter,
        )
        with self._lock:
            self._samples.append(sample)
            self._rate_window.append(avg_rate)
            cutoff = now - self.history_seconds
            while self._samples and self._samples[0].t < cutoff:
                self._samples.popleft()
        self._emit("sample", sample)

    def _read_each(self, sqm: InficonSQM160) -> list[SensorReading]:
        out = []
        for i in range(1, max(1, self.capabilities.channels) + 1):
            try:
                out.append(SensorReading(sqm.rate(i), sqm.thickness(i), sqm.frequency(i)))
            except SQM160Error:
                break
        return out

    def _refresh_film(self, sqm: InficonSQM160) -> None:
        try:
            film = sqm.film(0)
        except SQM160Error:
            return
        if film != self.film:
            self.film = film
            self._emit("film", (self.film_number, film))


class _Result:

    def __init__(self, done: threading.Event, box: dict):
        self._done, self._box = done, box

    def wait(self, timeout: float = 5.0):
        if not self._done.wait(timeout):
            raise SQM160Timeout("the instrument command did not finish in time")
        if "error" in self._box:
            raise self._box["error"]
        return self._box.get("value")

    @property
    def finished(self) -> bool:
        return self._done.is_set()


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    seconds = int(max(0, seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"
