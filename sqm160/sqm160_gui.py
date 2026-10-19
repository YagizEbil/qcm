from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

import pyqtgraph as pg

from sqm160 import Film, SystemParams1, SystemParams2, forget_connection
from sqm160_engine import (Monitor, State, default_connector, emulator_connector,
                           format_duration)
from sqm160_log import (LogWriter, default_log_dir, export_run_settings, plot_samples,
                        safe_name)

ANGSTROM = "Å"
APP_NAME = "SQM-160 Monitor"

DISPLAY_UNITS = {
    0: (f"{ANGSTROM}/s", f"k{ANGSTROM}"),
    1: ("nm/s", "µm"),
    2: ("Hz/s", "Hz"),
    3: ("ng/cm²/s", "µg/cm²"),
}

COLOR_RATE = "#1f77b4"
COLOR_THICK = "#d62728"
COLOR_OK = "#2e7d32"
COLOR_BUSY = "#ef6c00"
COLOR_BAD = "#c62828"


class Bridge(QtCore.QObject):
    sample = Signal(object)
    state = Signal(object)
    progress = Signal(str)
    error = Signal(str)
    capabilities = Signal(object)
    film = Signal(object)
    run = Signal(object)

    def listener(self, event: str, payload=None) -> None:
        signal = {"sample": self.sample, "state": self.state, "progress": self.progress,
                  "error": self.error, "capabilities": self.capabilities,
                  "film": self.film, "run": self.run}.get(event)
        if signal is not None:
            signal.emit(payload)


class Task(QtCore.QThread):

    note = Signal(str)
    done = Signal(object, str)

    def __init__(self, func, parent=None):
        super().__init__(parent)
        self._func = func

    def run(self) -> None:
        try:
            self.done.emit(self._func(self.note.emit), "")
        except Exception as exc:
            self.done.emit(None, str(exc))


def big_font(size: int, bold: bool = True) -> QtGui.QFont:
    font = QtGui.QFont()
    font.setPointSize(size)
    font.setBold(bold)
    return font


class Readout(QtWidgets.QFrame):
    def __init__(self, title: str, unit: str = "", color: str = "#222", size: int = 34):
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setStyleSheet("QFrame { background: palette(base); border: 1px solid "
                           "palette(mid); border-radius: 8px; }")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        self.title = QtWidgets.QLabel(title)
        self.title.setStyleSheet("color: palette(mid); border: none;")
        self.value = QtWidgets.QLabel("--")
        self.value.setFont(big_font(size))
        self.value.setStyleSheet(f"color: {color}; border: none;")
        self.unit = QtWidgets.QLabel(unit)
        self.unit.setStyleSheet("color: palette(mid); border: none;")
        layout.addWidget(self.title)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.value)
        row.addWidget(self.unit, alignment=Qt.AlignBottom)
        row.addStretch(1)
        layout.addLayout(row)

    def set(self, text: str, unit: str | None = None) -> None:
        self.value.setText(text)
        if unit is not None:
            self.unit.setText(unit)


class WaitingPage(QtWidgets.QWidget):
    check_requested = Signal()
    demo_requested = Signal()

    def __init__(self):
        super().__init__()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch(1)
        title = QtWidgets.QLabel("Looking for your SQM-160…")
        title.setFont(big_font(22))
        title.setAlignment(Qt.AlignCenter)
        self.detail = QtWidgets.QLabel("Checking the USB connection.")
        self.detail.setAlignment(Qt.AlignCenter)
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet("color: palette(mid);")
        self.hint = QtWidgets.QLabel(
            "Make sure the instrument is switched on and its USB cable is plugged in.\n"
            "If INFICON's Comm software is open, close it — only one program at a "
            "time can use the connection.")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)

        bar = QtWidgets.QProgressBar()
        bar.setRange(0, 0)
        bar.setMaximumWidth(420)
        bar.setTextVisible(False)

        buttons = QtWidgets.QHBoxLayout()
        check = QtWidgets.QPushButton("Connection check…")
        check.setMinimumHeight(38)
        check.clicked.connect(self.check_requested)
        demo = QtWidgets.QPushButton("Try it without the instrument")
        demo.setMinimumHeight(38)
        demo.clicked.connect(self.demo_requested)
        buttons.addStretch(1)
        buttons.addWidget(check)
        buttons.addWidget(demo)
        buttons.addStretch(1)

        for widget in (title, self.detail):
            layout.addWidget(widget)
        layout.addSpacing(10)
        layout.addWidget(bar, alignment=Qt.AlignCenter)
        layout.addSpacing(10)
        layout.addWidget(self.hint)
        layout.addSpacing(16)
        layout.addLayout(buttons)
        layout.addStretch(2)


