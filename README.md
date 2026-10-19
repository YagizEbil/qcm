# QCM Cycle Analyzer

`qcm_cycle_analyzer.py` analyzes data from polymer-coated QCM sensors for VOC detection. The data comes from SQM-160 log files (`.txt`).

Project: ENS 491, Polymer Based Novel Gas Sensors for VOC Detection.

## 1. Description

The script does these operations:

1. It reads one or more SQM-160 log files.
2. It calculates the frequency shift `Δf = f0 − f`. The value `f0` is the first frequency in the file.
3. It finds the sudden changes in the signal and shows them in a window.
4. You examine the marks in the window and correct them with the mouse.
5. It calculates the frequency shift and other values for each cycle.
6. It writes plots, a table for each file, and one table for all files.

A cycle starts at gas ON and stops at gas OFF. Gas ON is the start of the VOC exposure. Gas OFF is the end of the exposure and the start of the purge.

The table for all files has one row for each cycle. You can use this table as a dataset for machine learning.

## 2. Requirements

- Python 3
- numpy
- matplotlib
- openpyxl (necessary only for Excel output)

## 3. Installation

1. Open a terminal.
2. Type this command:

   ```
   pip install numpy matplotlib
   ```

3. To get Excel output, type this command:

   ```
   pip install openpyxl
   ```

## 4. Data file names

The script reads the coating, the VOC, the concentration, and the humidity from the file name.

Use these rules for file names:

- Put an underscore between the parts of the name.
- Write the concentration as a number followed by `ppm`. Example: `1000ppm`.
- Write the humidity as a number followed by `rh`. Example: `50rh` is 50 % relative humidity.

Examples of correct file names:

| File name | Coating | VOC | Concentration | Humidity |
|---|---|---|---|---|
| `4vp_dvb_ace_1000ppm.txt` | 4VP-DVB | Acetone | 1000 ppm | — |
| `pv4d4_dvb_ipa_500ppm.txt` | pV4D4-DVB | IPA | 500 ppm | — |
| `4vp_dvb_meoh_1000ppm_50rh.txt` | 4VP-DVB | Methanol | 1000 ppm | 50 % RH |

The script knows these VOC codes:

| Code in file name | VOC |
|---|---|
| `ace`, `acetone` | Acetone |
| `ipa`, `isopropanol` | IPA |
| `meth`, `methanol`, `meoh` | Methanol |
| `eth`, `ethanol`, `etoh` | Ethanol |
| `water`, `h2o` | Water |
| `tol`, `toluene` | Toluene |

If the script cannot find a value in the file name, it writes `?` for that value.

## 5. Procedure

### 5.1 Start the analysis

1. Open a terminal in the folder that contains the data files.
2. To analyze one file, type this command:

   ```
   python qcm_cycle_analyzer.py 4vp_dvb_ace_1000ppm.txt
   ```

3. To analyze more than one file, type the names of all the files:

   ```
   python qcm_cycle_analyzer.py file1.txt file2.txt
   ```

4. To analyze all the `.txt` files in the folder, type this command:

   ```
   python qcm_cycle_analyzer.py *.txt
   ```

The script opens one window for each file. The window shows the automatic marks.

### 5.2 Correct the marks in the window

Each mark is a colored band on the plot:

- A yellow band is a gas ON mark.
- A green band is a gas OFF mark.
- A gray band is a sudden change that is not gas ON or gas OFF.

The script names the marks from left to right in this sequence: ON, OFF, ON, OFF. Thus, you only put a mark at each sudden change. The script gives the name.

1. To add a mark, left-click near a sudden change.
2. To remove a mark, right-click near the mark.
3. To cancel the last change, click **Undo**.
4. To remove all marks, click **Clear all**.
5. To go back to the automatic marks, click **Automatic**.

The plot shows the `Δf` value of each cycle. The value changes immediately after each click.

