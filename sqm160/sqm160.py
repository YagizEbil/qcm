from __future__ import annotations

import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

SYNC = b"!"
CMD_LEN_OFFSET = 34
RSP_LEN_OFFSET = 35
BAUD_RATES = (2400, 4800, 9600, 19200, 38400, 57600, 115200)
DEFAULT_BAUD = 19200
BAUD_SEARCH_ORDER = (19200, 9600, 115200, 57600, 38400, 4800, 2400)

PL2303_IDS = {(0x067B, 0x2303), (0x067B, 0x23A3), (0x067B, 0x23B3),
              (0x067B, 0x23C3), (0x067B, 0x23D3), (0x067B, 0x23E3),
              (0x067B, 0x23F3), (0x067B, 0x2304)}
USB_IDS = PL2303_IDS
OTHER_USB_SERIAL_IDS = {
    (0x0403, 0x6001), (0x0403, 0x6010), (0x0403, 0x6011), (0x0403, 0x6014),
    (0x10C4, 0xEA60), (0x10C4, 0xEA70),
    (0x1A86, 0x7523), (0x1A86, 0x5523), (0x1A86, 0x55D4),
    (0x067B, 0x2AF9),
}

CONFIG_DIR = Path(os.environ.get("SQM160_HOME", Path.home() / ".sqm160"))
CONNECTION_CACHE = CONFIG_DIR / "connection.json"


class SQM160Error(Exception):
    pass


class SQM160Timeout(SQM160Error):
    pass


class SQM160CommandError(SQM160Error):
    pass


class SQM160ConnectionLost(SQM160Error):
    pass


class SQM160NotFound(SQM160Error):

    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class _BadPacket(SQM160Error):
    pass


def crc(data: bytes) -> bytes:
    reg = 0x3FFF
    for byte in data:
        reg ^= byte
        for _ in range(8):
            carry = reg & 1
            reg >>= 1
            if carry:
                reg ^= 0x2001
    reg &= 0x3FFF
    return bytes(((reg & 0x7F) + 34, ((reg >> 7) & 0x7F) + 34))


def build_packet(message: bytes) -> bytes:
    if not 1 <= len(message) <= 190:
        raise ValueError("message must be 1 to 190 bytes")
    if SYNC in message:
        raise ValueError("'!' is reserved for the sync byte")
    body = bytes([len(message) + CMD_LEN_OFFSET]) + message
    return SYNC + body + crc(body)


def film_byte(number: int) -> bytes:
    if not 0 <= number <= 99:
        raise ValueError("film number must be 0 to 99")
    return bytes([48 + number])


def _sensor(sensor: int) -> str:
    if not 1 <= sensor <= 6:
        raise ValueError("sensor must be 1 to 6")
    return str(sensor)


def _check(name: str, value: float, low: float, high: float) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name}={value} outside {low} to {high}")


@dataclass
class Film:

    name: str
    density: float = 1.0
    tooling: int = 100
    z_ratio: float = 1.0
    final_thickness: float = 0.0
    thickness_setpoint: float = 0.0
    time_setpoint: int = 0
    sensors: tuple = (1,)

    def encode(self) -> bytes:
        name = self.name.upper().replace(" ", "_")
        if len(name) > 8 or not all((c.isascii() and c.isalnum()) or c == "_" for c in name):
            raise ValueError("film name: max 8 characters, A-Z, 0-9, spaces or _")
        _check("density", self.density, 0.5, 99.99)
        _check("tooling", self.tooling, 10, 399)
        _check("z_ratio", self.z_ratio, 0.1, 9.999)
        _check("final_thickness", self.final_thickness, 0, 9999)
        _check("thickness_setpoint", self.thickness_setpoint, 0, 9999)
        _check("time_setpoint", self.time_setpoint, 0, 5999)
        if not self.sensors or any(not 1 <= s <= 6 for s in self.sensors):
            raise ValueError("sensors must be a non-empty set of numbers 1 to 6")
        mask = sum(1 << (s - 1) for s in set(self.sensors))
        text = (
            f"{name:_<8} {self.density:.2f} {int(self.tooling)} {self.z_ratio:.3f} "
            f"{self.final_thickness:.3f} {self.thickness_setpoint:.3f} "
            f"{int(self.time_setpoint)} {mask}"
        )
        return text.encode("ascii")

    @classmethod
    def decode(cls, text: str) -> "Film":
        name, values = text[:8], text[8:].split()
        if len(values) != 7:
            tokens = text.split()
            if len(tokens) < 8:
                raise SQM160Error(f"unexpected film response: {text!r}")
            name, values = " ".join(tokens[:-7]), tokens[-7:]
        d, tool, z, final, sp, tsp, mask = values
        sensors = tuple(i + 1 for i in range(6) if int(mask) >> i & 1)
        return cls(name.replace("_", " ").strip(), float(d), int(float(tool)), float(z),
                   float(final), float(sp), int(float(tsp)), sensors)


