# SQM-160 Monitor

This program reads data from an INFICON SQM-160 rate/thickness monitor and records the data to files. It replaces the INFICON Comm software. It operates on macOS, Windows, and Linux.

This program writes the `.txt` log files that `qcm_cycle_analyzer.py` (in the parent folder) reads.

```
SQM-160  --USB-->  sqm160/  --run.txt-->  qcm_cycle_analyzer.py  -->  Δf per cycle
```

The two tools are independent. One tool does not import the other. The only connection between them is the layout of the `.txt` file (section 9).

Part A is for the operator of the instrument. Part B is for the developer.

---

# Part A: Operator manual

## 1. Functions

The program does these functions:

- It finds the instrument automatically. You do not select a port or a baud rate.
- It shows the rate, the thickness, the deposition time, and the time remaining.
- It shows a live graph of the rate and the thickness.
- It records a run to `.csv`, `.txt`, `.png`, and `.json` files.
- It opens and closes the shutter.
- It sets the thickness and the timer to zero.
- It reads, changes, backs up, and restores the 99 films in the instrument.
- It finds connection problems and tells you how to correct them.
- On Windows, it can install the USB driver.
- It has a demo mode. The demo mode operates without the instrument.

## 2. Requirements

- Python 3.9 or newer
- The packages in `requirements.txt`: pyserial, PySide6-Essentials, pyqtgraph, matplotlib

The setup script installs the packages. It puts them in one `.venv` folder in the parent folder of `sqm160`. Both tools in this repository use this `.venv` folder. Git ignores it. The setup script does not install packages into the Python of the operating system.

If the `sqm160` folder is not in a repository, the program uses `~/.sqm160/venv` instead.

## 3. Installation

Do the installation one time only. The installation takes some minutes. An internet connection is necessary.

### 3.1 macOS

1. Double-click `setup.command`.
2. When the window shows "Done", push Return to close the window.

If Python 3.9 or newer is not installed, the window tells you. Install Python from https://www.python.org/downloads/. Then double-click `setup.command` again.

### 3.2 Linux

1. Open a terminal in the `sqm160` folder.
2. Type `./setup.sh`.

If Python 3.9 or newer is not installed, install it with the package manager:

```
sudo apt install python3 python3-venv python3-tk
```

### 3.3 Windows

The first start does the installation. There is no separate setup step. Refer to section 4.

If Python is not installed, the Python download page opens.

1. Download and start the Python installer.
2. On the first page of the installer, select the check box "Add Python to PATH".
3. Click **Install Now**.
4. When the installation is complete, double-click `Start SQM-160.bat` again.

### 3.4 Packages for the analyzer

The setup script also installs `numpy` and `openpyxl`. `qcm_cycle_analyzer.py` uses these packages. Thus, one environment is sufficient for the two tools.

To install only the packages for the SQM-160 program, type this command:

```
./setup.command --sqm160-only
```

On Linux, use `./setup.sh --sqm160-only`.

## 4. Start the program

CAUTION: CLOSE THE INFICON COMM SOFTWARE BEFORE YOU START THIS PROGRAM. ONLY ONE PROGRAM AT A TIME CAN USE THE CONNECTION TO THE INSTRUMENT.

| System | Action |
|---|---|
| macOS | Double-click `Start SQM-160.command`. |
| Windows | Double-click `Start SQM-160.bat`. |
| Linux | Type `./start-sqm160.sh` in a terminal. |

The window opens in approximately 1 second.

To use the program without the instrument, click **Try it without the instrument** on the start screen. All functions operate with simulated readings.

## 5. Connect to the instrument

You do not select a port or a speed. The program tries each serial port on the computer. When the instrument replies, the program keeps the port and the baud rate. The next start is then immediate.

During the search, the window shows "Looking for your SQM-160…".

If the program does not find the instrument in some seconds, do these steps:

