"""Drive the real Tk UI against the bundled simulator: connect, place calls, check the log.

    python scripts/ui_smoke.py [--mode transparent] [--lang en] [--screenshot docs/images/main.png]

Exits non-zero if the call is not accepted. The screenshot needs Pillow and a
visible desktop session.
"""

from __future__ import annotations

import argparse
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from elevator_call_tester import settings  # noqa: E402
from elevator_call_tester.i18n import LANGUAGES  # noqa: E402
from elevator_call_tester.simulator import Simulator  # noqa: E402
from elevator_call_tester.ui import app as ui  # noqa: E402


def pump(root: tk.Tk, until, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.02)
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("gateway", "transparent"), default="transparent")
    parser.add_argument("--lang", choices=tuple(LANGUAGES), default="en")
    parser.add_argument("--screenshot")
    args = parser.parse_args()

    settings.save = lambda values, path=None: None  # keep the user's saved form untouched
    settings.load = lambda path=None: {"language": args.lang}

    with Simulator(args.mode, port=0) as sim:
        root = tk.Tk()
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        app = ui.App(root)
        host, port = sim.address
        app.transport.set("tcp")
        app._build()
        app.host.set(host)
        app.tcp_port.set(str(port))
        app.params["device"].set("12")
        app.params["floor_offset"].set("-1")
        app.params["mco_map"].set("1:0-20;2:21-40")
        app.origin.set("0")
        app.destination.set("27")

        app.on_connect_toggle()
        if not pump(root, lambda: app.connected and not app.busy):
            print("FAIL: did not connect")
            return 1
        app.on_call()
        pump(root, lambda: not app.busy and len(sim.calls) >= 1)
        pump(root, lambda: False, 0.3)

        text = app.log_text.get("1.0", "end")
        print(text)
        ok = "Call accepted" in text and sim.calls == [(0, [1, 12, 28, 2, 0, 0, 1, 0])]
        if args.screenshot:
            from PIL import ImageGrab

            root.lift()
            root.attributes("-topmost", True)
            pump(root, lambda: False, 0.5)
            x, y = root.winfo_rootx(), root.winfo_rooty()
            w, h = root.winfo_width(), root.winfo_height()
            Path(args.screenshot).parent.mkdir(parents=True, exist_ok=True)
            ImageGrab.grab((x, y, x + w, y + h)).save(args.screenshot)
            print("screenshot:", args.screenshot)
        app.on_close()
    print("PASS" if ok else f"FAIL: calls={sim.calls}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