@dataclass
class SystemParams1:

    timebase: float = 0.25
    simulate: bool = False
    display_mode: int = 0
    high_rate_resolution: bool = False
    rate_filter: int = 8
    crystal_tooling: tuple = (100,) * 6

    def encode(self) -> bytes:
        _check("timebase", self.timebase, 0.1, 2.0)
        _check("display_mode", self.display_mode, 0, 3)
        _check("rate_filter", self.rate_filter, 1, 20)
        for t in self.crystal_tooling:
            _check("crystal_tooling", t, 10, 399)
        fields = [f"{self.timebase:.2f}", str(int(self.simulate)), str(self.display_mode),
                  str(int(self.high_rate_resolution)), str(self.rate_filter),
                  *(str(int(t)) for t in self.crystal_tooling)]
        return ("B " + " ".join(fields)).encode("ascii")

    @classmethod
    def decode(cls, text: str) -> "SystemParams1":
        v = text.split()
        return cls(float(v[0]), v[1] == "1", int(v[2]), v[3] == "1", int(v[4]),
                   tuple(int(float(t)) for t in v[5:]))


@dataclass
class SystemParams2:

    min_frequency: float = 5.0
    max_frequency: float = 6.1
    min_rate: float = 0.0
    max_rate: float = 100.0
    min_thickness: float = 0.0
    max_thickness: float = 1.0
    etch_mode: bool = False

    def encode(self) -> bytes:
        _check("min_frequency", self.min_frequency, 1.0, 6.4)
        _check("max_frequency", self.max_frequency, 1.1, 6.5)
        for n, v in (("min_rate", self.min_rate), ("max_rate", self.max_rate)):
            _check(n, v, -99, 999)
        for n, v in (("min_thickness", self.min_thickness), ("max_thickness", self.max_thickness)):
            _check(n, v, 0, 9999)
        fields = [f"{self.min_frequency:.3f}", f"{self.max_frequency:.3f}",
                  f"{self.min_rate:.2f}", f"{self.max_rate:.2f}",
                  f"{self.min_thickness:.3f}", f"{self.max_thickness:.3f}",
                  str(int(self.etch_mode))]
        return ("C " + " ".join(fields)).encode("ascii")

    @classmethod
    def decode(cls, text: str) -> "SystemParams2":
        v = text.split()
        return cls(*(float(x) for x in v[:6]), v[6] == "1")


@dataclass
class SensorReading:

    rate: float
    thickness: float
    frequency: float


@dataclass
class Capabilities:

    firmware: str = ""
    channels: int = 6
    rate_query_suffix: str = "?"
    rate_suffix_confirmed: bool = False
    w_thickness_scale: float = 0.001
    w_scale_confirmed: bool = False
    w_sensor_count: int = 0
    tooling_count: int = 6
    notes: list = field(default_factory=list)

    def summary(self) -> str:
        unit = "A" if self.w_thickness_scale == 0.001 else "kA"
        how = "measured" if self.w_scale_confirmed else "assumed"
        return (f"{self.firmware or 'unknown firmware'}, {self.channels} channel(s); "
                f"read-all thickness in {unit} ({how}); "
                f"rate command 'L1{self.rate_query_suffix}'; "
                f"{self.tooling_count} tooling value(s)")