1. Make sure that the instrument is on.
2. Make sure that the USB cable is connected to the instrument and to the computer.
3. Make sure that the INFICON Comm software is closed.
4. Click **Connection check…**. Refer to section 8.

If you disconnect the USB cable during a run, the window shows "Connection lost - trying again". When you connect the cable again, the program connects again automatically. The log file keeps all readings until the disconnection.

## 6. The main window

### 6.1 Readouts

The four boxes at the top of the window show these values:

| Box | Description |
|---|---|
| Rate | The rate of film growth now |
| Thickness | The thickness of the film since the last zero |
| Deposition time | The time that the shutter is open in this run |
| Time remaining | The time until the film is at its final thickness |

When the time remaining shows `--:--`, the program cannot calculate it. Usually, this occurs because the film does not grow.

### 6.2 Graph

The graph shows the rate (blue, left axis) and the thickness (red, right axis) as a function of time.

To select the time range of the graph, use the **View** menu:

- Last 2 minutes
- Last 10 minutes
- Last hour
- Whole run

### 6.3 Buttons

| Button | Function |
|---|---|
| **Open the shutter** | Asks a question. When you click **Yes**, it opens the shutter. While the shutter is open, the button is green and shows **Close the shutter**. |
| **Start recording** | Asks for a name. Then it writes the readings to files. Click it again to stop the recording. |
| **Zero thickness** | Sets the thickness to zero |
| **Zero timer** | Sets the timer of the instrument to zero |

### 6.4 Sensor table

The table at the bottom right shows each sensor. The column *Crystal life* shows the used part of the quartz crystal.

When *Crystal life* is more than 90 %, the value is red. Replace the crystal soon.

### 6.5 Active film

The bottom left area shows the active film, with its density, tooling, and final thickness.

To use a different film:

1. Set the film number.
2. Click **Use this film**.

### 6.6 Menus

| Menu | Item | Function |
|---|---|---|
| File | Save the data so far… | Saves the readings of the current run |
| File | Save a picture of the graph… | Saves the graph as an image |
| File | Open the logs folder | Opens the folder with the log files |
| File | Data log settings… | Sets the log folder, the file types, and the reading interval (section 7.3) |
| Instrument | Films… | Shows and changes the stored films (section 7.4) |
| Instrument | System settings… | Shows and changes the system parameters (section 7.5) |
| Instrument | Communications… | Sets the port and the baud rate. The default is automatic. Use the manual setting only for unusual connections. |
| Instrument | Zero thickness, Zero timer | The same as the buttons |
| View | Last 2 minutes … Whole run | Time range of the graph |
| Help | Connection check… | Starts the connection check (section 8) |
| Help | What the numbers mean | Shows the units of the readouts |

## 7. Procedures

### 7.1 Record a run

1. Click **Start recording**.
2. Type a name for the run. Refer to section 7.2.
3. Do the deposition.
4. Click **Stop recording**.

A message shows the files that the program wrote. The default folder is **Documents → SQM-160 logs**.

| File | Contents |
|---|---|
| `name.csv` | A spreadsheet. You can open it in Excel or Origin. |
| `name.txt` | The log for `qcm_cycle_analyzer.py`. The film settings are at the top. |
| `name.png` | An image of the graph |
| `name_settings.json` | The film and instrument settings of the run. Use this file to do the run again with the same settings. |

The program writes each reading to the file immediately. If the computer stops during a run, you lose only the last reading.

### 7.2 Name a run for the analyzer

`qcm_cycle_analyzer.py` reads the coating, the VOC, the concentration, and the humidity from the file name. Thus, use this pattern for the name:

```
coating_voc_1000ppm_50rh
```

Examples:

- `4vp_dvb_ace_1000ppm`
- `pv4d4_dvb_ipa_500ppm`
- `4vp_dvb_meoh_1000ppm_50rh`

The window shows this pattern when it asks for the name.

### 7.3 Change the log settings

