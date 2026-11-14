"""Per-user folders for logs and saved settings."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "ElevatorCallTester"


def data_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / APP_DIR_NAME
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "elevator-call-tester"


def log_dir() -> Path:
    return data_dir() / "logs"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def asset(name: str) -> Path:
    return Path(__file__).resolve().parent / "assets" / name