class DoctorDialog(QtWidgets.QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connection check")
        self.resize(760, 560)
        self.report = None
        layout = QtWidgets.QVBoxLayout(self)

        self.status = QtWidgets.QLabel("Checking…")
        self.status.setFont(big_font(13))
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.list = QtWidgets.QTreeWidget()
        self.list.setHeaderLabels(["", "Check", "What it means"])
        self.list.setColumnWidth(0, 34)
        self.list.setColumnWidth(1, 190)
        self.list.setWordWrap(True)
        layout.addWidget(self.list, 1)

        self.detail = QtWidgets.QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(150)
        layout.addWidget(self.detail)
        self.list.currentItemChanged.connect(self._show_detail)

        row = QtWidgets.QHBoxLayout()
        self.fix_button = QtWidgets.QPushButton("Install the USB driver")
        self.fix_button.setVisible(False)
        self.fix_button.clicked.connect(self._install_driver)
        self.again = QtWidgets.QPushButton("Check again")
        self.again.clicked.connect(self.start)
        save = QtWidgets.QPushButton("Save this report…")
        save.clicked.connect(self._save)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(self.fix_button)
        row.addStretch(1)
        row.addWidget(save)
        row.addWidget(self.again)
        row.addWidget(close)
        layout.addLayout(row)
        self._task = None
        QtCore.QTimer.singleShot(50, self.start)

    def start(self) -> None:
        from sqm160_doctor import run_checks

        self.list.clear()
        self.detail.clear()
        self.fix_button.setVisible(False)
        self.again.setEnabled(False)
        self.status.setText("Checking…")
        self._task = Task(lambda note: run_checks(progress=note), self)
        self._task.note.connect(lambda m: self.status.setText(m))
        self._task.done.connect(self._finished)
        self._task.start()

    def _finished(self, report, error: str) -> None:
        self.again.setEnabled(True)
        if error or report is None:
            self.status.setText(f"The check itself ran into a problem: {error}")
            return
        self.report = report
        for check in report.checks:
            item = QtWidgets.QTreeWidgetItem([check.icon.strip("[] "), check.name, check.message])
            colour = {"ok": COLOR_OK, "warning": COLOR_BUSY,
                      "problem": COLOR_BAD}.get(check.status)
            if colour:
                item.setForeground(0, QtGui.QBrush(QtGui.QColor(colour)))
            item.setData(0, Qt.UserRole, check)
            self.list.addTopLevelItem(item)
        self.status.setText(report.summary)
        if any(c.action == "install_driver" for c in report.checks) and sys.platform == "win32":
            self.fix_button.setVisible(True)
        if self.list.topLevelItemCount():
            self.list.setCurrentItem(self.list.topLevelItem(0))

    def _show_detail(self, item, _previous) -> None:
        if not item:
            return
        check = item.data(0, Qt.UserRole)
        text = check.message + ("\n\nWhat to do:\n" + check.fix if check.fix else "")
        self.detail.setPlainText(text)

    def _install_driver(self) -> None:
        from sqm160_doctor import bundled_inf, install_windows_driver

        inf = bundled_inf()
        if not inf:
            QtWidgets.QMessageBox.warning(
                self, "Driver file missing",
                "The driver file ser2pl.inf is not next to the program, so it cannot be "
                "installed automatically.")
            return
        if QtWidgets.QMessageBox.question(
                self, "Install the USB driver",
                "Windows will ask for permission to install the Prolific driver "
                "(version 3.3.2.102). Press Yes on that prompt.\n\n"
                "Afterwards, unplug the instrument's USB cable and plug it back in.\n\n"
                "Continue?") != QtWidgets.QMessageBox.Yes:
            return
        ok, message = install_windows_driver(inf)
        QtWidgets.QMessageBox.information(self, "USB driver", message)
        if ok:
            self.start()

    def _save(self) -> None:
        if not self.report:
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save the report", str(Path.home() / "sqm160-connection-check.txt"),
            "Text files (*.txt)")
        if path:
            Path(path).write_text(self.report.text(), encoding="utf-8")