1. Select **File → Data log settings…**.
2. Set these values:
   - The folder for the log files
   - The file types: `.csv`, `.txt`, and `.png`
   - The interval between readings: 0.1 s to 60 s (default 0.5 s)
   - Automatic recording: the recording starts when the shutter opens
3. Click **OK**.

### 7.4 Back up the instrument settings

CAUTION: BACK UP THE FILMS BEFORE YOU CHANGE ANY FILM OR SYSTEM SETTING. THE CHANGES GO INTO THE INSTRUMENT, NOT ONLY INTO THE DISPLAY.

1. Select **Instrument → Films…**.
2. Click **Back up all films…**.
3. Select a file name.

The backup file contains the 99 films and the two system parameter blocks.

To restore the backup:

1. Select **Instrument → Films…**.
2. Click **Restore from a backup…**.
3. Select the backup file.

### 7.5 Change a film

1. Do the backup in section 7.4.
2. Select **Instrument → Films…**.
3. Select the film.
4. Change the values at the bottom of the dialog.
5. Click **Save to the instrument**.
6. In the question dialog, click **Yes**.

Film values and limits:

| Value | Unit | Range |
|---|---|---|
| Density | g/cm³ | 0.50 to 99.99 |
| Tooling | % | 10 to 399 |
| Z-ratio | — | 0.10 to 9.999 |
| Final thickness | kÅ | 0 to 9999 |
| Thickness setpoint | kÅ | 0 to 9999 |
| Time setpoint | s | 0 to 5999 (the instrument shows mm:ss) |
| Sensors | — | The sensors that the film averages, 1 to 6 |

The film name has 8 characters. It can contain spaces.

### 7.6 Change the system settings

1. Do the backup in section 7.4.
2. Select **Instrument → System settings…**.
3. Change the values.
4. Click **Apply**.

The program sends no value to the instrument until you click **Apply**.

System 1 contains these settings:

| Setting | Range |
|---|---|
| Timebase | 0.10 s to 2.00 s |
| Display mode | 0 = Å/s and kÅ, 1 = nm/s and µm, 2 = Hz only, 3 = ng/cm²/s and µg/cm² |
| High rate resolution | 0.01 Å/s instead of 0.1 Å/s |
| Rate averaging | 1 to 20 readings |
| Tooling for each sensor | 10 % to 399 % |
| Simulate mode | The instrument makes a simulated deposition. |

System 2 contains these settings:

- Minimum and maximum crystal frequency (MHz)
- Analog output scale: rate in Å/s at 0 V and at +5 V
- Analog output scale: thickness in kÅ at 0 V and at +5 V
- Etch mode: the thickness decreases

## 8. Connection problems

### 8.1 Start the connection check

1. Click **Connection check…** on the start screen, or select **Help → Connection check…**.
2. Read the result of each check.

The connection check examines these items:

1. The Python version
2. The pyserial package
3. The serial ports on the computer
4. The USB driver
5. Other programs that use the port
6. The reply from the instrument

Each check shows OK, WARNING, or PROBLEM. The check also shows a fix when one is available.

To send the result to a support person, click **Save this report…**. The program also keeps the last result in `~/.sqm160/last-check.json`.

### 8.2 Messages and corrections

**"Another program is already using COM3."**

1. Close the INFICON Comm software, or the other copy of this program.
2. Click **Check again**.

**"Windows has loaded the newest Prolific driver…"**

This is the most frequent problem on Windows. The USB chip of the instrument is an old Prolific PL2303 chip. The newest Prolific driver does not operate with this chip. Device Manager shows the device as *PL2303HXA PHASED OUT SINCE 2012*.

1. In the check window, click **Install the USB driver**.
2. When Windows asks for permission, click **Yes**.
3. Disconnect the USB cable of the instrument.
4. Connect the USB cable again.
5. Click **Check again**.

The computer can ask for an administrator password. If you do not know the password, speak to the administrator.