class InficonSQM160:

    def __init__(self, port: str | None = None, baudrate: int = DEFAULT_BAUD, *,
                 url: str | None = None, transport=None,
                 timeout: float = 3.0, retries: int = 3):
        if baudrate not in BAUD_RATES:
            raise ValueError(f"baudrate must be one of {BAUD_RATES}")
        self.port = port
        self.baudrate = baudrate
        self.url = url
        self.capabilities = Capabilities()
        if transport is None:
            import serial

            if url:
                transport = serial.serial_for_url(url, baudrate=baudrate, timeout=0.05)
            else:
                if port is None:
                    port, baudrate = discover()
                    self.baudrate = baudrate
                transport = serial.Serial(port, baudrate, bytesize=8, parity="N",
                                          stopbits=1, timeout=0.05)
            self.port = port
        self.transport = transport
        self.timeout = timeout
        self.retries = retries
        self._lock = threading.Lock()
        self._closed = False

    @classmethod
    def autoconnect(cls, *, progress=None, timeout: float = 3.0,
                    retries: int = 3, probe: bool = True) -> "InficonSQM160":
        import serial

        port, baud = discover(progress=progress)
        transport = serial.Serial(port, baud, bytesize=8, parity="N", stopbits=1,
                                  timeout=0.05)
        sqm = cls(port, baud, transport=transport, timeout=timeout, retries=retries)
        sqm.port, sqm.baudrate = port, baud
        if probe:
            sqm.probe(progress=progress)
        remember_connection(port, baud)
        return sqm

    def close(self) -> None:
        self._closed = True
        try:
            self.transport.close()
        except Exception:
            pass

    @property
    def is_closed(self) -> bool:
        return self._closed

    def __enter__(self) -> "InficonSQM160":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def comm(self, command: str | bytes) -> str:
        message = command.encode("latin-1") if isinstance(command, str) else bytes(command)
        packet = build_packet(message)
        with self._lock:
            for _ in range(self.retries):
                try:
                    self.transport.reset_input_buffer()
                    self.transport.write(packet)
                except OSError as exc:
                    raise SQM160ConnectionLost(f"lost the connection: {exc}") from exc
                try:
                    status, reply = self._read_response()
                except _BadPacket:
                    continue
                if status == ord("A"):
                    return reply.decode("latin-1")
                reason = {ord("C"): "invalid command", ord("D"): "bad data"}.get(status, "unknown status")
                raise SQM160CommandError(f"{message!r} rejected: {reason} ({chr(status)!r})")
        raise SQM160Timeout(f"no valid reply to {message!r} after {self.retries} attempts")

    def _read_exact(self, n: int, deadline: float) -> bytes:
        buf = bytearray()
        while len(buf) < n:
            if time.monotonic() > deadline:
                raise _BadPacket("timeout")
            try:
                buf += self.transport.read(n - len(buf))
            except OSError as exc:
                raise SQM160ConnectionLost(f"lost the connection: {exc}") from exc
        return bytes(buf)

    def _read_response(self) -> tuple[int, bytes]:
        deadline = time.monotonic() + self.timeout
        while self._read_exact(1, deadline) != SYNC:
            pass
        length = self._read_exact(1, deadline)[0]
        count = length - RSP_LEN_OFFSET
        if count < 1:
            raise _BadPacket("bad length byte")
        body = self._read_exact(count + 2, deadline)
        payload, received = body[:-2], body[-2:]
        if SYNC in payload or crc(bytes([length]) + payload) != received:
            raise _BadPacket("CRC mismatch")
        return payload[0], payload[1:]

    def probe(self, progress=None) -> Capabilities:
        caps = self.capabilities
        say = progress or (lambda _m: None)

        say("Reading the firmware version...")
        caps.firmware = self.version()
        try:
            caps.channels = self.channels()
        except SQM160Error:
            caps.notes.append("The unit did not answer the channel-count command (J); "
                              "assuming 6 channels.")

        say("Checking the rate command...")
        for suffix in ("?", ""):
            try:
                self.comm(f"L1{suffix}")
            except SQM160CommandError:
                continue
            except SQM160Error:
                break
            caps.rate_query_suffix = suffix
            caps.rate_suffix_confirmed = True
            break
        else:
            caps.notes.append("Neither 'L1?' nor 'L1' was accepted; rate readings may fail.")

        say("Checking the read-all command...")
        try:
            raw = self._read_all_raw()
            caps.w_sensor_count = len(raw)
        except SQM160Error:
            caps.notes.append("The read-all command (W) did not answer; "
                              "per-sensor commands will be used instead.")

        try:
            caps.tooling_count = len(self.system1().crystal_tooling)
        except SQM160Error:
            pass

        self.calibrate_thickness_scale()
        if not caps.w_scale_confirmed:
            caps.notes.append(
                "Thickness units of the read-all command could not be confirmed yet "
                "(all sensors read zero). The manual's reading (A) is in use and the "
                "check repeats automatically once a film starts growing.")
        return caps

    def calibrate_thickness_scale(self) -> bool:
        caps = self.capabilities
        if caps.w_scale_confirmed:
            return True
        try:
            raw = self._read_all_raw()
        except SQM160Error:
            return False
        for index, reading in enumerate(raw[:6], start=1):
            if abs(reading.thickness) < 1e-6:
                continue
            try:
                kilo = self.thickness(index)
            except SQM160Error:
                return False
            if abs(kilo) < 1e-4:
                continue
            ratio = reading.thickness / kilo
            if 500 < ratio < 2000:
                caps.w_thickness_scale, caps.w_scale_confirmed = 0.001, True
            elif 0.5 < ratio < 2:
                caps.w_thickness_scale, caps.w_scale_confirmed = 1.0, True
            else:
                continue
            caps.notes = [n for n in caps.notes if "Thickness units" not in n]
            caps.notes.append(
                f"Read-all thickness confirmed as {'A' if caps.w_thickness_scale == 0.001 else 'kA'} "
                "by comparing it against the per-sensor thickness command.")
            return True
        return False

    def version(self) -> str:
        return self.comm("@").strip()

    show_version = version

    def channels(self) -> int:
        return int(self.comm("J"))

    def film(self, number: int = 0) -> Film:
        return Film.decode(self.comm(b"A" + film_byte(number) + b"?"))

    def show_film_parameters(self, number: int = 1) -> Film:
        return self.film(number)

    def set_film(self, number: int, film: Film) -> None:
        self.comm(b"A" + film_byte(number) + film.encode())

    def set_active_film(self, number: int) -> None:
        if not 1 <= number <= 99:
            raise ValueError("film number must be 1 to 99")
        self.comm(b"D" + film_byte(number))

    def system1(self) -> SystemParams1:
        return SystemParams1.decode(self.comm("B?"))

    def set_system1(self, params: SystemParams1) -> None:
        self.comm(params.encode())

    def system2(self) -> SystemParams2:
        return SystemParams2.decode(self.comm("C?"))

    def set_system2(self, params: SystemParams2) -> None:
        self.comm(params.encode())

    def rate(self, sensor: int = 1) -> float:
        return float(self.comm(f"L{_sensor(sensor)}{self.capabilities.rate_query_suffix}"))

    def avg_rate(self) -> float:
        return float(self.comm("M"))

    def thickness(self, sensor: int = 1) -> float:
        return float(self.comm(f"N{_sensor(sensor)}"))

    def avg_thickness(self) -> float:
        return float(self.comm("O"))

    def frequency(self, sensor: int = 1) -> float:
        return float(self.comm(f"P{_sensor(sensor)}"))

    def crystal_life(self, sensor: int = 1) -> float:
        return float(self.comm(f"R{_sensor(sensor)}"))

    def _read_all_raw(self) -> list[SensorReading]:
        values = [float(v) for v in self.comm("W").split()[1:]]
        return [SensorReading(*values[i:i + 3]) for i in range(0, len(values) - 2, 3)]

    def read_all(self) -> list[SensorReading]:
        scale = self.capabilities.w_thickness_scale
        return [SensorReading(r.rate, r.thickness * scale, r.frequency)
                for r in self._read_all_raw()]

    def zero(self) -> None:
        self.comm("S")

    def zero_time(self) -> None:
        self.comm("T")

    def shutter_is_open(self) -> bool:
        return self.comm("U?").strip() == "1"

    def open_shutter(self) -> None:
        self.comm("U1")

    def close_shutter(self) -> None:
        self.comm("U0")

    def power_up_flag(self) -> bool:
        return self.comm("Y").strip() == "1"

    def reset_to_defaults(self, *, confirm: bool = False) -> None:
        if not confirm:
            raise ValueError("this erases all 99 films; call with confirm=True")
        self.comm("Z")

    def backup(self, path: str | Path, progress=None) -> dict:
        say = progress or (lambda _m: None)
        data = {"saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                "firmware": self.capabilities.firmware or self.version(),
                "films": {}, "system1": None, "system2": None}
        for n in range(1, 100):
            say(f"Saving film {n} of 99...")
            try:
                data["films"][str(n)] = asdict(self.film(n))
            except SQM160Error as exc:
                data["films"][str(n)] = {"error": str(exc)}
        data["system1"] = asdict(self.system1())
        data["system2"] = asdict(self.system2())
        path = Path(path)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data

    def restore(self, path: str | Path, progress=None) -> None:
        say = progress or (lambda _m: None)
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, values in sorted(data.get("films", {}).items(), key=lambda kv: int(kv[0])):
            if "error" in values:
                continue
            say(f"Restoring film {key}...")
            values = dict(values)
            values["sensors"] = tuple(values.get("sensors", (1,)))
            self.set_film(int(key), Film(**values))
        if data.get("system1"):
            s1 = dict(data["system1"])
            s1["crystal_tooling"] = tuple(s1.get("crystal_tooling", (100,) * 6))
            self.set_system1(SystemParams1(**s1))
        if data.get("system2"):
            self.set_system2(SystemParams2(**data["system2"]))