NOTE: A left-click mark moves to the nearest sudden change. The search area is 4 s on each side of the click. To stop this movement, set `SNAP_TO_JUMP` to `False`.

### 5.3 Zoom into the plot

1. Click the magnifier icon in the toolbar.
2. Drag a rectangle on the plot.
3. To put marks again, click the magnifier icon a second time.

NOTE: While the magnifier is on, a click does not add or remove a mark.

### 5.4 Calculate the results

1. Click **Done - calculate**.
2. Do steps 5.2 to 5.4 for each window that opens.

The script writes the results to the folder `QCM_results`. This folder is in the same folder as the first data file.

The script also keeps your marks in the file `<name>_selection.txt`. When you analyze the same file again, the window starts with these marks. To start again from the automatic marks, delete this file.

### 5.5 Analyze without the window

To use only the automatic marks, add `--auto` to the command:

```
python qcm_cycle_analyzer.py *.txt --auto
```

The script opens no windows. It writes the results immediately.

CAUTION: EXAMINE THE FILE `<name>_cycles.png` FOR EACH DATA FILE BEFORE YOU USE THE RESULTS FROM `--auto`. IF THE SCRIPT DID NOT FIND A SUDDEN CHANGE, THE RESULTS FOR THAT CYCLE CAN BE INCORRECT OR ABSENT.

## 6. Output files

The script writes these files to `QCM_results`. In the table, `<name>` is the name of the data file without `.txt`.

| File | Contents |
|---|---|
| `<name>_cycles.png` | Plot of the signal, the marks, and the `Δf` of each cycle |
| `<name>_overlay.png` | Plot of all cycles of one file on the same axes. Each cycle starts at 0 s and 0 Hz. Use this plot to compare the cycles. |
| `<name>_cycles.csv` | One row for each cycle (section 7) |
| `<name>_events.csv` | One row for each mark: number, name, time, step, direction |
| `<name>_results.xlsx` | The two tables above in one Excel file |
| `<name>_report.txt` | Text report: marks, cycles, and summary |
| `<name>_selection.txt` | The marks from the window |
| `ALL_cycles.csv` | The cycles of all files in one table. This is the machine-learning dataset. |
| `ALL_summary.csv` | One row for each file (section 8) |
| `ALL_results.xlsx` | The two tables above in one Excel file |
| `ALL_table.tex` | LaTeX table for the report. It uses the `booktabs` package. |
| `ALL_comparison.png` | Bar chart of the mean `Δf` for each file, with the standard deviation. The script makes this chart only when there are two or more files. |

If openpyxl is not installed, the script does not write the `.xlsx` files.

## 7. Cycle values

Each row of `<name>_cycles.csv` and `ALL_cycles.csv` contains these values. The sign of all Hz values agrees with the setting `DELTA_F_SIGN` (section 9).

| Column | Unit | Description |
|---|---|---|
| `cycle` | — | Cycle number |
| `t_on_s` | s | Time of gas ON |
| `t_off_s` | s | Time of gas OFF |
| `exposure_s` | s | Time from gas ON to gas OFF |
| `purge_s` | s | Time from gas OFF to the next gas ON |
| `baseline_Hz` | Hz | Median signal in the last 5 s before gas ON |
| `end_of_exposure_Hz` | Hz | Median signal in the last 5 s before gas OFF |
| `dF_cycle_Hz` | Hz | **Main result.** `end_of_exposure_Hz` minus `baseline_Hz` |
| `dF_peak_Hz` | Hz | Maximum signal during the exposure minus `baseline_Hz` |
| `response_time_s` | s | Time from gas ON until the signal is at 90 % of `dF_peak_Hz` (t90) |
| `switch_step_Hz` | Hz | The fast step at gas OFF. Usually, a change of flow or pressure causes this step. It is not desorption. |
| `recovered_Hz` | Hz | The part of `Δf` that goes back during the purge |
| `recovery_pct` | % | `recovered_Hz` / `dF_cycle_Hz` × 100 |
| `slope_initial_Hz_per_s` | Hz/s | Slope in the first 10 s of the exposure. This is the initial rate of adsorption. |
| `slope_final_Hz_per_s` | Hz/s | Slope in the last 20 s of the exposure. A value near 0 shows saturation of the coating. |
| `area_Hz_s` | Hz·s | Area under the signal during the exposure. This value is a good feature for machine learning. |
| `mass_ng_per_cm2` | ng/cm² | Adsorbed mass from the Sauerbrey equation |
| `sensitivity_Hz_per_ppm` | Hz/ppm | `dF_cycle_Hz` / concentration |