The program contains the driver file `ser2pl.inf` (version 3.3.2.102).

**"No Prolific driver appears to be loaded on this Mac."**

1. Install **PL2303 Serial** (Prolific Technology) from the Mac App Store. It is free.
2. Open **System Settings → Privacy & Security** and click **Allow** for the driver.
3. Restart the Mac.

**"This user account is not allowed to open /dev/ttyUSB0."** (Linux)

1. Type this command:

   ```
   sudo usermod -a -G dialout $USER
   ```

2. Log out.
3. Log in again.

**"The SQM-160 did not answer on any serial port."**

Usually, the instrument is off. The program tries all baud rates. If the problem continues, make sure that the System menu of the instrument shows 19200 baud.

## 9. The `.txt` log file

### 9.1 Columns

`qcm_cycle_analyzer.py` keeps only the lines that contain only numbers. The table has these columns:

| Column | Value |
|---|---|
| 0 | Time in s since the start of the run |
| 1 | Mean rate (Å/s) |
| 2 | Mean thickness (kÅ) |
| 3 | Shutter: 1 = open, 0 = closed |
| 4 | Deposition time in s |
| 5, 6, 7 | Sensor 1: frequency (Hz), rate, thickness |
| 8, 9, 10 | Sensor 2: frequency (Hz), rate, thickness |
| … | One group of three columns for each sensor. There is no column after the last sensor. |

The analyzer finds the frequency of sensor *c* in column `5 + 3·(c − 1)`. Thus, the sequence of the three values for each sensor is important. An extra column at the end causes the analyzer to find an additional sensor that does not exist.

Each cell contains a number. The program writes a number for a missing value, not an empty cell. An empty cell moves the columns.

### 9.2 Header

The lines above the table contain the film and instrument settings. Each header line contains a word. Thus, the analyzer ignores these lines.

## 10. File locations

| Item | Location |
|---|---|
| Logs | Documents → SQM-160 logs |
| The last port and baud rate | `~/.sqm160/connection.json` |
| The last connection check | `~/.sqm160/last-check.json` |
| The Python environment | The `.venv` folder in the parent folder of `sqm160` |

If you delete the `.sqm160` folder, the program searches for the instrument again at the next start. If you delete `.venv`, do the installation again. These folders contain no measurements.

To delete the last port from the terminal, type `sqm160_cli.py forget` (section 11).

## 11. Terminal commands

You can use all functions from a terminal. This is useful for long logs without an operator, and for your own scripts.

Type the commands from the repository folder:

```
.venv/bin/python sqm160/sqm160_cli.py <command>
```

On Windows, use `.venv\Scripts\python` instead of `.venv/bin/python`.

| Command | Function |
|---|---|
| `status` | Shows the instrument data and the measured capabilities |
| `ports` | Shows the serial ports |
| `doctor` | Does the connection check |
| `monitor` | Shows live readings |
| `forget` | Deletes the last port and baud rate |
| `gui` | Opens the window. This is the default command. |
| `log [name]` | Records a run (section 11.2) |
| `films list` | Shows the stored films |
| `films backup FILE` | Writes the 99 films and the two system blocks to FILE |
| `films restore FILE` | Writes the films and system blocks from FILE to the instrument |

### 11.1 General options

| Option | Function |
|---|---|
| `--demo` | Uses the built-in emulator instead of the instrument |
| `--port PORT` | Uses this serial port. Default: automatic search. |
| `--baud BAUD` | Baud rate. Default: 19200. |
| `--url URL` | A pyserial URL, for example `socket://192.168.1.200:2101` |
| `--interval S` | Time between readings in s. Default: 0.5. |

### 11.2 Options for `log`

