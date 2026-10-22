#!/bin/bash
# cment setup (macOS/Linux): creates .venv and installs the Python packages. Safe to run again.
cd "$(dirname "$0")" || exit 1

PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is needed (macOS ships an older one)."
  echo "Install it from https://www.python.org/downloads/macos/  or with Homebrew: brew install python"
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating the Python environment with $PY..."
  "$PY" -m venv .venv || exit 1
fi
echo "Installing packages (needs internet the first time)..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt || exit 1
[ -f config.toml ] || cp config.example.toml config.toml
echo
echo "Setup complete."
echo "  Demo with the simulator:   ./demo.command"
echo "  Real PLC: edit config.toml (PLC IP address), add a user, then ./run.command"
echo "    .venv/bin/python -m scada adduser NAME --role operator"