`ALL_cycles.csv` also contains the columns `file`, `coating`, `voc`, `concentration_ppm`, and `humidity_RH`.

## 8. File summary values

Each row of `ALL_summary.csv` contains these values for one file.

| Column | Description |
|---|---|
| `n_cycles` | Number of complete cycles |
| `dF_mean_Hz`, `dF_std_Hz` | Mean and standard deviation of `dF_cycle_Hz` |
| `repeatability_CV_pct` | Coefficient of variation of `dF_cycle_Hz`, in % |
| `t90_mean_s`, `t90_std_s` | Mean and standard deviation of the response time |
| `recovery_mean_pct`, `recovery_std_pct` | Mean and standard deviation of the recovery |
| `baseline_drift_Hz_per_cycle` | Change of the baseline from the first cycle to the last cycle, divided by the number of cycles minus 1 |
| `max_shift_from_start_Hz` | Maximum shift from the first point of the file. This value contains the baseline drift. Table 3 of Progress Report I used this method. |
| `noise_rms_Hz` | RMS noise of the signal |
| `sensitivity_Hz_per_ppm` | `dF_mean_Hz` / concentration |
| `LOD_estimate_ppm` | Limit of detection: 3 × noise / sensitivity |
| `mass_mean_ng_per_cm2` | Mean adsorbed mass |
| `f0_Hz` | First frequency in the file |
| `channel` | SQM-160 channel that the script used |

CAUTION: MEASURE MORE THAN ONE CONCENTRATION BEFORE YOU USE `LOD_ESTIMATE_PPM`. THE ESTIMATE IS CORRECT ONLY IF THE SENSOR RESPONSE IS LINEAR.

## 9. Settings

The settings are at the top of `qcm_cycle_analyzer.py`. To change a setting, change its value in the file.

### 9.1 General settings

| Setting | Default | Description |
|---|---|---|
| `OUTPUT_FOLDER` | `None` | Folder for the results. `None` puts the results in `QCM_results` near the data files. |
| `FREQ_CHANNEL` | `"auto"` | SQM-160 channel (1, 2, 3, …). `"auto"` uses the first channel with a frequency of more than 1 kHz. |
| `DELTA_F_SIGN` | `"f0_minus_f"` | `"f0_minus_f"` shows adsorption as a positive value. `"f_minus_f0"` shows adsorption as a negative value. |

### 9.2 Window settings

| Setting | Default | Description |
|---|---|---|
| `HAND_SELECTION` | `True` | `False` opens no window. This is the same as `--auto`. |
| `SNAP_TO_JUMP` | `True` | `True` moves a click to the nearest sudden change. |
| `SNAP_WINDOW_S` | `4.0` | Time in s on each side of the click for `SNAP_TO_JUMP` |
| `REUSE_SAVED_SELECTION` | `True` | `True` starts the window with the marks from `<name>_selection.txt` |

### 9.3 Settings for the automatic marks