| Option | Function |
|---|---|
| `name` | Name of the files. Default: the date and the time. |
| `-d S`, `--duration S` | Stops after S seconds. Default: until you push Ctrl+C. |
| `-o DIR`, `--out DIR` | Folder for the files. Default: Documents/SQM-160 logs. |
| `-f csv txt`, `--format csv txt` | File types. Default: `csv`. |
| `--plot` | Also writes a PNG graph |
| `--zero` | Sets the thickness to zero before the start |
| `--until-final` | Stops when the film is at its final thickness |
| `--note TEXT` | Writes one line of text in the log header |
| `--wait S` | Time in s to wait for the instrument. Default: 30. |

### 11.3 Options for `films`

| Option | Function |
|---|---|
| `list --range FIRST LAST` | Shows films FIRST to LAST. Default: 1 to 10. |
| `restore FILE -y` | Restores without a question |

### 11.4 Examples

```
.venv/bin/python sqm160/sqm160_cli.py status
.venv/bin/python sqm160/sqm160_cli.py log 4vp_dvb_ace_1000ppm -d 3600 -f csv txt --plot
.venv/bin/python sqm160/sqm160_cli.py films backup films.json
.venv/bin/python sqm160/sqm160_cli.py --demo gui
```

---

# Part B: Developer manual

## 12. Files

| File | Contents |
|---|---|
| `sqm160.py` | The driver: framing, CRC, the command set, auto-discovery, and capability probes. Its only dependency is pyserial. |
| `sqm160_engine.py` | The polling thread, the run state, the history, the reconnection, and the command queue |
| `sqm160_log.py` | The `.csv`, `.txt`, `.json`, and `.png` output |
| `sqm160_gui.py` | The window and its dialogs (PySide6 and pyqtgraph) |
| `sqm160_cli.py` | The terminal commands |
| `sqm160_doctor.py` | The connection check, with the Windows driver detection and installation |
| `sqm160_emulator.py` | A simulated SQM-160 that uses the real protocol |
| `test_sqm160.py` | 76 tests. They use the emulator. No instrument is necessary. |
| `bootstrap.py` | The first-start setup. The launchers use it when no environment exists. |
| `setup.command`, `setup.sh` | The one-time setup for macOS and Linux |
| `Start SQM-160.command`, `Start SQM-160.bat`, `start-sqm160.sh` | The launchers |
| `requirements.txt` | The Python packages |
| `ser2pl.inf` | The Prolific USB driver for Windows, version 3.3.2.102 |

## 13. Structure

The layers are strict:

```
sqm160_gui.py   sqm160_cli.py
        \           /
       sqm160_engine.py  ── sqm160_log.py
              |
          sqm160.py  ── sqm160_doctor.py
              |
           pyserial
```

- The GUI and the CLI use the engine.
- The engine uses the driver.
- The driver uses pyserial.
- No module above the engine uses the serial port.
- The driver has no data about the GUI.

## 14. Launchers and environment

Each launcher looks for Python in this sequence:

1. `../.venv`
2. `~/.sqm160/venv`
3. The system Python. Then the launcher starts `bootstrap.py`.

`bootstrap.py` uses only the Python standard library, because no other package is installed at the first start. It does these steps:

1. It makes sure that the Python version is 3.9 or newer.
2. It makes the virtual environment.
3. It installs the packages one at a time and shows a progress window. If tkinter is not available, it writes the progress to the terminal.
4. It starts the window.

`bootstrap.py` uses `../.venv` when the parent folder contains `.git` or `.venv`. In other conditions, it uses `~/.sqm160/venv`. Thus, the folder operates also when you copy it to a different location.

When an error occurs, `bootstrap.py` shows a message and offers the connection check.

## 15. Driver (`sqm160.py`)

### 15.1 Origin

The driver started from the PyExpLabSys `InficonSQM160` driver. The CRC function is the same. It gives the correct result for all 28 examples in manual 074-511-P1-G, section 8.4. The framing, the byte operations, the error processing, and the command set are new.

### 15.2 Transport