@dataclass
class PortCandidate:
    device: str
    description: str = ""
    vid: int | None = None
    pid: int | None = None
    rank: int = 3

    @property
    def is_prolific(self) -> bool:
        return (self.vid, self.pid) in PL2303_IDS

    @property
    def ids(self) -> str:
        return f"{self.vid:04X}:{self.pid:04X}" if self.vid is not None else "----:----"


def list_candidates() -> list[PortCandidate]:
    from serial.tools import list_ports

    out = []
    for p in list_ports.comports():
        device = p.device or ""
        if sys.platform == "darwin" and device.startswith("/dev/tty."):
            continue
        if (p.vid, p.pid) in PL2303_IDS:
            rank = 0
        elif (p.vid, p.pid) in OTHER_USB_SERIAL_IDS:
            rank = 1
        elif p.vid is not None:
            rank = 2
        else:
            rank = 3
        name = (p.description or "").lower() + " " + device.lower()
        if any(word in name for word in ("bluetooth", "debug-console", "modem")):
            rank = 4
        out.append(PortCandidate(device, p.description or "", p.vid, p.pid, rank))
    out.sort(key=lambda c: (c.rank, c.device))
    return out


def _try_port(device: str, baud: int, timeout: float) -> bool:
    import serial

    try:
        with serial.Serial(device, baud, bytesize=8, parity="N", stopbits=1,
                           timeout=0.05) as port:
            sqm = InficonSQM160(device, baud, transport=port, timeout=timeout, retries=1)
            reply = sqm.version()
            return bool(reply) and any(ch.isdigit() for ch in reply)
    except (SQM160Error, OSError, ValueError):
        return False


