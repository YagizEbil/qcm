from __future__ import annotations

import random
import time

from sqm160 import RSP_LEN_OFFSET, SYNC, Film, SystemParams1, SystemParams2, crc


class FakeSQM160:

    def __init__(self, channels: int = 6, version: str = "4.13", rate: float = 2.0,
                 thickness_unit: str = "A", accept_rate_query: bool = True):
        self.channels = channels
        self.version = version
        self.base_rate = rate
        self.thickness_unit = thickness_unit
        self.accept_rate_query = accept_rate_query
        self.films = {n: Film(f"FILM{n}", 1.0, 100, 1.0, 0.5, 0.0, 0, (1,)) for n in range(1, 100)}
        self.active = 1
        self.sys1 = SystemParams1(crystal_tooling=(100,) * channels)
        self.sys2 = SystemParams2()
        self.shutter = False
        self.thickness = [0.0] * 6
        self.rates = [0.0] * 6
        self.life = [0.0] * 6
        self.power_up = True
        self.drop_next = 0
        self.corrupt_next = 0
        self._last = time.monotonic()
        self._rx = bytearray()
        self._tx = bytearray()

    def write(self, data: bytes) -> int:
        self._rx += data
        self._process()
        return len(data)

    def read(self, n: int = 1) -> bytes:
        if not self._tx:
            time.sleep(0.005)
        out, self._tx = bytes(self._tx[:n]), self._tx[n:]
        return out

    def reset_input_buffer(self) -> None:
        self._tx.clear()

    def close(self) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _process(self) -> None:
        while True:
            start = self._rx.find(SYNC)
            if start < 0 or len(self._rx) < start + 2:
                return
            need = self._rx[start + 1] - 34 + 2
            if len(self._rx) < start + 2 + need:
                return
            packet = bytes(self._rx[start:start + 2 + need])
            del self._rx[:start + 2 + need]
            body, received = packet[1:-2], packet[-2:]
            if crc(body) != received:
                continue
            if self.drop_next:
                self.drop_next -= 1
                continue
            status, message = self._handle(body[1:].decode("latin-1"))
            self._send(status + message)

    def _send(self, text: str) -> None:
        body = bytes([len(text) + RSP_LEN_OFFSET]) + text.encode("latin-1")
        check = crc(body)
        if self.corrupt_next:
            self.corrupt_next -= 1
            check = bytes([check[0] ^ 1, check[1]])
        self._tx += SYNC + body + check

    def _advance(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        film = self.films[self.active]
        for i in range(6):
            active = self.shutter and (i + 1) in film.sensors
            self.rates[i] = self.base_rate * random.uniform(0.97, 1.03) if active else 0.0
            self.thickness[i] += self.rates[i] * dt / 1000
            self.life[i] = min(100.0, self.life[i] + self.rates[i] * dt / 5000)
        if self.shutter and film.final_thickness > 0 and self._avg_thickness() >= film.final_thickness:
            self.shutter = False

    def _active_sensors(self) -> list[int]:
        return [s - 1 for s in self.films[self.active].sensors]

    def _avg_thickness(self) -> float:
        idx = self._active_sensors()
        return sum(self.thickness[i] for i in idx) / len(idx)

    def _avg_rate(self) -> float:
        idx = self._active_sensors()
        return sum(self.rates[i] for i in idx) / len(idx)

    def _frequency(self, i: int) -> float:
        return 6_000_000.0 - 1000.0 * (i + 1) - 1500.0 * self.thickness[i]

    def _handle(self, msg: str) -> tuple[str, str]:
        self._advance()
        cmd, arg = msg[0], msg[1:]
        try:
            if cmd == "@":
                return "A", f"MON Ver {self.version}"
            if cmd == "J":
                return "A", str(self.channels)
            if cmd == "A":
                n = ord(arg[0]) - 48
                n = self.active if n == 0 else n
                if not 1 <= n <= 99:
                    return "D", ""
                if arg[1:] == "?":
                    f = self.films[n]
                    mask = sum(1 << (s - 1) for s in f.sensors)
                    return "A", (f"{f.name:<8} {f.density:5.2f} {f.tooling:3d} {f.z_ratio:6.3f} "
                                 f"{f.final_thickness:6.3f} {f.thickness_setpoint:6.3f} "
                                 f"{f.time_setpoint} {mask}")
                rest = arg[1:]
                cut = rest.find(" ")
                name = rest[:cut] if 0 <= cut < 8 else rest[:8]
                film = Film.decode(f"{name:<8}" + rest[len(name):])
                film.encode()
                self.films[n] = film
                return "A", ""
            if cmd == "B":
                if arg == "?":
                    p = self.sys1
                    fields = [f"{p.timebase:.2f}", str(int(p.simulate)), str(p.display_mode),
                              str(int(p.high_rate_resolution)), str(p.rate_filter),
                              *(str(t) for t in p.crystal_tooling)]
                    return "A", " " + " ".join(fields) + " "
                p = SystemParams1.decode(arg)
                p.encode()
                self.sys1 = p
                return "A", ""
            if cmd == "C":
                if arg == "?":
                    p = self.sys2
                    vals = [p.min_frequency, p.max_frequency, p.min_rate, p.max_rate,
                            p.min_thickness, p.max_thickness]
                    return "A", " " + " ".join(f"{v:.3f}" for v in vals) + f" {int(p.etch_mode)}"
                p = SystemParams2.decode(arg)
                p.encode()
                self.sys2 = p
                return "A", ""
            if cmd == "D":
                n = ord(arg[0]) - 48
                if not 1 <= n <= 99:
                    return "D", ""
                self.active = n
                return "A", ""
            if cmd in "LNPR":
                if cmd == "L" and arg.endswith("?") and not self.accept_rate_query:
                    return "C", ""
                i = int(arg.rstrip("?")) - 1
                if not 0 <= i < self.channels:
                    return "D", ""
                if cmd == "L":
                    return "A", f" {self.rates[i]:.2f} "
                if cmd == "N":
                    return "A", f" {self.thickness[i]:.3f} "
                if cmd == "P":
                    return "A", f"{self._frequency(i):.3f}"
                return "A", f" {self.life[i]:.2f}"
            if cmd == "M":
                return "A", f" {self._avg_rate():.2f} "
            if cmd == "O":
                return "A", f" {self._avg_thickness():.3f} "
            if cmd == "S":
                self.thickness = [0.0] * 6
                self.rates = [0.0] * 6
                return "A", ""
            if cmd == "T":
                return "A", ""
            if cmd == "U":
                if arg == "?":
                    return "A", str(int(self.shutter))
                if arg in ("0", "1"):
                    self.shutter = arg == "1"
                    return "A", ""
                return "D", ""
            if cmd == "W":
                scale = 1000.0 if self.thickness_unit == "A" else 1.0
                parts = ["00.00"] + [f"{self.rates[i]:05.2f} {self.thickness[i] * scale:06.3f} "
                                     f"{self._frequency(i):.3f}" for i in range(self.channels)]
                return "A", " ".join(parts) + " "
            if cmd == "Y":
                flag, self.power_up = self.power_up, False
                return "A", str(int(flag))
            if cmd == "Z":
                self.__init__(self.channels, self.version, self.base_rate,
                              self.thickness_unit, self.accept_rate_query)
                self.power_up = False
                return "A", ""
        except (ValueError, IndexError):
            return "D", ""
        return "C", ""