The USB port of the SQM-160 is a Prolific PL2303 USB-to-serial bridge (VID 067B, PID 2303). Thus, the instrument is a serial port:

| System | Port name |
|---|---|
| Windows | `COM3` (example) |
| Linux | `/dev/ttyUSB0` |
| macOS | `/dev/cu.P…` or `/dev/cu.usbserial-…` |

The serial settings are 8N1 without flow control (manual section 8.1). The reply timeout is 3 s.

The driver can use any pyserial-type transport. The transport must have `write(bytes)`, `read(n)`, and `reset_input_buffer()`. This includes USB, RS-232, and Ethernet with `url="socket://192.168.1.200:2101"`.

### 15.3 Packets

A command packet is `!` + length + message + CRC1 + CRC2. The CRC covers all bytes after the sync byte (manual section 8.3.3).

The driver reads the length byte of each reply. It does not use a fixed delay.

The film number is one byte: 48 + number. Film 0 is the active film. Films 80 to 99 give bytes above 127. Thus, the driver sends commands as bytes. The original driver sent them as UTF-8 text, and this gave an incorrect CRC.

### 15.4 Errors

| Exception | Cause |
|---|---|
| `SQM160Error` | Base class of all communication errors |
| `SQM160Timeout` | No valid reply after all retries |
| `SQM160CommandError` | The instrument rejected the command. Status C = invalid command. Status D = bad data. |
| `SQM160ConnectionLost` | The serial port disappeared, for example because the cable is disconnected |
| `SQM160NotFound` | No instrument replied on any port. The `detail` attribute shows what the search found. |

The driver tries a command again after a timeout or after a reply with a bad CRC.

### 15.5 Auto-discovery

`InficonSQM160.autoconnect()` finds the instrument. `discover()` does three passes. It stops at the first reply:

1. The port and baud rate in `~/.sqm160/connection.json`
2. Each port at 19200 baud, best candidates first
3. Each port at each supported baud rate. Bluetooth and console ports are not included in this pass.

The sequence of baud rates in pass 3 is 19200, 9600, 115200, 57600, 38400, 4800, 2400.

The sequence of ports is:

1. Prolific PL2303
2. Other USB-serial bridges: FTDI, Silicon Labs CP210x, WCH CH340/CH341
3. Other USB devices
4. Other COM ports

A port is the instrument only when it replies to `@` with a frame that has a correct CRC. Thus, the driver ignores a PL2303 cable that connects to a different device.

On macOS, each port has two device files. The driver uses only `/dev/cu.*`. The `/dev/tty.*` device waits for a carrier signal when it opens.

The worst case is approximately 4 s: no saved port, many ports, and no instrument. Usually, the first try is successful.

If the home folder is read-only, the program operates, but it does not keep the port.

### 15.6 Values that the manual does not specify

The manual does not specify three items. The driver measures them when it connects, and keeps the result in `Capabilities`. The test file tests each item in the two possible conditions.

| Item | Method | If the method fails |
|---|---|---|
| Does `W` give the thickness in Å or kÅ? | The driver compares the `W` thickness with the `N` thickness of the same sensor. `N` is in kÅ. A ratio near 1000 means Å. A ratio near 1 means kÅ. | The method needs a thickness that is not zero. Thus, it usually fails at connection. The driver then uses Å (the value that the manual implies) and shows a note. The engine tries again each fourth poll until a film grows. |
| Does the rate command need the `?` suffix? | The driver sends `L1?`. If the instrument replies "invalid command", the driver sends `L1`. The driver then uses only that form. | If the instrument rejects the two forms, the driver keeps a note. Rate readings then give an error. |
| How many tooling values does a 2-channel unit give? | The driver counts the fields in the reply to `B?`. | This method cannot fail. |

`*_confirmed` in `Capabilities` is `True` when the driver measured the value. It is `False` when the driver uses the value from the manual.

### 15.7 Display units

