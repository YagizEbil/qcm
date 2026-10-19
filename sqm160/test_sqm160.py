import time
from pathlib import Path

import pytest

from sqm160 import (Capabilities, Film, InficonSQM160, SQM160CommandError, SQM160NotFound,
                    SQM160Timeout, SystemParams1, SystemParams2, build_packet, crc)
from sqm160_emulator import FakeSQM160

MANUAL_PACKETS = [
    ("#@", 79, 55), ("%A1?", 46, 149), ("$B?", 93, 116), ("$C?", 103, 47), ("$D1", 93, 145),
    ("#J", 79, 56), ("%L1?", 133, 123), ("#M", 142, 138), ("$N1", 93, 81), ("#O", 143, 57),
    ("$P1", 90, 145), ("$R1", 105, 114), ("#S", 142, 143), ("#T", 79, 53), ("$U?", 91, 84),
    ("$U1", 90, 113), ("#W", 143, 53), ("#Y", 142, 144), ("#Z", 78, 144),
    ("$A", 53, 151), ("%A6", 118, 134), ("*A 0.00 ", 91, 100), ("+A 0.000 ", 74, 111),
    ("/A5500110.056", 147, 45), ("*A 50.01", 134, 76), ("%A0", 118, 135), ("%A1", 55, 60),
    ("0AMON Ver 4.13", 85, 119),
    ("KA1GOLD____ 1.23 150 1.23 1.234 1.234 0 12", 140, 40),
    ("HB 0.25 1 0 0 8 100 100 100 100 100 100", 80, 68),
    ("IC 5.000 6.000 0.000 10.00 0.000 10.00 0", 146, 41),
]


@pytest.mark.parametrize("body,c1,c2", MANUAL_PACKETS)
def test_crc_matches_manual(body, c1, c2):
    assert crc(body.encode("latin-1")) == bytes([c1, c2])


def test_build_packet_matches_manual():
    assert build_packet(b"@") == b"!#@" + bytes([79, 55])
    assert build_packet(b"U1") == b"!$U1" + bytes([90, 113])


def test_system1_encode_matches_manual_bytes():
    p = SystemParams1(0.25, True, 0, False, 8, (100,) * 6)
    assert p.encode() == b"B 0.25 1 0 0 8 100 100 100 100 100 100"


def test_decode_manual_responses():
    p1 = SystemParams1.decode(" 0.10 1 0 0 1 100 100 100 100 100 100 ")
    assert p1.timebase == 0.10 and p1.simulate and p1.rate_filter == 1
    p2 = SystemParams2.decode(" 4.000 6.000 0.000 100.000 0.000 1.000 0")
    assert (p2.min_frequency, p2.max_rate, p2.etch_mode) == (4.0, 100.0, False)
    film = Film.decode("FILM 1    1.00 100  1.000 33.380  0.000 0 1")
    assert film.name == "FILM 1" and film.final_thickness == 33.38 and film.sensors == (1,)
    assert Film.decode("GOLD____ 1.23 150 1.23 1.234 1.234 0 12").sensors == (3, 4)


@pytest.fixture
def emu():
    fake = FakeSQM160()
    return fake, InficonSQM160(transport=fake, timeout=0.2)


def test_basic_queries(emu):
    _, sqm = emu
    assert sqm.version() == "MON Ver 4.13"
    assert sqm.channels() == 6
    assert sqm.power_up_flag() is True and sqm.power_up_flag() is False
    assert len(sqm.read_all()) == 6


def test_film_round_trip_including_high_numbers(emu):
    _, sqm = emu
    film = Film("al 2", 2.70, 120, 1.08, 0.75, 0.5, 90, (1, 2))
    for n in (1, 79, 80, 99):
        sqm.set_film(n, film)
        assert sqm.film(n) == Film("AL 2", 2.70, 120, 1.08, 0.75, 0.5, 90, (1, 2))


def test_deposition_and_zero(emu):
    fake, sqm = emu
    sqm.set_active_film(5)
    sqm.zero()
    sqm.open_shutter()
    assert sqm.shutter_is_open()
    time.sleep(0.3)
    assert sqm.avg_rate() > 0 and sqm.avg_thickness() > 0
    sqm.close_shutter()
    sqm.zero()
    assert sqm.avg_thickness() == 0


