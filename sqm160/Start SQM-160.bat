@echo off
setlocal
set "HERE=%~dp0"
for %%I in ("%HERE%..") do set "REPO=%%~fI"

if exist "%REPO%\.venv\Scripts\pythonw.exe" (
    start "" "%REPO%\.venv\Scripts\pythonw.exe" "%HERE%sqm160_cli.py" gui
    exit /b 0
)
if exist "%USERPROFILE%\.sqm160\venv\Scripts\pythonw.exe" (
    start "" "%USERPROFILE%\.sqm160\venv\Scripts\pythonw.exe" "%HERE%sqm160_cli.py" gui
    exit /b 0
)

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%HERE%bootstrap.py" %*
    goto :done
)
where python >nul 2>&1
if %errorlevel%==0 (
    python "%HERE%bootstrap.py" %*
    goto :done
)

echo.
echo   Python is not installed on this computer.
echo.
echo   This program needs Python, which is a free download.
echo   The download page will open now. On the first page of the
echo   installer, TICK THE BOX that says "Add Python to PATH",
echo   then press Install Now.
echo.
echo   When it has finished, double-click this file again.
echo.
start "" https://www.python.org/downloads/
pause
exit /b 1

:done
if %errorlevel% neq 0 (
    echo.
    echo   Something went wrong. The message above explains what.
    pause
)
exit /b %errorlevel%
