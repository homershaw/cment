#!/bin/bash
# cment (macOS/Linux): run against the real PLC set in config.toml.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || ./setup.command || exit 1
[ -f config.toml ] || cp config.example.toml config.toml
(sleep 3; open http://localhost:8080 2>/dev/null || xdg-open http://localhost:8080 2>/dev/null) &
.venv/bin/python -m scada --config config.toml "$@"
