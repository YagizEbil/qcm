from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from sqm160 import (InficonSQM160, SQM160Error, SQM160NotFound, list_candidates,
                    forget_connection)
from sqm160_engine import Monitor, default_connector, emulator_connector, format_duration
from sqm160_log import LogWriter, default_log_dir, export_run_settings, plot_samples, safe_name

ANGSTROM = "Å"


def _utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def _connect(args) -> InficonSQM160:
    if args.demo:
        return emulator_connector(progress=lambda m: print(m, file=sys.stderr))
    if args.port or args.url:
        sqm = InficonSQM160(args.port, args.baud, url=args.url)
        sqm.probe()
        return sqm
    return InficonSQM160.autoconnect(progress=lambda m: print(m, file=sys.stderr))


def _monitor(args) -> Monitor:
    if args.demo:
        connector = emulator_connector
    elif args.port or args.url:
        def fixed_connector(progress=None):
            sqm = InficonSQM160(args.port, args.baud, url=args.url)
            sqm.probe(progress=progress)
            return sqm
        connector = fixed_connector
    else:
        connector = default_connector
    return Monitor(interval=args.interval, connector=connector)


def cmd_ports(args) -> int:
    candidates = list_candidates()
    if not candidates:
        print("No serial ports found on this computer.")
        return 1
    for c in candidates:
        tag = "   <- Prolific PL2303 (the SQM-160's USB chip)" if c.is_prolific else ""
        print(f"{c.device:24} {c.ids}  {c.description}{tag}")
    return 0


def cmd_doctor(args) -> int:
    from sqm160_doctor import _main as doctor_main

    return doctor_main()


def cmd_status(args) -> int:
    try:
        sqm = _connect(args)
    except SQM160NotFound as exc:
        print(f"{exc}\n{exc.detail}\n\nRun 'sqm160 doctor' for a step-by-step check.")
        return 1
    with sqm:
        caps = sqm.capabilities
        print(f"Port           {sqm.port} at {sqm.baudrate} baud")
        print(f"Firmware       {caps.firmware}")
        print(f"Channels       {caps.channels}")
        print(f"Measured       {caps.summary()}")
        for note in caps.notes:
            print(f"  note         {note}")
        film = sqm.film(0)
        print(f"Active film    {film.name}  density {film.density} g/cm3, "
              f"tooling {film.tooling}%, z {film.z_ratio}, "
              f"final {film.final_thickness} k{ANGSTROM}, sensors {film.sensors}")
        print(f"Shutter        {'OPEN' if sqm.shutter_is_open() else 'closed'}")
        print(f"Average        {sqm.avg_rate():.2f} {ANGSTROM}/s, "
              f"{sqm.avg_thickness():.4f} k{ANGSTROM}")
        for i, r in enumerate(sqm.read_all(), start=1):
            life = ""
            try:
                life = f"  life {sqm.crystal_life(i):5.1f}%"
            except SQM160Error:
                pass
            print(f"  sensor {i}     {r.rate:7.2f} {ANGSTROM}/s  {r.thickness:9.4f} k{ANGSTROM}"
                  f"  {r.frequency:12.3f} Hz{life}")
    return 0