def test_shutter_closes_at_final_thickness(emu):
    fake, sqm = emu
    fake.base_rate = 1000.0
    sqm.open_shutter()
    time.sleep(0.7)
    assert not sqm.shutter_is_open()


def test_system_params_round_trip(emu):
    _, sqm = emu
    p1 = SystemParams1(0.5, True, 1, True, 4, (100, 110, 120, 130, 140, 150))
    sqm.set_system1(p1)
    assert sqm.system1() == p1
    p2 = SystemParams2(5.0, 6.0, 0.0, 50.0, 0.0, 2.0, True)
    sqm.set_system2(p2)
    assert sqm.system2() == p2


def test_retry_recovers_from_dropped_and_corrupt_replies(emu):
    fake, sqm = emu
    fake.drop_next = 1
    assert sqm.channels() == 6
    fake.corrupt_next = 2
    assert sqm.channels() == 6


def test_timeout_raises_after_retries(emu):
    fake, sqm = emu
    fake.drop_next = 10
    with pytest.raises(SQM160Timeout):
        sqm.version()


def test_rejected_commands_raise(emu):
    _, sqm = emu
    with pytest.raises(SQM160CommandError, match="invalid command"):
        sqm.comm("Q")
    with pytest.raises(SQM160CommandError, match="bad data"):
        sqm.comm("L9?")


def test_input_validation():
    with pytest.raises(ValueError):
        Film("TOO LONG NAME").encode()
    with pytest.raises(ValueError):
        Film("X", density=0.1).encode()
    with pytest.raises(ValueError):
        InficonSQM160(transport=FakeSQM160()).reset_to_defaults()


def test_backup_and_restore_round_trip(tmp_path, emu):
    _, sqm = emu
    sqm.set_film(7, Film("TITANIUM"[:8], 4.51, 130, 0.628, 1.5, 0.0, 0, (1, 3)))
    path = tmp_path / "films.json"
    sqm.backup(path)
    sqm.set_film(7, Film("WRONG", 1.0, 100, 1.0, 0, 0, 0, (1,)))
    sqm.restore(path)
    restored = sqm.film(7)
    assert restored.name == "TITANIUM" and restored.sensors == (1, 3)


def test_probe_measures_thickness_unit_in_angstroms():
    fake = FakeSQM160(thickness_unit="A")
    sqm = InficonSQM160(transport=fake, timeout=0.2)
    fake.thickness = [0.25] * 6
    sqm.probe()
    assert sqm.capabilities.w_scale_confirmed
    assert sqm.capabilities.w_thickness_scale == 0.001
    assert sqm.read_all()[0].thickness == pytest.approx(sqm.thickness(1), rel=1e-6)


def test_probe_measures_thickness_unit_in_kiloangstroms():
    fake = FakeSQM160(thickness_unit="kA")
    sqm = InficonSQM160(transport=fake, timeout=0.2)
    fake.thickness = [0.25] * 6
    sqm.probe()
    assert sqm.capabilities.w_scale_confirmed
    assert sqm.capabilities.w_thickness_scale == 1.0
    assert sqm.read_all()[0].thickness == pytest.approx(sqm.thickness(1), rel=1e-6)


def test_unconfirmed_scale_falls_back_to_the_manual_and_says_so():
    sqm = InficonSQM160(transport=FakeSQM160(), timeout=0.2)
    sqm.probe()
    assert not sqm.capabilities.w_scale_confirmed
    assert sqm.capabilities.w_thickness_scale == 0.001
    assert any("could not be confirmed" in note for note in sqm.capabilities.notes)


def test_rate_command_falls_back_when_the_question_mark_is_rejected():
    fake = FakeSQM160(accept_rate_query=False)
    sqm = InficonSQM160(transport=fake, timeout=0.2)
    sqm.probe()
    assert sqm.capabilities.rate_query_suffix == ""
    assert sqm.capabilities.rate_suffix_confirmed
    sqm.rate(1)


def test_rate_command_keeps_the_documented_question_mark():
    sqm = InficonSQM160(transport=FakeSQM160(), timeout=0.2)
    sqm.probe()
    assert sqm.capabilities.rate_query_suffix == "?"
    sqm.rate(1)


