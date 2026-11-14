# Building and testing

## Tests and lint

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

The suite needs no hardware:

- unit tests for CRC, frame building and parsing, the MCO parser, and the register layout,
- `ModbusClient` against a scripted fake link (timeouts, corrupt replies, exceptions,
  retries, detection),
- the TK Elevator driver end to end through a real TCP socket against
  `elevator_call_tester.simulator` in both gateway and transparent modes (detection,
  gateway exceptions, reconnect after the peer restarts),
- the I/O worker, i18n completeness, and settings and log files.

`scripts/ui_smoke.py` opens the real Tk window, connects to the simulator, places a call
and checks the log. It needs a display; with `--screenshot` it also captures the window
(this is how the README images are made).

## Windows executable

Build **on Windows** with a Python that includes Tcl/Tk (the python.org installer does).
Without Tcl/Tk, PyInstaller still finishes but the executable cannot open its window.

```powershell
.\build.ps1
```

Output: `dist\ElevatorCallTester\ElevatorCallTester.exe` (one folder, about 25 MB). Zip the
folder to distribute it. The executable has no console; its logs go to
`%LOCALAPPDATA%\ElevatorCallTester\logs`.

The icon is drawn by `scripts/make_icon.py` (Pillow) and committed under
`elevator_call_tester/assets/`.