def discover(preferred: tuple[str, int] | None = None, *, timeout: float = 0.6,
             progress=None, full: bool = True) -> tuple[str, int]:
    say = progress or (lambda _m: None)
    tried: set[tuple[str, int]] = set()

    remembered = preferred or recall_connection()
    if remembered:
        device, baud = remembered
        say(f"Reconnecting to {device}...")
        tried.add((device, baud))
        if _try_port(device, baud, timeout):
            return device, baud

    candidates = list_candidates()
    if not candidates:
        raise SQM160NotFound(
            "No serial ports were found on this computer.",
            "Nothing at all is listed as a serial port. The USB cable is probably "
            "not plugged in, the SQM-160 is switched off, or the USB driver is not "
            "installed. Run the connection check for the exact steps.")

    for cand in candidates:
        if (cand.device, DEFAULT_BAUD) in tried:
            continue
        tried.add((cand.device, DEFAULT_BAUD))
        say(f"Checking {cand.device} at {DEFAULT_BAUD} baud...")
        if _try_port(cand.device, DEFAULT_BAUD, timeout):
            return cand.device, DEFAULT_BAUD

    if full:
        for cand in candidates:
            if cand.rank >= 4:
                continue
            for baud in BAUD_SEARCH_ORDER:
                if (cand.device, baud) in tried:
                    continue
                tried.add((cand.device, baud))
                say(f"Checking {cand.device} at {baud} baud...")
                if _try_port(cand.device, baud, timeout):
                    return cand.device, baud

    seen = ", ".join(f"{c.device} ({c.description or c.ids})" for c in candidates)
    prolific = [c for c in candidates if c.is_prolific]
    if prolific:
        detail = (f"A Prolific USB-to-serial port is present ({prolific[0].device}) but it "
                  "did not answer at any baud rate. The usual causes are the SQM-160 being "
                  "switched off, another program holding the port open (close INFICON's Comm "
                  "software), or the Windows Prolific driver being the version that refuses "
                  "to work with older chips.")
    else:
        detail = (f"Serial ports seen: {seen}. None of them answered. The SQM-160's USB chip "
                  "(Prolific PL2303) was not among them, which usually means the cable is "
                  "unplugged or the USB driver is missing.")
    raise SQM160NotFound("The SQM-160 did not answer on any serial port.", detail)


