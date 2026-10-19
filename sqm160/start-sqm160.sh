#!/bin/bash
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"
REPO="$(dirname "$HERE")"

for CANDIDATE in "$REPO/.venv/bin/python" "$HOME/.sqm160/venv/bin/python"; do
    if [ -x "$CANDIDATE" ]; then
        exec "$CANDIDATE" "$HERE/sqm160_cli.py" "${@:-gui}"
    fi
done

if command -v python3 >/dev/null 2>&1; then
    exec python3 bootstrap.py "$@"
fi

echo "Python 3 is not installed. Install it with your package manager, for example:"
echo "    sudo apt install python3 python3-venv python3-tk"
exit 1