class CommunicationsDialog(QtWidgets.QDialog):

    def __init__(self, monitor: Monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.setWindowTitle("Communications")
        self.resize(520, 330)
        layout = QtWidgets.QVBoxLayout(self)

        caps = monitor.capabilities
        where = (f"{monitor.sqm.port} at {monitor.sqm.baudrate} baud"
                 if monitor.sqm else "not connected")
        info = QtWidgets.QLabel(f"<b>Now:</b> {where}<br><b>Instrument:</b> "
                                f"{caps.summary() if caps.firmware else 'unknown'}")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.auto = QtWidgets.QRadioButton("Find the instrument automatically (recommended)")
        self.auto.setChecked(True)
        self.manual = QtWidgets.QRadioButton("Always use this port:")
        layout.addWidget(self.auto)
        layout.addWidget(self.manual)

        row = QtWidgets.QHBoxLayout()
        self.ports = QtWidgets.QComboBox()
        self.baud = QtWidgets.QComboBox()
        from sqm160 import BAUD_RATES, list_candidates

        for c in list_candidates():
            self.ports.addItem(f"{c.device}  -  {c.description or c.ids}", c.device)
        for b in BAUD_RATES:
            self.baud.addItem(str(b), b)
        self.baud.setCurrentText("19200")
        row.addSpacing(24)
        row.addWidget(self.ports, 2)
        row.addWidget(self.baud, 1)
        layout.addLayout(row)

        note = QtWidgets.QLabel(
            "The baud rate must match the BAUDRATE setting in the instrument's own "
            "System menu. 19200 is the factory setting, and automatic mode tries every "
            "rate anyway, so this is almost never needed.")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        layout.addWidget(note)
        layout.addStretch(1)

        buttons = QtWidgets.QDialogButtonBox()
        forget = buttons.addButton("Forget the remembered port",
                                   QtWidgets.QDialogButtonBox.ResetRole)
        forget.clicked.connect(self._forget)
        buttons.addButton(QtWidgets.QDialogButtonBox.Ok)
        buttons.addButton(QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _forget(self) -> None:
        forget_connection()
        QtWidgets.QMessageBox.information(
            self, "Done", "The remembered port was cleared. The program will search "
            "again the next time it connects.")

    def chosen(self) -> tuple[str, int] | None:
        if self.auto.isChecked():
            return None
        return self.ports.currentData(), self.baud.currentData()


class SystemDialog(QtWidgets.QDialog):

    def __init__(self, monitor: Monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.setWindowTitle("System settings")
        self.resize(560, 560)
        self.s1: SystemParams1 | None = None
        self.s2: SystemParams2 | None = None

        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            "These settings change how the instrument itself measures. Only change them "
            "if you know what they do — the current values are read from the "
            "instrument and nothing is sent until you press Apply.")
        warning.setWordWrap(True)
        warning.setStyleSheet(f"color: {COLOR_BUSY};")
        layout.addWidget(warning)

        form1 = QtWidgets.QGroupBox("Measurement (System 1)")
        f1 = QtWidgets.QFormLayout(form1)
        self.timebase = QtWidgets.QDoubleSpinBox()
        self.timebase.setRange(0.10, 2.00)
        self.timebase.setSingleStep(0.05)
        self.timebase.setDecimals(2)
        self.timebase.setSuffix(" s")
        self.simulate = QtWidgets.QCheckBox("Simulate mode (the instrument invents a deposition)")
        self.display_mode = QtWidgets.QComboBox()
        self.display_mode.addItems([f"{ANGSTROM}/s and k{ANGSTROM}", "nm/s and µm",
                                    "Hz only", "ng/cm²/s and µg/cm²"])
        self.high_res = QtWidgets.QCheckBox(f"High rate resolution (0.01 {ANGSTROM}/s)")
        self.rate_filter = QtWidgets.QSpinBox()
        self.rate_filter.setRange(1, 20)
        f1.addRow("Timebase", self.timebase)
        f1.addRow("", self.simulate)
        f1.addRow("Display units", self.display_mode)
        f1.addRow("", self.high_res)
        f1.addRow("Rate averaging", self.rate_filter)
        self.tooling = []
        tooling_row = QtWidgets.QHBoxLayout()
        for i in range(6):
            spin = QtWidgets.QSpinBox()
            spin.setRange(10, 399)
            spin.setSuffix(" %")
            spin.setToolTip(f"Tooling factor for sensor {i + 1}")
            self.tooling.append(spin)
            tooling_row.addWidget(spin)
        f1.addRow("Crystal tooling", tooling_row)
        layout.addWidget(form1)

        form2 = QtWidgets.QGroupBox("Crystal window and analog outputs (System 2)")
        f2 = QtWidgets.QFormLayout(form2)
        self.min_f = self._spin(1.0, 6.4, 3, " MHz")
        self.max_f = self._spin(1.1, 6.5, 3, " MHz")
        self.min_rate = self._spin(-99, 999, 2, f" {ANGSTROM}/s")
        self.max_rate = self._spin(-99, 999, 2, f" {ANGSTROM}/s")
        self.min_thick = self._spin(0, 9999, 3, f" k{ANGSTROM}")
        self.max_thick = self._spin(0, 9999, 3, f" k{ANGSTROM}")
        self.etch = QtWidgets.QCheckBox("Etch mode (thickness counts down)")
        f2.addRow("Crystal frequency, minimum", self.min_f)
        f2.addRow("Crystal frequency, maximum", self.max_f)
        f2.addRow("Analog rate at 0 V", self.min_rate)
        f2.addRow("Analog rate at +5 V", self.max_rate)
        f2.addRow("Analog thickness at 0 V", self.min_thick)
        f2.addRow("Analog thickness at +5 V", self.max_thick)
        f2.addRow("", self.etch)
        layout.addWidget(form2)
        layout.addStretch(1)

        self.status = QtWidgets.QLabel("Reading the current settings…")
        self.status.setStyleSheet("color: palette(mid);")
        layout.addWidget(self.status)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Close)
        buttons.button(QtWidgets.QDialogButtonBox.Apply).clicked.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        QtCore.QTimer.singleShot(0, self._load)

    @staticmethod
    def _spin(low, high, decimals, suffix) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setDecimals(decimals)
        spin.setSuffix(suffix)
        return spin

    def _load(self) -> None:
        try:
            self.s1 = self.monitor.submit(lambda s: s.system1()).wait(8)
            self.s2 = self.monitor.submit(lambda s: s.system2()).wait(8)
        except Exception as exc:
            self.status.setText(f"Could not read the settings: {exc}")
            return
        self.timebase.setValue(self.s1.timebase)
        self.simulate.setChecked(self.s1.simulate)
        self.display_mode.setCurrentIndex(self.s1.display_mode)
        self.high_res.setChecked(self.s1.high_rate_resolution)
        self.rate_filter.setValue(self.s1.rate_filter)
        for spin, value in zip(self.tooling, self.s1.crystal_tooling):
            spin.setValue(int(value))
        for spin in self.tooling[len(self.s1.crystal_tooling):]:
            spin.setEnabled(False)
        self.min_f.setValue(self.s2.min_frequency)
        self.max_f.setValue(self.s2.max_frequency)
        self.min_rate.setValue(self.s2.min_rate)
        self.max_rate.setValue(self.s2.max_rate)
        self.min_thick.setValue(self.s2.min_thickness)
        self.max_thick.setValue(self.s2.max_thickness)
        self.etch.setChecked(self.s2.etch_mode)
        self.status.setText("These are the instrument's current settings.")

    def _apply(self) -> None:
        if QtWidgets.QMessageBox.question(
                self, "Send settings to the instrument",
                "The settings will be written to the SQM-160 now. Continue?"
        ) != QtWidgets.QMessageBox.Yes:
            return
        count = len(self.s1.crystal_tooling) if self.s1 else 6
        s1 = SystemParams1(self.timebase.value(), self.simulate.isChecked(),
                           self.display_mode.currentIndex(), self.high_res.isChecked(),
                           self.rate_filter.value(),
                           tuple(spin.value() for spin in self.tooling[:count]))
        s2 = SystemParams2(self.min_f.value(), self.max_f.value(), self.min_rate.value(),
                           self.max_rate.value(), self.min_thick.value(),
                           self.max_thick.value(), self.etch.isChecked())
        try:
            self.monitor.submit(lambda s: s.set_system1(s1)).wait(8)
            self.monitor.submit(lambda s: s.set_system2(s2)).wait(8)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Not accepted",
                                           f"The instrument did not accept the settings:\n{exc}")
            return
        self.status.setText("Sent. Reading them back…")
        self._load()