def find_sqm160(baudrate: int = DEFAULT_BAUD, timeout: float = 1.0) -> str:
    port, _baud = discover(timeout=timeout)
    return port


def remember_connection(port: str, baud: int) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONNECTION_CACHE.write_text(
            json.dumps({"port": port, "baud": baud, "when": time.time()}), encoding="utf-8")
    except OSError:
        pass


def recall_connection() -> tuple[str, int] | None:
    try:
        data = json.loads(CONNECTION_CACHE.read_text(encoding="utf-8"))
        return str(data["port"]), int(data["baud"])
    except (OSError, ValueError, KeyError):
        return None


def forget_connection() -> None:
    try:
        CONNECTION_CACHE.unlink()
    except OSError:
        pass


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Read an INFICON SQM-160.")
    parser.add_argument("port", nargs="?",
                        help="serial port, e.g. /dev/ttyUSB0 or COM3 (default: auto-detect)")
    parser.add_argument("--baud", type=int, default=None)
    parser.add_argument("--url", help="pyserial URL, e.g. socket://192.168.1.200:2101")
    parser.add_argument("--list", action="store_true", help="list serial ports and exit")
    parser.add_argument("--emulate", action="store_true", help="use the built-in emulator")
    args = parser.parse_args()

    if args.list:
        for c in list_candidates():
            tag = "  <- Prolific PL2303 (SQM-160 USB)" if c.is_prolific else ""
            print(f"{c.device:24} {c.ids}  {c.description}{tag}")
        return

    if args.emulate:
        from sqm160_emulator import FakeSQM160

        sqm = InficonSQM160(transport=FakeSQM160())
        sqm.probe()
    elif args.url:
        sqm = InficonSQM160(url=args.url, baudrate=args.baud or DEFAULT_BAUD)
        sqm.probe()
    elif args.port:
        sqm = InficonSQM160(args.port, args.baud or DEFAULT_BAUD)
        sqm.probe()
    else:
        try:
            sqm = InficonSQM160.autoconnect(progress=lambda m: print(m))
        except SQM160NotFound as exc:
            parser.exit(1, f"error: {exc}\n{exc.detail}\n")

    with sqm:
        if sqm.port:
            print("Port:         ", sqm.port, f"at {sqm.baudrate} baud")
        print("Version:      ", sqm.capabilities.firmware or sqm.version())
        print("Capabilities: ", sqm.capabilities.summary())
        for note in sqm.capabilities.notes:
            print("  note:", note)
        print("Active film:  ", sqm.film(0))
        print("Shutter open: ", sqm.shutter_is_open())
        print("Avg rate:     ", sqm.avg_rate(), "A/s")
        print("Avg thickness:", sqm.avg_thickness(), "kA")
        for i, r in enumerate(sqm.read_all(), start=1):
            print(f"Sensor {i}: {r.rate:6.2f} A/s  {r.thickness:10.4f} kA  {r.frequency:12.3f} Hz"
                  f"  life {sqm.crystal_life(i):5.1f} %")


if __name__ == "__main__":
    _main()