| Setting | Default | Description |
|---|---|---|
| `EVENT_LABELING` | `"auto"` | `"auto"`: an increase is gas ON and a decrease is gas OFF. They must alternate. Other changes are gray. `"alternate"`: the script names all sudden changes ON, OFF, ON, OFF. Use `"alternate"` if the direction of the changes is not clear. |
| `SENSITIVITY` | `6.0` | A change is sudden if it is larger than `SENSITIVITY` × noise. A lower value finds more and smaller changes. Usual range: 4 to 10. |
| `MIN_JUMP_HZ` | `0.8` | Minimum size in Hz of a sudden change. This setting prevents false marks in data with very low noise. |
| `MERGE_WINDOW_S` | `8.0` | The script combines sudden changes that are less than this time (s) apart into one mark. |

### 9.4 Settings for the cycle calculation

| Setting | Default | Description |
|---|---|---|
| `BASELINE_WINDOW_S` | `5.0` | The baseline is the median of the last X s before gas ON. |
| `END_WINDOW_S` | `5.0` | The end of the exposure is the median of the last X s before gas OFF. |
| `RESPONSE_LEVEL` | `0.90` | Fraction of the peak for the response time (0.90 gives t90) |
| `SMOOTH_POINTS` | `5` | Length (points) of the moving-median filter. The script uses the filter only for the peak and t90. |
| `INITIAL_SLOPE_WINDOW_S` | `10.0` | Time (s) for the initial slope |
| `FINAL_SLOPE_WINDOW_S` | `20.0` | Time (s) for the final slope |

### 9.5 Crystal settings (Sauerbrey equation)

| Setting | Default | Description |
|---|---|---|
| `QUARTZ_DENSITY` | `2.648` | Density of quartz, g/cm³ |
| `QUARTZ_SHEAR_MODULUS` | `2.947e11` | Shear modulus of quartz, g/(cm·s²) |

### 9.6 Output settings

| Setting | Default | Description |
|---|---|---|
| `SAVE_EXCEL` | `True` | `True` writes `.xlsx` files. You must install openpyxl first. |
| `MAKE_LATEX_TABLE` | `True` | `True` writes `ALL_table.tex` |
| `OPEN_RESULTS_FOLDER_AT_END` | `True` | `True` opens the results folder at the end |
| `PLOT_DPI` | `200` | Resolution of the PNG plots |

## 10. Method

### 10.1 Input file

The script reads all lines that contain only numbers. It ignores other lines.

If the file has two columns, the script uses column 1 as time and column 2 as frequency.

If the file has more columns, the script uses the SQM-160 layout. Columns 1 to 3 are time, mean thickness, and mean rate. Then each channel has three columns: thickness, rate, and frequency.

The script removes the rows with a frequency of 1 kHz or less. A failed crystal gives these rows.

### 10.2 Automatic marks

The script calculates the noise from the second differences of the signal. A slow increase or decrease of the signal does not change this noise value.

A sudden change is a step between two points that is larger than the threshold. The threshold is the larger of `MIN_JUMP_HZ` and `SENSITIVITY` × noise. The script also finds fast changes across 2 or 3 points.

The script combines changes that are near each other into one mark. Then it compares the median signal 5 s before and 5 s after the mark. This difference gives the direction of the change.

Gas ON can start some seconds before the large step. Thus, the script moves each gas ON mark back by a maximum of 10 s. The new position is the point where the signal starts to move away from the baseline.

If the first mark is gas OFF, the file starts during an exposure. In this condition, the script adds a gas ON mark at the first point of the file.

### 10.3 Cycle calculation

The script makes one cycle from each gas ON mark that has a gas OFF mark immediately after it. It ignores a gas ON mark that has no gas OFF mark.

The purge of a cycle stops at the next mark. For the last cycle, the purge length is the median purge length of the other cycles.

### 10.4 Sauerbrey equation

The script calculates the adsorbed mass with this equation:

```
Δm = Δf / Cf
Cf = 2 · f0² / sqrt(ρq · μq)
```

- `ρq` is the density of quartz (`QUARTZ_DENSITY`).
- `μq` is the shear modulus of quartz (`QUARTZ_SHEAR_MODULUS`).
- `f0` is the first frequency in the file.

The unit of `Δm` is ng/cm².