class FilmsDialog(QtWidgets.QDialog):

    COLUMNS = ["#", "Name", "Density", "Tooling", "Z-Ratio", "Final (k" + ANGSTROM + ")",
               "Setpoint", "Time (s)", "Sensors"]

    def __init__(self, monitor: Monitor, parent=None):
        super().__init__(parent)
        self.monitor = monitor
        self.setWindowTitle("Films")
        self.resize(860, 560)
        self.films: dict[int, Film] = {}

        layout = QtWidgets.QVBoxLayout(self)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Show films"))
        self.first = QtWidgets.QSpinBox()
        self.first.setRange(1, 99)
        self.first.setValue(1)
        self.last = QtWidgets.QSpinBox()
        self.last.setRange(1, 99)
        self.last.setValue(12)
        load = QtWidgets.QPushButton("Read from the instrument")
        load.clicked.connect(self.reload)
        top.addWidget(self.first)
        top.addWidget(QtWidgets.QLabel("to"))
        top.addWidget(self.last)
        top.addWidget(load)
        top.addStretch(1)
        backup = QtWidgets.QPushButton("Back up all films…")
        backup.clicked.connect(self._backup)
        restore = QtWidgets.QPushButton("Restore from a backup…")
        restore.clicked.connect(self._restore)
        top.addWidget(backup)
        top.addWidget(restore)
        layout.addLayout(top)

        self.table = QtWidgets.QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        layout.addWidget(self.table, 1)

        editor = QtWidgets.QGroupBox("Edit the selected film")
        form = QtWidgets.QFormLayout(editor)
        self.name = QtWidgets.QLineEdit()
        self.name.setMaxLength(8)
        self.density = QtWidgets.QDoubleSpinBox()
        self.density.setRange(0.5, 99.99)
        self.density.setDecimals(2)
        self.density.setSuffix(" g/cm³")
        self.tooling = QtWidgets.QSpinBox()
        self.tooling.setRange(10, 399)
        self.tooling.setSuffix(" %")
        self.zratio = QtWidgets.QDoubleSpinBox()
        self.zratio.setRange(0.1, 9.999)
        self.zratio.setDecimals(3)
        self.final = QtWidgets.QDoubleSpinBox()
        self.final.setRange(0, 9999)
        self.final.setDecimals(3)
        self.final.setSuffix(f" k{ANGSTROM}")
        self.setpoint = QtWidgets.QDoubleSpinBox()
        self.setpoint.setRange(0, 9999)
        self.setpoint.setDecimals(3)
        self.setpoint.setSuffix(f" k{ANGSTROM}")
        self.time_setpoint = QtWidgets.QSpinBox()
        self.time_setpoint.setRange(0, 5999)
        self.time_setpoint.setSuffix(" s")
        self.sensor_boxes = [QtWidgets.QCheckBox(str(i)) for i in range(1, 7)]
        sensors = QtWidgets.QHBoxLayout()
        for box in self.sensor_boxes:
            sensors.addWidget(box)
        sensors.addStretch(1)
        form.addRow("Name (8 letters)", self.name)
        form.addRow("Density", self.density)
        form.addRow("Tooling", self.tooling)
        form.addRow("Z-Ratio", self.zratio)
        form.addRow("Final thickness", self.final)
        form.addRow("Thickness setpoint", self.setpoint)
        form.addRow("Time setpoint", self.time_setpoint)
        form.addRow("Sensors used", sensors)
        layout.addWidget(editor)

        buttons = QtWidgets.QHBoxLayout()
        self.status = QtWidgets.QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        use = QtWidgets.QPushButton("Make this the active film")
        use.clicked.connect(self._activate)
        write = QtWidgets.QPushButton("Save to the instrument")
        write.setDefault(True)
        write.clicked.connect(self._write)
        close = QtWidgets.QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(self.status, 1)
        buttons.addWidget(use)
        buttons.addWidget(write)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        QtCore.QTimer.singleShot(0, self.reload)

    def reload(self) -> None:
        first, last = self.first.value(), max(self.first.value(), self.last.value())
        self.table.setRowCount(0)
        self.films.clear()
        self.status.setText("Reading…")
        QtWidgets.QApplication.processEvents()
        for number in range(first, last + 1):
            try:
                film = self.monitor.submit(lambda s, n=number: s.film(n)).wait(8)
            except Exception as exc:
                self.status.setText(f"Film {number}: {exc}")
                break
            self.films[number] = film
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [str(number), film.name, f"{film.density:.2f}", f"{film.tooling}",
                      f"{film.z_ratio:.3f}", f"{film.final_thickness:.3f}",
                      f"{film.thickness_setpoint:.3f}", f"{film.time_setpoint}",
                      ",".join(str(s) for s in film.sensors)]
            for col, text in enumerate(values):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(text))
            QtWidgets.QApplication.processEvents()
        self.status.setText(f"{len(self.films)} films read.")
        if self.table.rowCount():
            self.table.selectRow(0)

    def _selected_number(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        return int(self.table.item(rows[0].row(), 0).text())

    def _selection_changed(self) -> None:
        number = self._selected_number()
        film = self.films.get(number) if number else None
        if not film:
            return
        self.name.setText(film.name)
        self.density.setValue(film.density)
        self.tooling.setValue(film.tooling)
        self.zratio.setValue(film.z_ratio)
        self.final.setValue(film.final_thickness)
        self.setpoint.setValue(film.thickness_setpoint)
        self.time_setpoint.setValue(film.time_setpoint)
        for i, box in enumerate(self.sensor_boxes, start=1):
            box.setChecked(i in film.sensors)

    def _edited_film(self) -> Film:
        sensors = tuple(i for i, box in enumerate(self.sensor_boxes, start=1) if box.isChecked())
        return Film(self.name.text(), self.density.value(), self.tooling.value(),
                    self.zratio.value(), self.final.value(), self.setpoint.value(),
                    self.time_setpoint.value(), sensors or (1,))

    def _write(self) -> None:
        number = self._selected_number()
        if number is None:
            return
        film = self._edited_film()
        try:
            film.encode()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Check the values", str(exc))
            return
        if QtWidgets.QMessageBox.question(
                self, "Save the film",
                f"Film {number} in the instrument will be overwritten with these values.\n\n"
                "This cannot be undone unless you have a backup. Continue?"
        ) != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.monitor.submit(lambda s: s.set_film(number, film)).wait(8)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Not accepted",
                                           f"The instrument refused the film:\n{exc}")
            return
        self.status.setText(f"Film {number} saved.")
        self.reload()

    def _activate(self) -> None:
        number = self._selected_number()
        if number is None:
            return
        try:
            self.monitor.submit(lambda s: s.set_active_film(number)).wait(8)
            self.status.setText(f"Film {number} is now the active film.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Not accepted", str(exc))

    def _backup(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Back up every film",
            str(Path.home() / f"sqm160-films-{time.strftime('%Y%m%d')}.json"),
            "Backup files (*.json)")
        if not path:
            return
        progress = QtWidgets.QProgressDialog("Reading all 99 films…", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def job(note):
            return self.monitor.submit(lambda s: s.backup(path, progress=note)).wait(300)

        task = Task(job, self)
        task.note.connect(progress.setLabelText)
        task.done.connect(lambda _r, err: (progress.close(), self._after_backup(path, err)))
        task.start()
        self._task = task

    def _after_backup(self, path: str, error: str) -> None:
        if error:
            QtWidgets.QMessageBox.critical(self, "Backup failed", error)
        else:
            QtWidgets.QMessageBox.information(
                self, "Backup saved", f"Every film and both system blocks were saved to:\n{path}")

    def _restore(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Restore films from a backup", str(Path.home()), "Backup files (*.json)")
        if not path:
            return
        if QtWidgets.QMessageBox.warning(
                self, "Restore films",
                "Every film stored in the instrument will be replaced by the ones in this "
                "file.\n\nThis cannot be undone. Continue?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel
        ) != QtWidgets.QMessageBox.Yes:
            return
        progress = QtWidgets.QProgressDialog("Writing films…", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        def job(note):
            return self.monitor.submit(lambda s: s.restore(path, progress=note)).wait(300)

        task = Task(job, self)
        task.note.connect(progress.setLabelText)
        task.done.connect(lambda _r, err: (progress.close(), self.reload()))
        task.start()
        self._task = task


class LogSettingsDialog(QtWidgets.QDialog):
    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Data log settings")
        self.resize(540, 300)
        layout = QtWidgets.QFormLayout(self)

        self.folder = QtWidgets.QLineEdit(settings.value("log/folder", str(default_log_dir())))
        browse = QtWidgets.QPushButton("Choose…")
        browse.clicked.connect(self._browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.folder, 1)
        row.addWidget(browse)
        layout.addRow("Save logs in", row)

        self.csv = QtWidgets.QCheckBox("Spreadsheet file (.csv)")
        self.csv.setChecked(settings.value("log/csv", True, type=bool))
        self.txt = QtWidgets.QCheckBox("Text log (.txt), like INFICON's")
        self.txt.setChecked(settings.value("log/txt", True, type=bool))
        self.png = QtWidgets.QCheckBox("Picture of the graph (.png) when the run stops")
        self.png.setChecked(settings.value("log/png", True, type=bool))
        layout.addRow("Write", self.csv)
        layout.addRow("", self.txt)
        layout.addRow("", self.png)

        self.interval = QtWidgets.QDoubleSpinBox()
        self.interval.setRange(0.1, 60.0)
        self.interval.setSingleStep(0.1)
        self.interval.setDecimals(1)
        self.interval.setSuffix(" s")
        self.interval.setValue(settings.value("poll/interval", 0.5, type=float))
        layout.addRow("Reading every", self.interval)

        self.auto = QtWidgets.QCheckBox("Start recording by itself when the shutter opens")
        self.auto.setChecked(settings.value("log/auto", False, type=bool))
        layout.addRow("", self.auto)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _browse(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Where to save logs",
                                                          self.folder.text())
        if path:
            self.folder.setText(path)

    def _save(self) -> None:
        self.settings.setValue("log/folder", self.folder.text())
        self.settings.setValue("log/csv", self.csv.isChecked())
        self.settings.setValue("log/txt", self.txt.isChecked())
        self.settings.setValue("log/png", self.png.isChecked())
        self.settings.setValue("log/auto", self.auto.isChecked())
        self.settings.setValue("poll/interval", self.interval.value())
        self.accept()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.setWindowTitle(APP_NAME + (" — demo mode" if demo else ""))
        self.resize(1120, 760)
        self.settings = QtCore.QSettings("SabanciPSAL", "SQM160Monitor")
        self.demo = demo
        self.units = DISPLAY_UNITS[0]
        self.writers: list[LogWriter] = []
        self.recording = False
        self._last_shutter = False

        self.monitor = Monitor(
            interval=self.settings.value("poll/interval", 0.5, type=float),
            connector=emulator_connector if demo else default_connector)
        self.bridge = Bridge()
        self.bridge.sample.connect(self.on_sample)
        self.bridge.state.connect(self.on_state)
        self.bridge.progress.connect(self.on_progress)
        self.bridge.error.connect(self.on_error)
        self.bridge.capabilities.connect(self.on_capabilities)
        self.bridge.film.connect(self.on_film)
        self.monitor.add_listener(self.bridge.listener)

        self._build_ui()
        self._build_menus()
        self.monitor.start()

    def _build_ui(self) -> None:
        self.stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self.stack)

        self.waiting = WaitingPage()
        self.waiting.check_requested.connect(self.open_doctor)
        self.waiting.demo_requested.connect(self.switch_to_demo)
        self.stack.addWidget(self.waiting)

        dashboard = QtWidgets.QWidget()
        outer = QtWidgets.QVBoxLayout(dashboard)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        tiles = QtWidgets.QHBoxLayout()
        self.rate_tile = Readout("Rate", self.units[0], COLOR_RATE, 40)
        self.thick_tile = Readout("Thickness", self.units[1], COLOR_THICK, 40)
        self.time_tile = Readout("Deposition time", "", "#444", 26)
        self.left_tile = Readout("Time remaining", "", "#444", 26)
        for tile in (self.rate_tile, self.thick_tile, self.time_tile, self.left_tile):
            tiles.addWidget(tile, 1)
        outer.addLayout(tiles)

        pg.setConfigOptions(antialias=True)
        self.plot = pg.PlotWidget()
        self.plot.setBackground(None)
        item = self.plot.getPlotItem()
        item.showGrid(x=True, y=True, alpha=0.25)
        item.setLabel("bottom", "Time (minutes)")
        item.setLabel("left", f"Rate ({self.units[0]})")
        item.getAxis("left").setPen(pg.mkPen(COLOR_RATE))
        for side in ("left", "bottom", "right"):
            item.getAxis(side).enableAutoSIPrefix(False)
        self.rate_curve = item.plot(pen=pg.mkPen(COLOR_RATE, width=2))

        self.thick_view = pg.ViewBox()
        item.showAxis("right")
        item.scene().addItem(self.thick_view)
        item.getAxis("right").linkToView(self.thick_view)
        self.thick_view.setXLink(item)
        item.getAxis("right").setLabel(f"Thickness ({self.units[1]})", color=COLOR_THICK)
        item.getAxis("right").setPen(pg.mkPen(COLOR_THICK))
        self.thick_curve = pg.PlotCurveItem(pen=pg.mkPen(COLOR_THICK, width=2))
        self.thick_view.addItem(self.thick_curve)
        item.vb.sigResized.connect(self._sync_views)
        outer.addWidget(self.plot, 3)

        controls = QtWidgets.QHBoxLayout()
        self.shutter_button = QtWidgets.QPushButton("Open the shutter")
        self.shutter_button.setMinimumHeight(44)
        self.shutter_button.setCheckable(True)
        self.shutter_button.clicked.connect(self.toggle_shutter)
        self.record_button = QtWidgets.QPushButton("Start recording")
        self.record_button.setMinimumHeight(44)
        self.record_button.clicked.connect(self.toggle_recording)
        zero_thick = QtWidgets.QPushButton("Zero thickness")
        zero_thick.setMinimumHeight(44)
        zero_thick.clicked.connect(lambda: self.monitor.zero_thickness())
        zero_time = QtWidgets.QPushButton("Zero timer")
        zero_time.setMinimumHeight(44)
        zero_time.clicked.connect(lambda: self.monitor.zero_timer())
        for widget in (self.shutter_button, self.record_button, zero_thick, zero_time):
            controls.addWidget(widget, 1)
        outer.addLayout(controls)

        bottom = QtWidgets.QHBoxLayout()
        film_box = QtWidgets.QGroupBox("Active film")
        film_layout = QtWidgets.QFormLayout(film_box)
        self.film_label = QtWidgets.QLabel("—")
        self.film_label.setFont(big_font(14))
        self.film_detail = QtWidgets.QLabel("")
        self.film_detail.setWordWrap(True)
        self.film_chooser = QtWidgets.QSpinBox()
        self.film_chooser.setRange(1, 99)
        switch = QtWidgets.QPushButton("Use this film")
        switch.clicked.connect(self._switch_film)
        chooser = QtWidgets.QHBoxLayout()
        chooser.addWidget(self.film_chooser)
        chooser.addWidget(switch)
        film_layout.addRow(self.film_label)
        film_layout.addRow(self.film_detail)
        film_layout.addRow("Switch to film", chooser)
        bottom.addWidget(film_box, 1)

        self.sensor_table = QtWidgets.QTableWidget(0, 5)
        self.sensor_table.setHorizontalHeaderLabels(
            ["Sensor", "Rate", "Thickness", "Frequency (Hz)", "Crystal life"])
        self.sensor_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch)
        self.sensor_table.verticalHeader().setVisible(False)
        self.sensor_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        bottom.addWidget(self.sensor_table, 2)
        outer.addLayout(bottom, 2)

        self.stack.addWidget(dashboard)

        self.state_label = QtWidgets.QLabel("Starting…")
        self.note_label = QtWidgets.QLabel("")
        self.note_label.setStyleSheet("color: palette(mid);")
        self.statusBar().addPermanentWidget(self.state_label, 0)
        self.statusBar().addWidget(self.note_label, 1)

    def _sync_views(self) -> None:
        item = self.plot.getPlotItem()
        self.thick_view.setGeometry(item.vb.sceneBoundingRect())
        self.thick_view.linkedViewChanged(item.vb, self.thick_view.XAxis)

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("Save the data so far…", self.save_data)
        file_menu.addAction("Save a picture of the graph…", self.save_plot)
        file_menu.addAction("Open the logs folder", self.open_log_folder)
        file_menu.addSeparator()
        file_menu.addAction("Data log settings…", self.open_log_settings)
        file_menu.addSeparator()
        file_menu.addAction("Quit", self.close)

        inst = self.menuBar().addMenu("&Instrument")
        inst.addAction("Films…", self.open_films)
        inst.addAction("System settings…", self.open_system)
        inst.addAction("Communications…", self.open_communications)
        inst.addSeparator()
        inst.addAction("Zero thickness", lambda: self.monitor.zero_thickness())
        inst.addAction("Zero timer", lambda: self.monitor.zero_timer())

        view = self.menuBar().addMenu("&View")
        for label, minutes in (("Last 2 minutes", 2), ("Last 10 minutes", 10),
                               ("Last hour", 60), ("Whole run", 0)):
            action = view.addAction(label)
            action.setData(minutes)
            action.triggered.connect(lambda _checked=False, m=minutes: setattr(self, "_window", m))
        self._window = 10

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Connection check…", self.open_doctor)
        help_menu.addAction("What the numbers mean", self.show_units_help)
        help_menu.addAction(f"About {APP_NAME}", self.show_about)

    def on_state(self, state: State) -> None:
        self.state_label.setText(state.label)
        if state is State.CONNECTED:
            where = f"{self.monitor.sqm.port} at {self.monitor.sqm.baudrate} baud" \
                if self.monitor.sqm else ""
            self.state_label.setText(f"Connected — {where}")
            self.state_label.setStyleSheet(f"color: {COLOR_OK};")
            self.stack.setCurrentIndex(1)
        else:
            self.state_label.setStyleSheet(
                f"color: {COLOR_BAD if state is State.LOST else COLOR_BUSY};")
            if state in (State.SEARCHING, State.LOST):
                self.stack.setCurrentIndex(0)
                self.waiting.detail.setText(
                    self.monitor.last_error or "Checking the USB connection.")

    def on_progress(self, message: str) -> None:
        self.waiting.detail.setText(message)
        self.note_label.setText(message)

    def on_error(self, message: str) -> None:
        self.note_label.setText(message[:120])

    def on_capabilities(self, caps) -> None:
        try:
            s1 = self.monitor.submit(lambda s: s.system1()).wait(6)
            self.units = DISPLAY_UNITS.get(s1.display_mode, DISPLAY_UNITS[0])
        except Exception:
            self.units = DISPLAY_UNITS[0]
        self.rate_tile.set("--", self.units[0])
        self.thick_tile.set("--", self.units[1])
        item = self.plot.getPlotItem()
        item.setLabel("left", f"Rate ({self.units[0]})")
        item.getAxis("right").setLabel(f"Thickness ({self.units[1]})", color=COLOR_THICK)
        self.sensor_table.setHorizontalHeaderLabels(
            ["Sensor", f"Rate ({self.units[0]})", f"Thickness ({self.units[1]})",
             "Frequency (Hz)", "Crystal life"])
        self.note_label.setText(caps.notes[0] if caps.notes else "")

    def on_film(self, payload) -> None:
        _number, film = payload
        self.film_label.setText(film.name or "(no name)")
        self.film_detail.setText(
            f"Density {film.density:.2f} g/cm³ · tooling {film.tooling}% · "
            f"Z-Ratio {film.z_ratio:.3f}<br>Final thickness "
            f"{film.final_thickness:.3f} k{ANGSTROM} · sensors "
            f"{', '.join(str(s) for s in film.sensors)}")

    def on_sample(self, sample) -> None:
        self.rate_tile.set(f"{sample.avg_rate:,.2f}")
        self.thick_tile.set(f"{sample.avg_thickness:,.4f}")
        self.time_tile.set(format_duration(sample.deposit_time))
        self.left_tile.set(format_duration(self.monitor.time_remaining()))

        self.shutter_button.blockSignals(True)
        self.shutter_button.setChecked(sample.shutter)
        self.shutter_button.setText("Close the shutter" if sample.shutter
                                    else "Open the shutter")
        self.shutter_button.setStyleSheet(
            f"background: {COLOR_OK}; color: white; font-weight: bold;" if sample.shutter else "")
        self.shutter_button.blockSignals(False)

        if sample.shutter and not self._last_shutter:
            if self.settings.value("log/auto", False, type=bool) and not self.recording:
                self.start_recording()
        self._last_shutter = sample.shutter

        self._update_sensor_table(sample)
        self._update_plot()

    def _update_sensor_table(self, sample) -> None:
        count = len(sample.rates)
        if self.sensor_table.rowCount() != count:
            self.sensor_table.setRowCount(count)
        for i in range(count):
            life = sample.lives[i] if i < len(sample.lives) else float("nan")
            life_text = "--" if life != life else f"{life:.1f} %"
            values = [str(i + 1), f"{sample.rates[i]:.2f}", f"{sample.thicknesses[i]:.4f}",
                      f"{sample.frequencies[i]:,.1f}", life_text]
            for col, text in enumerate(values):
                cell = self.sensor_table.item(i, col)
                if cell is None:
                    cell = QtWidgets.QTableWidgetItem()
                    self.sensor_table.setItem(i, col, cell)
                cell.setText(text)
            if life == life and life > 90:
                self.sensor_table.item(i, 4).setForeground(QtGui.QBrush(QtGui.QColor(COLOR_BAD)))

    def _update_plot(self) -> None:
        samples = self.monitor.history(self._window * 60 if self._window else None)
        if not samples:
            return
        t0 = samples[0].t
        minutes = [(s.t - t0) / 60 for s in samples]
        self.rate_curve.setData(minutes, [s.avg_rate for s in samples])
        self.thick_curve.setData(minutes, [s.avg_thickness for s in samples])
        self._sync_views()

    def toggle_shutter(self) -> None:
        opening = self.shutter_button.isChecked()
        if opening and QtWidgets.QMessageBox.question(
                self, "Open the shutter",
                "The shutter will open and the film will start to grow. Continue?"
        ) != QtWidgets.QMessageBox.Yes:
            self.shutter_button.setChecked(False)
            return
        (self.monitor.open_shutter if opening else self.monitor.close_shutter)()

    def toggle_recording(self) -> None:
        self.stop_recording() if self.recording else self.start_recording()

    def start_recording(self) -> None:
        label, ok = QtWidgets.QInputDialog.getText(
            self, "Start recording",
            "Name for this run:\n\n"
            "The QCM cycle analyser reads the coating, the VOC, the\n"
            "concentration and the humidity from this name, so use\n"
            "the pattern  coating_voc_1000ppm_50rh\n"
            "for example   4vp_dvb_ace_1000ppm_50rh",
            text=time.strftime("run_%Y%m%d_%H%M%S"))
        if not ok:
            return
        label = safe_name(label)
        folder = Path(self.settings.value("log/folder", str(default_log_dir())))
        run = self.monitor.start_run(label, zero=False)
        sensors = max(1, len(self.monitor.latest.rates) if self.monitor.latest else 1)
        formats = [f for f, on in (("csv", self.settings.value("log/csv", True, type=bool)),
                                   ("txt", self.settings.value("log/txt", True, type=bool))) if on]
        self.writers = []
        try:
            for fmt in formats or ["csv"]:
                writer = LogWriter(folder / f"{label}.{fmt}", fmt, sensors=sensors,
                                   film=self.monitor.film,
                                   capabilities=self.monitor.capabilities, run=run)
                writer.open()
                writer.attach(self.monitor)
                self.writers.append(writer)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self, "Cannot write the log",
                f"The log file could not be created:\n{exc}\n\nChoose another folder in "
                "File > Data log settings.")
            return
        self.recording = True
        self.record_button.setText("Stop recording")
        self.record_button.setStyleSheet(f"background: {COLOR_BAD}; color: white; "
                                         "font-weight: bold;")
        self.statusBar().showMessage(f"Recording to {folder}", 6000)

    def stop_recording(self) -> None:
        samples = self.monitor.history()
        run = self.monitor.stop_run()
        folder = Path(self.settings.value("log/folder", str(default_log_dir())))
        label = run.label or "run"
        for writer in self.writers:
            writer.detach(self.monitor)
            writer.close()
        written = [str(w.path) for w in self.writers]
        self.writers = []
        self.recording = False
        self.record_button.setText("Start recording")
        self.record_button.setStyleSheet("")
        try:
            export_run_settings(folder / f"{label}_settings.json", run=run,
                                film=self.monitor.film,
                                capabilities=self.monitor.capabilities)
            written.append(str(folder / f"{label}_settings.json"))
        except OSError:
            pass
        if self.settings.value("log/png", True, type=bool):
            try:
                written.append(str(plot_samples(samples, folder / f"{label}.png", title=label)))
            except RuntimeError:
                pass
        QtWidgets.QMessageBox.information(
            self, "Recording finished",
            "Saved:\n" + "\n".join(written) if written else "Nothing was recorded.")

    def _switch_film(self) -> None:
        number = self.film_chooser.value()
        try:
            self.monitor.set_active_film(number).wait(8)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Not accepted", str(exc))

    def save_data(self) -> None:
        samples = self.monitor.history()
        if not samples:
            QtWidgets.QMessageBox.information(self, "Nothing yet",
                                              "There are no readings to save yet.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save the readings",
            str(Path(self.settings.value("log/folder", str(default_log_dir())))
                / time.strftime("sqm160_%Y%m%d_%H%M%S.csv")),
            "Spreadsheet (*.csv);;Text log (*.txt)")
        if not path:
            return
        from sqm160_log import export_samples

        fmt = "txt" if path.lower().endswith(".txt") else "csv"
        export_samples(samples, path, fmt, film=self.monitor.film,
                       capabilities=self.monitor.capabilities)
        self.statusBar().showMessage(f"Saved {path}", 6000)

    def save_plot(self) -> None:
        samples = self.monitor.history()
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save a picture of the graph",
            str(Path.home() / time.strftime("sqm160_%Y%m%d_%H%M%S.png")),
            "Picture (*.png);;PDF (*.pdf)")
        if not path:
            return
        try:
            plot_samples(samples, path, title=Path(path).stem)
            self.statusBar().showMessage(f"Saved {path}", 6000)
        except RuntimeError as exc:
            QtWidgets.QMessageBox.warning(self, "Could not save the picture", str(exc))

    def open_log_folder(self) -> None:
        folder = Path(self.settings.value("log/folder", str(default_log_dir())))
        folder.mkdir(parents=True, exist_ok=True)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(folder)))

    def open_log_settings(self) -> None:
        dialog = LogSettingsDialog(self.settings, self)
        if dialog.exec():
            self.monitor.interval = self.settings.value("poll/interval", 0.5, type=float)

    def open_films(self) -> None:
        if not self._require_connection():
            return
        FilmsDialog(self.monitor, self).exec()

    def open_system(self) -> None:
        if not self._require_connection():
            return
        SystemDialog(self.monitor, self).exec()

    def open_communications(self) -> None:
        dialog = CommunicationsDialog(self.monitor, self)
        if not dialog.exec():
            return
        chosen = dialog.chosen()
        self.monitor.stop()
        if chosen:
            port, baud = chosen

            def connector(progress=None):
                from sqm160 import InficonSQM160

                sqm = InficonSQM160(port, baud)
                sqm.probe(progress=progress)
                return sqm
            self.monitor.connector = connector
        else:
            self.monitor.connector = emulator_connector if self.demo else default_connector
        self.monitor.start()

    def open_doctor(self) -> None:
        DoctorDialog(self).exec()

    def switch_to_demo(self) -> None:
        self.demo = True
        self.setWindowTitle(APP_NAME + " — demo mode")
        self.monitor.stop()
        self.monitor.connector = emulator_connector
        self.monitor.start()

    def show_units_help(self) -> None:
        QtWidgets.QMessageBox.information(
            self, "What the numbers mean",
            f"Rate is how fast the film is growing, in {self.units[0]}.\n"
            f"Thickness is how much has been deposited, in {self.units[1]}.\n"
            "Crystal life is how much of the quartz crystal's useful range has been "
            "used up; replace the crystal when it passes about 90%.\n\n"
            "The units follow the display setting in the instrument's own System menu. "
            "If the instrument's front panel is set to nm, the numbers here are nm too.")

    def show_about(self) -> None:
        caps = self.monitor.capabilities
        QtWidgets.QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>A replacement for INFICON's Comm software that runs on "
            "Windows, macOS and Linux.<br><br>"
            f"<b>Instrument:</b> {caps.summary() if caps.firmware else 'not connected'}<br>"
            f"<b>Python:</b> {sys.version.split()[0]}")

    def _require_connection(self) -> bool:
        if self.monitor.connected:
            return True
        QtWidgets.QMessageBox.information(
            self, "Not connected",
            "The instrument is not connected yet, so its settings cannot be read.")
        return False

    def closeEvent(self, event) -> None:
        if self.recording and QtWidgets.QMessageBox.question(
                self, "Still recording",
                "A recording is still running. Stop it and close?"
        ) != QtWidgets.QMessageBox.Yes:
            event.ignore()
            return
        if self.recording:
            self.stop_recording()
        self.monitor.stop()
        event.accept()


def _excepthook(kind, value, tb) -> None:
    text = "".join(traceback.format_exception(kind, value, tb))
    print(text, file=sys.stderr)
    app = QtWidgets.QApplication.instance()
    if app:
        QtWidgets.QMessageBox.critical(
            None, "Something went wrong",
            f"{value}\n\nThe program will keep running. If this keeps happening, use "
            "Help > Connection check and send the saved report.")


def main(demo: bool = False) -> int:
    QtCore.QCoreApplication.setOrganizationName("SabanciPSAL")
    QtCore.QCoreApplication.setApplicationName("SQM160Monitor")
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationDisplayName(APP_NAME)
    sys.excepthook = _excepthook
    window = MainWindow(demo=demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(demo="--demo" in sys.argv))
