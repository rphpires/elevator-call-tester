"""Entry point: ``python -m elevator_call_tester`` (and the PyInstaller executable)."""

import os
import sys

# A windowed PyInstaller build has no console: sys.stdout/stderr are None and
# any print() or logging to them would raise. Point them at devnull first.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")  # noqa: SIM115
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def main() -> None:
    from elevator_call_tester.ui.app import main as run

    run()


if __name__ == "__main__":
    main()
