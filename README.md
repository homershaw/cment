# cment: concrete batch plant SCADA (demo)

A browser-based SCADA for a concrete batch plant controlled by a Siemens S7-1500 (CPU 1511-1 PN).
It reads the PLC directly over S7 protocol, so no Modbus map is needed. It runs on **Windows** and
**macOS**. A built-in **PLC simulator** lets you try every screen without a plant.

> **Demo software.** It has not been commissioned on a live plant. Batch control is switched off
> for real PLCs until it has been checked (see [Connecting a real PLC](#connecting-a-real-plc)).

## What it does

- **Overview:** aggregate bins, cement silos, water and admix with live weights and batch progress,
  equipment states, the main conveyor, and the ready, paused and e-stop flags.
- **Batch Control:** start (with quantity), pause, resume and abort, behind an operator login.
  Interlocks are checked against fresh PLC values before anything is written.
- **Alarms:** the PLC's 42 alarm bits plus PLC communication loss, out-of-tolerance pause and
  e-stop during a batch. Acknowledge, and history.
- **Trends:** weights, flows, water and admix from 15 minutes to 7 days, with a table view.
- **Batches:** every batch with required vs batched per material, accuracy and tolerance flags.
  CSV export.
- **Events:** an audit log of logins, control actions (who and what), PLC connect/disconnect,
  and batch start/end.
- **Tags:** every PLC tag with its address and live value, for commissioning.

## Quick start on Windows

1. **Install Python 3.11 or newer** from https://www.python.org/downloads/. In the installer,
   tick **"Add python.exe to PATH"**.
2. **Download cment:** on this GitHub page, choose **Code > Download ZIP**, then unzip it, for
   example to `C:\cment`.
3. **Double-click `demo.bat`.**
   - The first run creates its Python environment and downloads the packages. This needs
     internet once and takes a minute or two.
   - It then starts the simulator and the SCADA, and opens http://localhost:8080.
   - If Windows Firewall asks, allow Python on **private** networks so other PCs can connect.
4. **Log in** as `demo` / `demo123` to try batch control.
5. **Stop:** close both console windows.

## Quick start on macOS

1. **Install Python 3.11 or newer.** The Python that comes with macOS is too old. Use either:
   - the installer from https://www.python.org/downloads/macos/, or
   - Homebrew: `brew install python`.
2. **Download cment:** choose **Code > Download ZIP** and unzip it, for example into your home
   folder.
3. **Open Terminal** in that folder and run:
   ```
   cd ~/cment-main
   bash demo.command
   ```
   The first run sets everything up (needs internet once), then opens http://localhost:8080.
   - Double-clicking `demo.command` in Finder also works. macOS may block a downloaded script the
     first time: right-click it and choose **Open**, or use the Terminal command above.
4. **Log in** as `demo` / `demo123`.
5. **Stop:** press **Ctrl+C** in Terminal.

## Files you start

| Windows | macOS | What it does |
|---|---|---|
| `demo.bat` | `demo.command` | Simulator + SCADA, demo database `data/demo.db`, control enabled |
| `run.bat` | `run.command` | SCADA against the real PLC in `config.toml`, database `data/scada.db` |
| `setup.bat` | `setup.command` | Creates `.venv` and installs packages. The other scripts run it when needed |

The demo and real data are kept apart: separate config files and separate databases.

## Simulator options

The demo starts the simulator with `--auto 30 --faults`:
- `--auto 30`: a new batch starts after 30 s idle.
- `--faults`: about one batch in four ends out of tolerance and pauses, and the air pressure
  dips now and then.

The demo resumes an out-of-tolerance pause by itself after 30 s, so it keeps running unattended.
To run the simulator by hand:
```
.venv\Scripts\python -m sim --port 1102 --auto 0        (Windows)
.venv/bin/python -m sim --port 1102 --auto 0            (macOS)
```
`--auto 0` means batches only start from Batch Control. `--speed 2` runs the plant twice as fast.

## Connecting a real PLC

1. **TIA Portal, on the CPU:**
   - Properties > Protection & Security > Connection mechanisms: tick **Permit access with
     PUT/GET communication from remote partner**.
   - Download the hardware configuration.
2. **Data blocks:** the DBs that are read (9, 10, 12, 14, 15, 16, 17, 18, 20, 30, 31, 63) must have
   **Optimized block access** switched off. Absolute addresses such as `%DB9.DBD14` only exist
   then.
3. **Edit `config.toml`:**
   - set `[plc] host` to the PLC's IP address (rack 0, slot 1, port 102);
   - leave `[control] enabled = false`.
4. **Add a user:**
   ```
   .venv\Scripts\python -m scada adduser NAME --role operator     (Windows)
   .venv/bin/python -m scada adduser NAME --role operator         (macOS)
   ```
   Roles: `viewer`, `operator` (batch control and acknowledge alarms), `admin`.
5. **Start `run.bat`** (or `run.command`) and open the **Tags** page. Compare the values against
   a TIA watch table, especially:
   - **REAL vs DINT:** every `DBD` value is assumed to be REAL, e.g. `DB9.DBD14` Bin 1 weight.
     A DINT shows as a nonsense number.
   - **Process stage** (`DB30.DBW14`): only 0 = idle is known. Name the others in `[stages]`.
   - **Units:** admix is assumed to be litres and batch quantity m³.
6. **Batch control:** enable it only after checking with the PLC programmer how these bits are
   used. They are the only things cment ever writes:

   | Action | Writes |
   |---|---|
   | Start | `DB30.DBD20` batch quantity (read back), then `DB30.DBX16.4` Run_Batch = 1 |
   | Pause | `DB30.DBX16.5` Pause Batch = 1 |
   | Resume | `DB30.DBX10.6` Resume = 1, then `DB30.DBX16.5` Pause Batch = 0 |
   | Abort | `DB30.DBX10.4` Abort Button = 1 |

   Manual controls and outputs are read-only. `WRITABLE` in `scada/tags.py` enforces this.

**Not included yet: recipe and target quantities.** Required quantities are read-only, so the
mix is still set by the plant's existing system.

## Using it from other PCs and tablets

- Browse to `http://<this-pc's-ip>:8080`. Viewing needs no login.
- **Windows:** allow inbound TCP 8080 in Windows Firewall (private network).
- **Start at boot (Windows):** use Task Scheduler with "At startup", running `run.bat`.
- **Backup:** all history is in `data/scada.db`, a single SQLite file. Copy it while cment is
  stopped.

## For developers

```
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest
```

| Path | What |
|---|---|
| `scada/tags.py` | Tag map: every DB/Q/I/M address, taken from the PLC program listing |
| `scada/s7.py` | S7 reads (one block per DB), decoding, single-bit writes, reconnect |
| `scada/engine.py` | Poll loop, alarm and batch tracking, history recording |
| `scada/control.py` | Batch control and its interlocks |
| `scada/app.py` | HTTP API, WebSocket live feed, static screens |
| `scada/store.py` | SQLite: samples, alarms, batches, events, users, sessions |
| `web/` | Screens: plain HTML/JS/CSS, no internet needed |
| `sim/` | Simulated S7-1500 with a plant model, served over real S7 protocol |
| `tests/` | S7 link, batches, control, alarms, API |

## Notes from the PLC program

- **E-stop signal:** the program uses `"Simulator".Estop` (DB63.DBX0.0) as its e-stop signal,
  TRUE = healthy, rather than the input `%I4.7 "Estop OK"`.
- **Simulation networks:** the program has networks that simulate bins, silos, water and admix.
  Confirm that the plant PLC runs the production version.
