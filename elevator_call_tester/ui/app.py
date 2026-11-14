"""Tkinter front end. Renders the call form from the selected driver's parameters."""

from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .. import __version__, logsetup, paths, settings
from ..drivers import DRIVERS, CallRequest, ConnectionConfig, DriverError, ElevatorDriver
from ..i18n import LANGUAGES, Translator, detect_language
from ..links import LinkError
from ..modbus import Framing
from .worker import IoWorker

log = logging.getLogger("elevator_call_tester.ui")

AUTHOR_URL = "https://www.linkedin.com/in/sp-raphael/"
POLL_MS = 50
MAX_LOG_LINES = 5000
COLOR_OK = "#1e8449"
COLOR_ERROR = "#c0392b"
COLOR_BUSY = "#b9770e"


def list_serial_ports() -> list[str]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return sorted(port.device for port in list_ports.comports())


def parse_floor(text: str, name: str) -> int:
    text = text.strip()
    try:
        return int(text)
    except ValueError:
        raise DriverError(f"{name} must be an integer, got {text!r}") from None


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.saved = settings.load()
        self.records, self.log_file = logsetup.setup()
        self.formatter = logsetup.screen_formatter()
        self.worker = IoWorker()
        self.log_lines: list[tuple[str, str]] = []  # (text, level tag)

        self.t = Translator(self.saved.get("language") or detect_language())
        self.driver_id = self.saved.get("driver") if self.saved.get("driver") in DRIVERS else next(iter(DRIVERS))
        self.driver: ElevatorDriver = DRIVERS[self.driver_id]()

        self.connected = False
        self.busy = False
        self._make_vars()

        root.minsize(980, 640)
        root.geometry("1200x720")
        self._set_icon()
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(POLL_MS, self._poll)

    # ------------------------------------------------------------- state

    def _make_vars(self) -> None:
        s, d = self.saved, self.driver
        self.language = tk.StringVar(value=LANGUAGES[self.t.language])
        self.transport = tk.StringVar(value=s.get("transport", d.transports[0]))
        if self.transport.get() not in d.transports:
            self.transport.set(d.transports[0])
        self.serial_port = tk.StringVar(value=s.get("serial_port", ""))
        self.host = tk.StringVar(value=s.get("host", ""))
        self.tcp_port = tk.StringVar(value=s.get("tcp_port", str(d.default_tcp_port)))
        framing = s.get("framing", Framing.AUTO.value)
        self.framing = Framing(framing) if framing in {f.value for f in d.tcp_framings} else Framing.AUTO
        self.framing_label = tk.StringVar()
        self.origin = tk.StringVar(value=s.get("origin", "0"))
        self.destination = tk.StringVar(value=s.get("destination", "1"))
        self.params: dict[str, tk.StringVar] = {}
        self.choice_labels: dict[str, tk.StringVar] = {}
        for p in d.parameters:
            self.params[p.key] = tk.StringVar(value=s.get(f"{d.id}.{p.key}", p.default))
            if p.choices:
                self.choice_labels[p.key] = tk.StringVar()

    def _snapshot(self) -> dict[str, str]:
        values = {
            "language": self.t.language,
            "driver": self.driver.id,
            "transport": self.transport.get(),
            "serial_port": self.serial_port.get(),
            "host": self.host.get(),
            "tcp_port": self.tcp_port.get(),
            "framing": self.framing.value,
            "origin": self.origin.get(),
            "destination": self.destination.get(),
        }
        for key, var in self.params.items():
            values[f"{self.driver.id}.{key}"] = var.get()
        return values

    # ---------------------------------------------------------- building

    def _set_icon(self) -> None:
        try:
            self.icon = tk.PhotoImage(file=str(paths.asset("icon.png")))
            self.root.iconphoto(True, self.icon)
        except tk.TclError:
            pass

    def _build(self) -> None:
        """(Re)build every widget. Called again when the language changes; values live in the vars."""
        t = self.t
        if hasattr(self, "outer"):
            self.outer.destroy()
        self.root.title(f"{t('app.title')} {__version__}")

        self.outer = outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, columnspan=2, sticky="we", pady=(0, 10))
        ttk.Label(header, text=t("app.title"), font=("Segoe UI", 15, "bold")).pack(side="left")
        lang = ttk.Combobox(
            header, textvariable=self.language, state="readonly", width=20, values=list(LANGUAGES.values())
        )
        lang.pack(side="right")
        lang.bind("<<ComboboxSelected>>", self.on_language)
        ttk.Label(header, text=t("language")).pack(side="right", padx=(0, 6))

        left = ttk.Frame(outer)
        left.grid(row=1, column=0, sticky="nsw", padx=(0, 14))
        self._build_connection(left)
        self._build_call(left)
        self._build_log(outer)
        self._build_footer(outer)
        self._refresh_state()
        self._render_log()

    def _help_button(self, parent, key: str | None, title: str) -> None:
        if key:
            ttk.Button(
                parent, text="?", width=2, command=lambda: messagebox.showinfo(title, self.t(key), parent=self.root)
            ).pack(side="left", padx=(6, 0))

    def _build_connection(self, parent) -> None:
        t, d = self.t, self.driver
        box = ttk.LabelFrame(parent, text=t("conn.box"), padding=10)
        box.pack(fill="x", pady=(0, 12))

        ttk.Label(box, text=t("driver")).grid(row=0, column=0, sticky="w")
        names = {cls.name: key for key, cls in DRIVERS.items()}
        self.driver_name = tk.StringVar(value=d.name)
        drv = ttk.Combobox(box, textvariable=self.driver_name, state="readonly", width=40, values=list(names))
        drv.grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))
        drv.bind("<<ComboboxSelected>>", lambda e: self.on_driver(names[self.driver_name.get()]))
        self.driver_combo = drv

        ttk.Label(box, text=t("conn.type")).grid(row=2, column=0, sticky="w")
        labels = {"serial": t("conn.serial"), "tcp": t("conn.tcp")}
        self.transport_labels = {labels[k]: k for k in d.transports}
        self.transport_label = tk.StringVar(value=labels[self.transport.get()])
        combo = ttk.Combobox(
            box, textvariable=self.transport_label, state="readonly", width=40, values=list(self.transport_labels)
        )
        combo.grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 8))
        combo.bind("<<ComboboxSelected>>", self.on_transport)
        self.transport_combo = combo

        # Serial and TCP rows share one grid cell; only one is visible.
        self.editable_widgets: list[ttk.Widget] = []  # (disabled while connected or busy)
        self.serial_row = row = ttk.Frame(box)
        row.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(row, text=t("conn.port")).grid(row=0, column=0, sticky="w")
        # Editable: lets a technician type a port the driver did not list (/dev/ttyUSB0, COM12).
        self.port_combo = ttk.Combobox(row, textvariable=self.serial_port, width=18, values=list_serial_ports())
        self.port_combo.grid(row=1, column=0, sticky="w")
        refresh = ttk.Button(row, text=t("conn.refresh"), command=self.on_refresh_ports)
        refresh.grid(row=1, column=1, padx=(8, 0))
        self.editable_widgets += [self.port_combo, refresh]
        if d.serial_settings:
            ttk.Label(row, text=t("conn.serial_settings", settings=d.serial_settings), foreground="#555").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
            )

        self.tcp_row = row = ttk.Frame(box)
        row.grid(row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(row, text=t("conn.host")).grid(row=0, column=0, sticky="w")
        host = ttk.Entry(row, textvariable=self.host, width=20)
        host.grid(row=1, column=0, sticky="w")
        ttk.Label(row, text=t("conn.tcp_port")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        tcp_port = ttk.Entry(row, textvariable=self.tcp_port, width=8)
        tcp_port.grid(row=1, column=1, sticky="w", padx=(10, 0))
        self.editable_widgets += [host, tcp_port]
        if d.tcp_framings:
            ttk.Label(row, text=t("conn.framing")).grid(row=2, column=0, sticky="w", pady=(8, 0))
            self.framing_names = {t(f"framing.{f.value}"): f for f in d.tcp_framings}
            self.framing_label.set(t(f"framing.{self.framing.value}"))
            fr = ttk.Combobox(
                row, textvariable=self.framing_label, state="readonly", width=30, values=list(self.framing_names)
            )
            fr.grid(row=3, column=0, columnspan=2, sticky="w")
            fr.bind("<<ComboboxSelected>>", self.on_framing)
            self.editable_widgets.append(fr)
        self._show_transport_row()

        bar = ttk.Frame(box)
        bar.grid(row=5, column=0, columnspan=2, sticky="we", pady=(12, 0))
        self.connect_button = ttk.Button(bar, command=self.on_connect_toggle, width=14)
        self.connect_button.pack(side="left")
        self.status = ttk.Label(bar, font=("Segoe UI", 10, "bold"))
        self.status.pack(side="left", padx=(12, 0))

    def _build_call(self, parent) -> None:
        t, d = self.t, self.driver
        box = ttk.LabelFrame(parent, text=t("call.box"), padding=10)
        box.pack(fill="x")

        fields = [
            ("origin", "call.origin", None, self.origin, ()),
            ("destination", "call.destination", None, self.destination, ()),
        ]
        fields += [(p.key, p.label, p.help, self.params[p.key], p.choices) for p in d.parameters]
        for index, (key, label, help_key, var, choices) in enumerate(fields):
            cell = ttk.Frame(box)
            cell.grid(row=index // 2, column=index % 2, sticky="nw", padx=(0, 16), pady=(0, 8))
            top = ttk.Frame(cell)
            top.pack(anchor="w")
            ttk.Label(top, text=t(label)).pack(side="left")
            self._help_button(top, help_key, t(label))
            if choices:
                by_label = {t(lbl): value for value, lbl in choices}
                by_value = {value: t(lbl) for value, lbl in choices}
                label_var = self.choice_labels[key]
                label_var.set(by_value.get(var.get(), next(iter(by_label))))
                var.set(by_label[label_var.get()])
                c = ttk.Combobox(cell, textvariable=label_var, state="readonly", width=24, values=list(by_label))
                c.pack(anchor="w")
                c.bind("<<ComboboxSelected>>", lambda e, v=var, lv=label_var, m=by_label: v.set(m[lv.get()]))
            else:
                ttk.Entry(cell, textvariable=var, width=26).pack(anchor="w")

        self.call_button = ttk.Button(box, text=t("call.send"), command=self.on_call)
        self.call_button.grid(row=(len(fields) + 1) // 2, column=0, columnspan=2, sticky="we", pady=(10, 0))
        self.root.bind("<Return>", lambda e: self.on_call() if str(self.call_button["state"]) == "normal" else None)

    def _build_log(self, parent) -> None:
        t = self.t
        box = ttk.LabelFrame(parent, text=t("log.box"), padding=8)
        box.grid(row=1, column=1, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        self.log_text = tk.Text(
            box, wrap="word", state="disabled", font=("Consolas", 9), background="#fbfbfb", relief="flat"
        )
        self.log_text.grid(row=0, column=0, sticky="nsew")
        self.log_text.tag_configure("WARNING", foreground=COLOR_BUSY)
        self.log_text.tag_configure("ERROR", foreground=COLOR_ERROR)
        bar = ttk.Scrollbar(box, orient="vertical", command=self.log_text.yview)
        bar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=bar.set)

        buttons = ttk.Frame(box)
        buttons.grid(row=1, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(buttons, text=t("log.clear"), command=self.on_clear_log).pack(side="left")
        ttk.Button(buttons, text=t("log.open_folder"), command=self.on_open_log_folder).pack(side="left", padx=(8, 0))

    def _build_footer(self, parent) -> None:
        t = self.t
        footer = ttk.Frame(parent)
        footer.grid(row=2, column=0, columnspan=2, sticky="e", pady=(10, 0))
        link = ttk.Label(
            footer, text=t("footer.author"), foreground="#1a6fb5", cursor="hand2", font=("Segoe UI", 9, "underline")
        )
        link.pack(side="left")
        link.bind("<Button-1>", lambda e: webbrowser.open(AUTHOR_URL))
        ttk.Button(
            footer,
            text=t("about"),
            command=lambda: messagebox.showinfo(t("about"), t("about.text", version=__version__), parent=self.root),
        ).pack(side="left", padx=(10, 0))

    # ------------------------------------------------------------- state

    def _show_transport_row(self) -> None:
        if self.transport.get() == "tcp":
            self.serial_row.grid_remove()
            self.tcp_row.grid()
        else:
            self.tcp_row.grid_remove()
            self.serial_row.grid()

    def _refresh_state(self) -> None:
        t = self.t
        if self.busy:
            self.status.configure(text=t("conn.busy"), foreground=COLOR_BUSY)
        elif self.connected:
            self.status.configure(text=t("conn.connected"), foreground=COLOR_OK)
        else:
            self.status.configure(text=t("conn.disconnected"), foreground=COLOR_ERROR)
        self.connect_button.configure(
            text=t("conn.disconnect") if self.connected else t("conn.connect"),
            state="disabled" if self.busy else "normal",
        )
        self.call_button.configure(state="normal" if self.connected and not self.busy else "disabled")
        lock = "disabled" if self.busy or self.connected else "readonly"
        self.transport_combo.configure(state=lock)
        self.driver_combo.configure(state=lock)
        for widget in self.editable_widgets:
            if widget.winfo_exists():
                widget.state(["disabled"] if self.busy or self.connected else ["!disabled"])

    def _run(self, task, done) -> None:
        self.busy = True
        self._refresh_state()

        def finished(result, error):
            self.busy = False
            try:
                done(result, error)
            finally:
                self._refresh_state()

        self.worker.submit(task, finished)

    # ----------------------------------------------------------- events

    def on_language(self, _event=None) -> None:
        code = next(k for k, v in LANGUAGES.items() if v == self.language.get())
        if code != self.t.language:
            self.t = Translator(code)
            self._build()

    def on_driver(self, driver_id: str) -> None:
        if driver_id == self.driver.id:
            return
        self.saved.update(self._snapshot())
        self.worker.submit(self.driver.close)
        self.driver = DRIVERS[driver_id]()
        self._make_vars()
        self._build()

    def on_transport(self, _event=None) -> None:
        self.transport.set(self.transport_labels[self.transport_label.get()])
        self._show_transport_row()

    def on_framing(self, _event=None) -> None:
        self.framing = self.framing_names[self.framing_label.get()]

    def on_refresh_ports(self) -> None:
        ports = list_serial_ports()
        self.port_combo.configure(values=ports)
        if not self.serial_port.get() and ports:
            self.serial_port.set(ports[0])

    def on_connect_toggle(self) -> None:
        if self.connected:
            self._run(self.driver.close, self._disconnected)
            return
        try:
            tcp_port = int(self.tcp_port.get().strip() or 0) if self.transport.get() == "tcp" else 0
        except ValueError:
            self._error(f"TCP port must be an integer, got {self.tcp_port.get()!r}")
            return
        # Read every Tk variable here, on the Tk thread; the worker gets plain values.
        config = ConnectionConfig(
            kind=self.transport.get(),
            serial_port=self.serial_port.get().strip(),
            host=self.host.get().strip(),
            port=tcp_port,
            framing=self.framing,
        )
        settings.save(self._snapshot())
        self._run(lambda: self.driver.connect(config), self._connected)

    def _connected(self, _result, error) -> None:
        if error is None:
            self.connected = True
            return
        self.connected = False
        if isinstance(error, (DriverError, LinkError)):
            log.error("Connection failed: %s", error)
        else:
            log.error("Connection failed", exc_info=error)

    def _disconnected(self, _result, error) -> None:
        self.connected = False
        if error is not None:
            log.warning("Disconnect: %s", error)

    def on_call(self) -> None:
        try:
            request = CallRequest(
                origin_floor=parse_floor(self.origin.get(), "Origin floor"),
                destination_floor=parse_floor(self.destination.get(), "Destination floor"),
                params={key: var.get() for key, var in self.params.items()},
            )
        except DriverError as ex:
            self._error(str(ex))
            return
        settings.save(self._snapshot())
        self._run(lambda: self.driver.call(request), self._call_done)

    def _call_done(self, result, error) -> None:
        if isinstance(error, DriverError):
            self._error(str(error))
        elif error is not None:
            log.error("Unexpected error during the call", exc_info=error)
        self.connected = self.driver.is_connected
        if result is not None and not result.accepted:
            log.error("%s: %s", self.t("call.failed"), result.summary)

    def _error(self, text: str) -> None:
        log.error(text)
        messagebox.showerror(self.t("error"), text, parent=self.root)

    def on_clear_log(self) -> None:
        self.log_lines.clear()
        self._render_log()

    def on_open_log_folder(self) -> None:
        folder = self.log_file.parent if self.log_file else None
        if folder is None:
            messagebox.showinfo(self.t("log.box"), self.t("log.no_file"), parent=self.root)
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # noqa: S606 - opens Explorer on our own folder
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as ex:
            self._error(f"Cannot open {folder}: {ex}")

    def on_close(self) -> None:
        settings.save(self._snapshot())
        self.worker.submit(self.driver.close)
        # Waits for a call in progress to finish (bounded). Log handlers are
        # flushed by logging's own atexit hook, after the worker is done.
        self.worker.shutdown(timeout=3.0)
        self.root.destroy()

    # -------------------------------------------------------------- log

    def _poll(self) -> None:
        try:
            self._drain()
        finally:
            self.root.after(POLL_MS, self._poll)

    def _drain(self) -> None:
        self.worker.poll()
        appended = []
        while True:
            try:
                record = self.records.get_nowait()
            except queue.Empty:
                break
            appended.append((self.formatter.format(record), record.levelname))
        if appended:
            self.log_lines.extend(appended)
            overflow = len(self.log_lines) - MAX_LOG_LINES
            if overflow > 0:
                del self.log_lines[:overflow]
                self._render_log()
            else:
                self._append_log(appended)

    def _append_log(self, lines) -> None:
        widget = self.log_text
        widget.configure(state="normal")
        for text, level in lines:
            widget.insert("end", text + "\n", level)
        widget.see("end")
        widget.configure(state="disabled")

    def _render_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._append_log(self.log_lines)


def main() -> None:
    root = tk.Tk()
    style = ttk.Style()
    for theme in ("vista", "clam"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break
    App(root)
    root.mainloop()
