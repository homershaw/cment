# cment: batch plant SCADA (demo)

Python (FastAPI + python-snap7 + SQLite) SCADA for a concrete batch plant on a Siemens S7-1500.
The screens are plain HTML/JS in `web/`, with no external libraries because the plant network may be offline.
Public demo repo: keep customer and site names out of everything committed.

- Source documents (local only, not in the repo): `C:\Users\scada\Documents\Cement\cment.pdf`, the TIA program
  listing that every tag address in `scada/tags.py` comes from, and `PanelDrawings.pdf`, the wiring.
- Tests: `.venv\Scripts\python -m pytest`. They start the simulator in-process on a free port.
- Demo: `demo.bat` / `demo.command` runs the simulator on port 1102 with `config.demo.toml` and `data/demo.db`.
  Real use: `run.bat` / `run.command` with `config.toml` and `data/scada.db`.
- Only the tags in `tags.WRITABLE` may ever be written to the PLC. Batch control is off by default
  (`[control] enabled`) and must stay off on the real plant until commissioned.
- python-snap7 3.x is pure Python (no native library), so the same code runs on Windows and macOS. Its
  server writes a bit request as a whole byte; `sim/server.py` fixes that for the simulator only.
- Batches are tracked by `DB30.DBW14` process stage (0 = idle), not by the PLC's one-scan complete pulse.
