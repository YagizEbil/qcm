#!/bin/bash
set -u
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
REPO="$(dirname "$HERE")"
VENV="$REPO/.venv"

echo
echo "  SQM-160 Monitor - setup"
echo "  ======================="
echo "  Repository:  $REPO"
echo "  Environment: $VENV"
echo

PY=""
for CANDIDATE in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$CANDIDATE" >/dev/null 2>&1; then
        if "$CANDIDATE" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
            PY="$(command -v "$CANDIDATE")"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "  Python 3.9 or newer is not installed on this Mac."
    echo
    echo "  Install it from https://www.python.org/downloads/ (the free download),"
    echo "  then double-click this file again."
    echo
    read -r -p "  Press Return to close this window. " _
    exit 1
fi
echo "  Using $PY ($("$PY" -c 'import platform;print(platform.python_version())'))"

if [ ! -x "$VENV/bin/python" ]; then
    echo "  Creating the environment (this happens once)..."
    if ! "$PY" -m venv "$VENV"; then
        echo "  The environment could not be created."
        read -r -p "  Press Return to close this window. " _
        exit 1
    fi
else
    echo "  The environment already exists; updating it."
fi

VPY="$VENV/bin/python"
"$VPY" -m pip install --upgrade pip --quiet

echo "  Installing the packages (a few minutes the first time)..."
if ! "$VPY" -m pip install --quiet -r "$HERE/requirements.txt"; then
    echo
    echo "  The packages could not be installed. The usual cause is no internet"
    echo "  connection. Try again when the Mac is online."
    read -r -p "  Press Return to close this window. " _
    exit 1
fi

if [ "${1:-}" != "--sqm160-only" ]; then
    echo "  Adding the packages used by qcm_cycle_analyzer.py..."
    "$VPY" -m pip install --quiet numpy openpyxl || \
        echo "  (Those are optional here; the SQM-160 program does not need them.)"
fi

echo "  Checking..."
if "$VPY" -m pytest "$HERE/test_sqm160.py" -q 2>/dev/null | tail -1; then
    :
else
    "$VPY" -m pip install --quiet pytest >/dev/null 2>&1
    "$VPY" -m pytest "$HERE/test_sqm160.py" -q 2>/dev/null | tail -1
fi

echo
echo "  Done."
echo
echo "  To open the window:        double-click \"Start SQM-160.command\""
echo "  To try it without the"
echo "  instrument:                \"$VPY\" \"$HERE/sqm160_cli.py\" --demo gui"
echo
read -r -p "  Press Return to close this window. " _
