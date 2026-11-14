"""Last-used form values, so a technician does not retype them on every visit."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)


def load(path: Path | None = None) -> dict[str, str]:
    path = path or paths.settings_file()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as ex:
        log.warning("Ignoring unreadable settings file %s: %s", path, ex)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, (str, int, float))}


def save(values: dict[str, str], path: Path | None = None) -> None:
    path = path or paths.settings_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    except OSError as ex:
        log.warning("Could not save settings to %s: %s", path, ex)