The window labels the values with the units of the display mode (System 1, parameter 3). The manual does not tell if the serial values change with the display mode. If the serial values are always in Å, change only `DISPLAY_UNITS` in `sqm160_gui.py`.

### 15.8 Methods

| Method | Function |
|---|---|
| `version()` | Firmware version, for example `MON Ver 4.13` |
| `channels()` | Number of sensor channels (2 or 6) |
| `film(n)`, `set_film(n, film)` | Reads or writes film 1 to 99. 0 is the active film. |
| `rate(s)` | Rate of one sensor, Å/s |
| `thickness(s)` | Thickness of one sensor, kÅ |
| `frequency(s)` | Crystal frequency, Hz |
| `crystal_life(s)` | Used crystal life, % |
| `read_all()` | Rate, thickness (kÅ), and frequency of all sensors in one command (`W`) |
| `zero()` | Sets the mean and sensor thickness and rate to zero |
| `power_up_flag()` | `True` one time after the instrument starts. The read clears the flag. |
| `probe()` | Measures the capabilities. It is read-only. |
| `backup(path)`, `restore(path)` | Writes or reads all films and the two system blocks as JSON |
| `reset_to_defaults(confirm=True)` | Resets all films and system parameters. The GUI cannot call this method. |

WARNING: DO NOT CALL `reset_to_defaults()` WITHOUT A BACKUP. IT DELETES ALL FILMS AND SYSTEM PARAMETERS IN THE INSTRUMENT.

Example:

```python
from sqm160 import InficonSQM160

with InficonSQM160.autoconnect() as sqm:
    print(sqm.avg_rate(), sqm.avg_thickness())
```

## 16. Engine (`sqm160_engine.py`)

`Monitor` owns the connection and the polling thread. Other code adds a listener:

```python
mon = Monitor()
mon.add_listener(lambda event, data: print(event, data))
mon.start()
```

`start()` does not block. The engine connects automatically and tries again after an error.

### 16.1 Events

| Event | Payload |
|---|---|
| `state` | A `State` value |
| `progress` | A text about the connection attempt |
| `sample` | A `Sample`. Thickness in kÅ, rate in Å/s. |
| `capabilities` | A `Capabilities` object. The engine sends it one time for each connection, and again when a measurement is complete. |
| `film` | `(number, Film)` when the active film changes |
| `error` | A message for the operator |
| `run` | A `RunInfo` when a run starts or stops |

An error in a listener does not stop the engine.

### 16.2 Reconnection

The engine continues to operate when you disconnect the instrument, turn it off, or connect it to a different USB socket. When a `SerialException` occurs:

1. The driver changes it to `SQM160ConnectionLost`.
2. The engine closes the port.
3. The state changes to `LOST`.
4. The engine starts the discovery again. The delay between attempts increases from 1 s to 10 s.

A test disconnects and connects the emulator during a run.

### 16.3 Commands from the GUI

The GUI sends each instrument write through `Monitor.submit()`. The engine runs the command on the polling thread between two polls. Thus, only one thread uses the port, and frames do not mix.

The GUI receives the engine events on the polling thread. A queued Qt signal moves them to the GUI thread.

### 16.4 Calculated values

- The deposition time increases only while the shutter is open.
- `smoothed_rate()` is the mean rate of the last few seconds.
- `time_remaining()` is `None` when there is no final thickness, when the film does not grow, or when the rate is not stable.
- If the instrument does not reply to the `W` command, the engine reads each sensor separately.

## 17. Log output (`sqm160_log.py`)

| Format | Contents |
|---|---|
| `csv` | One row for each poll and one column for each value. For Excel, Origin, and pandas. An empty cell shows a missing value. |
| `txt` | A tab-separated table with a header. The layout agrees with `qcm_cycle_analyzer.py` (section 9). |
| `json` | The film, the system parameters, and the capabilities. Use it to do the run again. |
| `png` | A graph of rate and thickness. The graph shades the periods when the shutter is open. PDF and SVG are also possible. |