def test_two_channel_unit_reports_fewer_tooling_values():
    sqm = InficonSQM160(transport=FakeSQM160(channels=2), timeout=0.2)
    sqm.probe()
    assert sqm.capabilities.channels == 2
    assert sqm.capabilities.tooling_count == 2
    assert sqm.capabilities.w_sensor_count == 2
    assert len(sqm.system1().crystal_tooling) == 2


def test_capabilities_summary_is_readable():
    caps = Capabilities(firmware="MON Ver 4.13", channels=6)
    assert "MON Ver 4.13" in caps.summary() and "assumed" in caps.summary()


class _Port:
    def __init__(self, device, vid, pid, description="fake port"):
        self.device, self.vid, self.pid, self.description = device, vid, pid, description


def _patch_ports(monkeypatch, ports, devices):
    import serial
    from serial.tools import list_ports

    import sqm160

    monkeypatch.setattr(list_ports, "comports", lambda: ports)
    monkeypatch.setattr(sqm160, "recall_connection", lambda: None)
    monkeypatch.setattr(sqm160, "remember_connection", lambda *a, **k: None)

    def fake_serial(port, *args, **kwargs):
        if port not in devices:
            raise serial.SerialException(f"could not open {port}")
        return devices[port]

    monkeypatch.setattr(serial, "Serial", fake_serial)


def test_find_skips_other_pl2303_cables(monkeypatch):
    from sqm160 import discover

    silent = FakeSQM160()
    silent.drop_next = 99
    ports = [_Port("/dev/ttyUSB0", 0x067B, 0x2303), _Port("/dev/ttyUSB1", 0x0403, 0x6001),
             _Port("/dev/ttyUSB2", 0x067B, 0x2303)]
    _patch_ports(monkeypatch, ports, {"/dev/ttyUSB0": silent, "/dev/ttyUSB2": FakeSQM160()})
    assert discover(timeout=0.1) == ("/dev/ttyUSB2", 19200)


def test_find_tries_a_plain_com_port_when_no_usb_chip_matches(monkeypatch):
    from sqm160 import discover

    ports = [_Port("COM1", None, None, "Communications Port")]
    _patch_ports(monkeypatch, ports, {"COM1": FakeSQM160()})
    assert discover(timeout=0.1)[0] == "COM1"


def test_constructor_auto_detects(monkeypatch):
    _patch_ports(monkeypatch, [_Port("COM7", 0x067B, 0x2303)], {"COM7": FakeSQM160()})
    with InficonSQM160(timeout=0.1) as sqm:
        assert sqm.port == "COM7" and sqm.channels() == 6


def test_not_found_explains_what_was_seen(monkeypatch):
    from sqm160 import discover

    _patch_ports(monkeypatch, [], {})
    with pytest.raises(SQM160NotFound, match="No serial ports"):
        discover(timeout=0.05)

    silent = FakeSQM160()
    silent.drop_next = 999
    _patch_ports(monkeypatch, [_Port("COM3", 0x067B, 0x2303)], {"COM3": silent})
    with pytest.raises(SQM160NotFound) as info:
        discover(timeout=0.05)
    assert "Prolific" in info.value.detail


def test_remembered_port_is_tried_first(monkeypatch, tmp_path):
    import sqm160

    monkeypatch.setattr(sqm160, "CONNECTION_CACHE", tmp_path / "connection.json")
    sqm160.remember_connection("COM9", 9600)
    assert sqm160.recall_connection() == ("COM9", 9600)
    sqm160.forget_connection()
    assert sqm160.recall_connection() is None


from sqm160_engine import Monitor, State, emulator_connector, format_duration


