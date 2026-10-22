#!/bin/bash
# cment demo (macOS/Linux): starts the simulated PLC and the SCADA, then opens the browser. Ctrl+C stops both.
cd "$(dirname "$0")" || exit 1
[ -x .venv/bin/python ] || ./setup.command || exit 1

.venv/bin/python -m scada --config config.demo.toml adduser demo --role operator --password demo123 >/dev/null
.venv/bin/python -m sim --port 1102 --auto 30 --faults &
SIM=$!
trap 'kill $SIM 2>/dev/null' EXIT INT TERM
sleep 2
(sleep 2; open http://localhost:8080 2>/dev/null || xdg-open http://localhost:8080 2>/dev/null) &
echo
echo "cment demo: http://localhost:8080   (log in as demo / demo123 for batch control)"
echo "Press Ctrl+C to stop."
echo
.venv/bin/python -m scada --config config.demo.toml