The writers flush the file after each row. A disk error does not stop the run.

If matplotlib is not installed, `plot_samples()` raises `RuntimeError` with a clear message. The caller can then offer the CSV file.

`safe_name()` makes a file name that is valid on Windows, macOS, and Linux.

## 18. Emulator (`sqm160_emulator.py`)

`FakeSQM160` uses the real protocol. While the shutter is open, it simulates a deposition. It closes the shutter at the final thickness, as the real instrument does.

| Parameter | Function |
|---|---|
| `thickness_unit` | The unit of the `W` thickness: `"A"` or `"kA"` |
| `accept_rate_query` | `False` makes the emulator accept only `L1`, not `L1?` |
| `channels` | Number of channels. This also sets the number of tooling values in the `B` reply. |
| `drop_next` | The emulator ignores this number of next commands. |
| `corrupt_next` | The emulator sends this number of replies with a bad CRC. |

## 19. Tests

Type this command from the repository folder:

```
.venv/bin/python -m pytest sqm160/test_sqm160.py -q
```

The 76 tests use the emulator. No instrument is necessary. The tests have four groups:

| Group | Contents |
|---|---|
| Protocol | Framing and CRC against all examples in manual section 8.4 |
| Driver | Commands through the emulator, retries, and auto-discovery |
| Measured | The three items of section 15.6, each in the two conditions |
| App | The engine, the log writers, and the connection check |

Four tests make sure that `qcm_cycle_analyzer.py` can read the `.txt` log, for 1, 2, and 6 sensors. These tests contain a copy of the read rules of the analyzer. They do not import the analyzer. Thus, the two tools stay independent. If the log layout changes, these tests fail.

## 20. First session with the instrument

Only steps 6 and 7 write to the instrument. You can reverse the two steps.

1. Prepare the environment:
   1. Type `pip install pyserial pytest`.
   2. Type `pytest test_sqm160.py`. All 76 tests must pass.
   3. Type `python sqm160_cli.py --demo gui` to see the window with the emulator.
2. Connect:
   1. Type `python sqm160_cli.py doctor`. The output shows the port, the baud rate, and the capabilities.
   2. If the Prolific driver is the phased-out version, type `python sqm160_doctor.py --fix-driver`. This installs `ser2pl.inf`.
3. Type `python sqm160_cli.py status`. Examine these values:
   - The firmware version
   - The number of channels
   - The form of the rate command
   - The number of tooling values
   - The active film. A film name with a space must show correctly.
   - The shutter state
4. Type `python sqm160_cli.py films backup films-original.json`. Keep this file.
5. Do the thickness unit check:
   1. Select **Instrument → System settings… → Simulate**.
   2. Open the shutter.
   3. Look at the status bar. In some seconds, it changes from *assumed* to "Read-all thickness confirmed as …".
   4. Set Simulate mode to off.
6. Do the film write check:
   1. In the Films dialog, write to an unused film with a number of 80 or more. These films use command bytes above 127.
   2. Read the film again.
   3. Restore the backup from step 4.
7. Do the disconnection check:
   1. Disconnect the USB cable during a run. The window must show "Connection lost - trying again".
   2. Connect the cable again. The program must connect again automatically.
   3. Make sure that the log file contains all readings before the disconnection.

## 21. Open items

- **Packaging.** The launchers are sufficient for the laboratory computer. A single `.exe` file (PyInstaller) can remove the Python installation step for other groups. You must build it on Windows.
- **Comparison with Comm.** On Windows, record the same deposition with this program and with Comm, one program at a time. Make sure that the rate, the thickness, and the time agree.
- **macOS driver.** It is not known if the Prolific App Store driver supports this chip. If it does not, use an FTDI USB-to-RS-232 adapter on the RS-232 connector of the instrument. The driver supports this adapter without code changes. A custom libusb layer for the PL2303 is the last option.