def cmd_monitor(args) -> int:
    mon = _monitor(args)
    state_seen = {"value": None}

    def on_event(event, payload):
        if event == "state" and payload is not state_seen["value"]:
            state_seen["value"] = payload
            print(f"\n[{payload.label}]")
        elif event == "error":
            print(f"\n! {payload}")

    mon.add_listener(on_event)
    mon.start()
    print("Monitoring. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(args.interval)
            s = mon.latest
            if s and mon.connected:
                remaining = format_duration(mon.time_remaining())
                print(f"\r{s.avg_rate:8.2f} {ANGSTROM}/s   {s.avg_thickness:9.4f} k{ANGSTROM}"
                      f"   shutter {'OPEN  ' if s.shutter else 'closed'}"
                      f"   left {remaining}   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        mon.stop()
    return 0


def cmd_log(args) -> int:
    out_dir = Path(args.out) if args.out else default_log_dir()
    label = safe_name(args.label or time.strftime("run_%Y%m%d_%H%M%S"))
    mon = _monitor(args)

    print("Waiting for the instrument... (Ctrl+C to give up)")
    mon.start()
    deadline = time.time() + args.wait
    while not mon.connected and time.time() < deadline:
        time.sleep(0.2)
    if not mon.connected:
        mon.stop()
        print("The instrument did not answer. Run 'sqm160 doctor' to find out why.")
        return 1

    sensors = max(1, mon.capabilities.channels)
    run = mon.start_run(label, zero=args.zero)
    writers = []
    for fmt in args.format:
        path = out_dir / f"{label}.{fmt}"
        writer = LogWriter(path, fmt, sensors=sensors, film=mon.film,
                           capabilities=mon.capabilities, run=run, note=args.note)
        writer.open()
        writer.attach(mon)
        writers.append(writer)
        print(f"Writing {path}")

    stop_at = time.time() + args.duration if args.duration else None
    try:
        while True:
            time.sleep(0.25)
            if stop_at and time.time() >= stop_at:
                break
            if args.until_final and mon.film and mon.film.final_thickness > 0:
                sample = mon.latest
                if sample and sample.avg_thickness >= mon.film.final_thickness:
                    print("\nFinal thickness reached.")
                    break
            sample = mon.latest
            if sample:
                print(f"\r{sample.avg_rate:8.2f} {ANGSTROM}/s  {sample.avg_thickness:9.4f} "
                      f"k{ANGSTROM}  {writers[0].rows:6d} rows  "
                      f"left {format_duration(mon.time_remaining())}   ", end="", flush=True)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        samples = mon.history()
        for writer in writers:
            writer.detach(mon)
            writer.close()
        mon.stop_run()
        settings = out_dir / f"{label}_settings.json"
        try:
            export_run_settings(settings, run=run, film=mon.film,
                                capabilities=mon.capabilities)
            print(f"\nSettings written to {settings}")
        except OSError as exc:
            print(f"\nCould not write the settings file: {exc}")
        if args.plot:
            try:
                path = plot_samples(samples, out_dir / f"{label}.png", title=label)
                print(f"Graph written to {path}")
            except RuntimeError as exc:
                print(f"No graph: {exc}")
        mon.stop()
    print(f"Done. {len(samples)} readings in {out_dir}")
    return 0


def cmd_films(args) -> int:
    try:
        sqm = _connect(args)
    except SQM160NotFound as exc:
        print(exc)
        return 1
    with sqm:
        if args.films_command == "list":
            first, last = args.range
            for n in range(first, last + 1):
                try:
                    film = sqm.film(n)
                except SQM160Error as exc:
                    print(f"{n:3d}  <error: {exc}>")
                    continue
                print(f"{n:3d}  {film.name:<9} density {film.density:6.2f}  "
                      f"tooling {film.tooling:3d}%  z {film.z_ratio:5.3f}  "
                      f"final {film.final_thickness:8.3f} k{ANGSTROM}  "
                      f"sensors {','.join(str(s) for s in film.sensors)}")
        elif args.films_command == "backup":
            path = Path(args.file)
            print(f"Saving every film to {path} - this takes about a minute.")
            sqm.backup(path, progress=lambda m: print(f"\r{m:<40}", end="", flush=True))
            print(f"\rSaved to {path}{' ' * 30}")
        elif args.films_command == "restore":
            path = Path(args.file)
            if not args.yes:
                answer = input(f"This overwrites the films stored in the instrument "
                               f"with {path}. Type yes to continue: ")
                if answer.strip().lower() != "yes":
                    print("Nothing was changed.")
                    return 1
            sqm.restore(path, progress=lambda m: print(f"\r{m:<40}", end="", flush=True))
            print("\rRestored." + " " * 30)
    return 0


def cmd_gui(args) -> int:
    try:
        from sqm160_gui import main as gui_main
    except ImportError as exc:
        print("The window needs the PySide6 and pyqtgraph packages, which are not "
              f"installed ({exc}).\nRun:  pip install PySide6 pyqtgraph\n"
              "Or start the program with the 'Start SQM-160' shortcut, which installs "
              "everything for you.")
        return 1
    return gui_main(demo=args.demo)


def cmd_forget(args) -> int:
    forget_connection()
    print("The remembered port was cleared. The next start will search again.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqm160",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="serial port (default: find it automatically)")
    parser.add_argument("--baud", type=int, default=19200)
    parser.add_argument("--url", help="pyserial URL, e.g. socket://192.168.1.200:2101")
    parser.add_argument("--demo", action="store_true",
                        help="use the built-in emulator instead of real hardware")
    parser.add_argument("--interval", type=float, default=0.5,
                        help="seconds between readings (default 0.5)")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)
    sub.add_parser("doctor", help="check the connection and explain any problem"
                   ).set_defaults(func=cmd_doctor)
    sub.add_parser("status", help="show what the instrument reports").set_defaults(func=cmd_status)
    sub.add_parser("monitor", help="live readings in the terminal").set_defaults(func=cmd_monitor)
    sub.add_parser("forget", help="forget the remembered port").set_defaults(func=cmd_forget)
    sub.add_parser("gui", help="open the window").set_defaults(func=cmd_gui)

    log = sub.add_parser("log", help="record a run to a file")
    log.add_argument("label", nargs="?",
                     help="name for the files (default: date and time). For the QCM cycle "
                          "analyser use coating_voc_1000ppm_50rh, e.g. 4vp_dvb_ace_1000ppm")
    log.add_argument("-d", "--duration", type=float, default=0,
                     help="stop after this many seconds (default: until Ctrl+C)")
    log.add_argument("-o", "--out", help="folder for the files "
                     f"(default: {default_log_dir()})")
    log.add_argument("-f", "--format", nargs="+", default=["csv"], choices=["csv", "txt"])
    log.add_argument("--plot", action="store_true", help="also save a PNG graph")
    log.add_argument("--zero", action="store_true", help="zero the thickness before starting")
    log.add_argument("--until-final", action="store_true",
                     help="stop when the film's final thickness is reached")
    log.add_argument("--note", default="", help="a line of text stored in the log header")
    log.add_argument("--wait", type=float, default=30,
                     help="seconds to wait for the instrument (default 30)")
    log.set_defaults(func=cmd_log)

    films = sub.add_parser("films", help="read, back up and restore stored films")
    films_sub = films.add_subparsers(dest="films_command", required=True)
    listing = films_sub.add_parser("list")
    listing.add_argument("--range", nargs=2, type=int, default=[1, 10], metavar=("FIRST", "LAST"))
    backup = films_sub.add_parser("backup")
    backup.add_argument("file")
    restore = films_sub.add_parser("restore")
    restore.add_argument("file")
    restore.add_argument("-y", "--yes", action="store_true", help="do not ask first")
    films.set_defaults(func=cmd_films)
    return parser


def main(argv=None) -> int:
    _utf8_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        args = parser.parse_args((argv or []) + ["gui"])
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except SQM160NotFound as exc:
        print(f"{exc}\n{exc.detail}")
        return 1
    except SQM160Error as exc:
        print(f"Instrument error: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
