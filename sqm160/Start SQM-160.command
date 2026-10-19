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
    exec python3 "$HERE/bootstrap.py" "$@"
fi

osascript -e 'display dialog "Python 3 is not installed on this Mac.

Install it from python.org (the free download), then double-click setup.command in this folder." buttons {"OK"} with icon stop' >/dev/null 2>&1
exit 1