def _wait_for(predicate, timeout=6.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def monitor():
    mon = Monitor(interval=0.1, connector=emulator_connector)
    yield mon
    mon.stop()


def test_monitor_connects_and_produces_samples(monitor):
    monitor.start()
    assert _wait_for(lambda: monitor.state is State.CONNECTED)
    assert _wait_for(lambda: monitor.latest is not None)
    sample = monitor.latest
    assert len(sample.rates) == 6 and sample.shutter is False


def test_monitor_tracks_a_deposition_and_time_remaining(monitor):
    monitor.start()
    assert _wait_for(lambda: monitor.connected)
    monitor.start_run("test", zero=True)
    monitor.open_shutter().wait(3)
    assert _wait_for(lambda: monitor.latest and monitor.latest.avg_thickness > 0)
    assert _wait_for(lambda: monitor.smoothed_rate > 0)
    assert _wait_for(lambda: monitor.time_remaining() is not None)
    assert monitor.time_remaining() > 0
    assert _wait_for(lambda: monitor.latest.deposit_time > 0)
    monitor.close_shutter().wait(3)


def test_monitor_confirms_the_thickness_unit_during_the_run(monitor):
    monitor.start()
    assert _wait_for(lambda: monitor.connected)
    assert not monitor.capabilities.w_scale_confirmed
    monitor.open_shutter().wait(3)
    assert _wait_for(lambda: monitor.capabilities.w_scale_confirmed, timeout=8)
    assert monitor.capabilities.w_thickness_scale == 0.001


def test_monitor_reconnects_after_the_cable_is_pulled():
    attempts = {"n": 0}

    def flaky(progress=None):
        attempts["n"] += 1
        return emulator_connector(progress)

    mon = Monitor(interval=0.1, connector=flaky)
    mon.start()
    try:
        assert _wait_for(lambda: mon.connected)
        mon.sqm.transport.write = _raise_disconnected
        assert _wait_for(lambda: mon.state in (State.LOST, State.SEARCHING))
        assert _wait_for(lambda: attempts["n"] >= 2, timeout=8)
        assert _wait_for(lambda: mon.connected, timeout=8)
    finally:
        mon.stop()


def _raise_disconnected(*_args, **_kwargs):
    raise OSError("device disconnected")


def test_format_duration():
    assert format_duration(None) == "--:--"
    assert format_duration(59) == "00:59"
    assert format_duration(125) == "02:05"
    assert format_duration(3725) == "1:02:05"


from sqm160_log import (LogWriter, export_run_settings, export_samples, plot_samples,
                        read_csv, safe_name)


def _fake_samples(count=5, sensors=2):
    from sqm160_engine import Sample

    now = time.time()
    return [Sample(t=now + i, elapsed=float(i), deposit_time=float(i),
                   rates=[1.0 + i] * sensors, thicknesses=[0.001 * i] * sensors,
                   frequencies=[5.9e6] * sensors, lives=[float("nan")] * sensors,
                   avg_rate=1.0 + i, avg_thickness=0.001 * i, shutter=i > 1)
            for i in range(count)]


def test_csv_has_one_row_per_sample_and_reads_back(tmp_path):
    samples = _fake_samples()
    path = export_samples(samples, tmp_path / "run.csv", "csv")
    rows = read_csv(path)
    assert len(rows) == len(samples)
    assert rows[0]["avg_rate_A_per_s"] == "1.000"
    assert rows[-1]["shutter_open"] == "1"
    assert rows[0]["life1_percent"] == ""


def _read_like_the_analyser(path):
    import re

    rows, start_info = [], ""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("start"):
            start_info = " ".join(line.split())
        parts = re.split(r"[\t;]+|\s{2,}|\s", line)
        try:
            rows.append([float(q.replace(",", ".")) for q in parts if q != ""])
        except ValueError:
            continue
    assert rows, "the analyser would find no numeric data in this file"
    ncol = min(len(r) for r in rows)
    channels, ch = {}, 1
    while 5 + 3 * (ch - 1) < ncol:
        channels[ch] = 5 + 3 * (ch - 1)
        ch += 1
    return [r[:ncol] for r in rows], ncol, channels, start_info


@pytest.mark.parametrize("sensors", [1, 2, 6])
def test_txt_log_is_readable_by_the_cycle_analyser(tmp_path, sensors):
    samples = _fake_samples(8, sensors=sensors)
    for i, sample in enumerate(samples):
        sample.frequencies = [5.9e6 - 10 * i] * sensors
    path = export_samples(samples, tmp_path / "4vp_dvb_ace_1000ppm.txt", "txt")

    rows, ncol, channels, start_info = _read_like_the_analyser(path)

    assert len(rows) == len(samples)
    assert ncol == 5 + 3 * sensors
    assert sorted(channels) == list(range(1, sensors + 1))
    assert start_info.lower().startswith("started")
    assert [r[0] for r in rows] == [s.elapsed for s in samples]
    first = channels[1]
    assert [r[first] for r in rows] == [s.frequencies[0] for s in samples]
    assert all(r[first] > 1000 for r in rows)


def test_txt_log_header_lines_never_look_like_data(tmp_path):
    film = Film("GOLD", 19.3, 100, 0.381, 1.0, 0, 0, (1,))
    path = export_samples(_fake_samples(3), tmp_path / "run.txt", "txt", film=film,
                          run=None, note="1000")
    rows, _ncol, _channels, _info = _read_like_the_analyser(path)
    assert len(rows) == 3


def test_txt_log_has_a_header_block(tmp_path):
    film = Film("GOLD", 19.3, 100, 0.381, 1.0, 0, 0, (1,))
    path = export_samples(_fake_samples(), tmp_path / "run.txt", "txt", film=film)
    text = path.read_text(encoding="utf-8")
    assert "INFICON SQM-160 deposition log" in text
    assert "GOLD" in text and "19.30" in text
    assert "Columns: time, average rate" in text
    assert text.count("\n") >= 5


def test_writer_flushes_every_row(tmp_path):
    path = tmp_path / "live.csv"
    with LogWriter(path, "csv", sensors=1) as writer:
        for sample in _fake_samples(3, sensors=1):
            writer.write(sample)
            assert path.read_text(encoding="utf-8").count("\n") == writer.rows + 1


def test_writer_attaches_to_a_monitor(tmp_path, monitor):
    monitor.start()
    assert _wait_for(lambda: monitor.connected)
    writer = LogWriter(tmp_path / "attached.csv", "csv", sensors=6).open()
    writer.attach(monitor)
    assert _wait_for(lambda: writer.rows >= 3)
    writer.detach(monitor)
    writer.close()
    assert len(read_csv(tmp_path / "attached.csv")) >= 3


def test_run_settings_json(tmp_path):
    from sqm160_engine import RunInfo

    film = Film("AL", 2.7, 100, 1.08, 1.0, 0, 0, (1,))
    path = export_run_settings(tmp_path / "s.json", run=RunInfo("r1", time.time()),
                               film=film, system1=SystemParams1(),
                               capabilities=Capabilities(firmware="MON Ver 4.13"))
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["film"]["name"] == "AL"
    assert data["instrument"]["firmware"] == "MON Ver 4.13"
    assert data["run"]["label"] == "r1"


def test_plot_export(tmp_path):
    pytest.importorskip("matplotlib")
    path = plot_samples(_fake_samples(10), tmp_path / "run.png", title="t")
    assert path.exists() and path.stat().st_size > 1000


def test_plot_export_without_data_is_explained(tmp_path):
    pytest.importorskip("matplotlib")
    with pytest.raises(RuntimeError, match="nothing to plot"):
        plot_samples([], tmp_path / "x.png")


def test_safe_name():
    assert safe_name("run 1/2: gold") == "run 1_2_ gold"
    assert safe_name("   ") == "run"


def test_doctor_runs_without_hardware_and_never_raises():
    from sqm160_doctor import FAIL, OK, WARN, run_checks

    report = run_checks(try_connect=False)
    assert report.checks
    assert all(c.status in (OK, WARN, FAIL, "info") for c in report.checks)
    assert "Python version" in [c.name for c in report.checks]
    text = report.text()
    assert "SQM-160 connection check" in text


def test_doctor_report_saves(tmp_path):
    from sqm160_doctor import run_checks

    report = run_checks(try_connect=False)
    path = report.save(tmp_path / "check.json")
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["checks"] and "system" in data


def test_cli_parser_accepts_every_command():
    from sqm160_cli import build_parser

    parser = build_parser()
    for argv in (["status"], ["ports"], ["doctor"], ["monitor"], ["gui"], ["forget"],
                 ["log", "run1", "-d", "60", "-f", "csv", "txt", "--plot"],
                 ["films", "list", "--range", "1", "5"],
                 ["films", "backup", "f.json"], ["films", "restore", "f.json", "-y"]):
        args = parser.parse_args(argv)
        assert getattr(args, "func", None) is not None
