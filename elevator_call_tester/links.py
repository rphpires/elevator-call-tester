"""Byte links: a serial port or a TCP socket, behind one small interface.

A link only moves bytes. Framing (RTU, MBAP) lives in :mod:`.modbus`, and the
manufacturer protocol lives in :mod:`.drivers`.
"""

from __future__ import annotations

import logging
import socket
import time
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

# A line that never goes quiet (noise, a chatty bus) must not hang a discard.
MAX_DISCARD_SECONDS = 1.0


class LinkError(Exception):
    """The link could not be opened, or broke during an exchange."""


class Link(Protocol):
    description: str

    @property
    def is_open(self) -> bool: ...

    def open(self) -> None: ...

    def ensure_open(self) -> None: ...

    def close(self) -> None: ...

    def write(self, data: bytes) -> None: ...

    def read(self, size: int, timeout: float) -> bytes:
        """Read up to ``size`` bytes, waiting at most ``timeout`` seconds in total.

        Returns fewer bytes (possibly none) on timeout.
        """
        ...

    def discard_input(self, wait: float = 0.0) -> None:
        """Drop pending input; with ``wait`` > 0, keep dropping until the line is quiet that long."""
        ...


@dataclass(frozen=True)
class SerialSettings:
    baudrate: int = 19200
    bytesize: int = 8
    parity: str = "E"  # N, E, O
    stopbits: int = 1

    def __str__(self) -> str:
        return f"{self.baudrate} {self.bytesize}{self.parity}{self.stopbits}"


class SerialLink:
    def __init__(self, port: str, settings: SerialSettings, write_timeout: float = 1.0):
        self.port = port
        self.settings = settings
        self.write_timeout = write_timeout
        self.description = f"{port} ({settings})"
        self._serial = None

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def open(self) -> None:
        import serial  # imported lazily so the protocol layers do not need pyserial

        self.close()
        try:
            self._serial = serial.Serial(
                port=self.port,
                baudrate=self.settings.baudrate,
                bytesize=self.settings.bytesize,
                parity=self.settings.parity,
                stopbits=self.settings.stopbits,
                timeout=0.2,
                write_timeout=self.write_timeout,
            )
        except (OSError, ValueError, serial.SerialException) as ex:
            self._serial = None
            raise LinkError(f"cannot open serial port {self.port}: {ex}") from ex

    def ensure_open(self) -> None:
        if not self.is_open:
            log.info("Reopening serial port %s", self.port)
            self.open()

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:  # noqa: BLE001 - closing must never raise
                pass
            self._serial = None

    def _fail(self, action: str, ex: Exception) -> LinkError:
        # A USB adapter pulled out of the port shows up here. Close so the next
        # exchange reopens instead of reusing a dead handle.
        self.close()
        return LinkError(f"serial {action} failed on {self.port}: {ex}")

    def write(self, data: bytes) -> None:
        try:
            written = self._serial.write(data)
            self._serial.flush()
        except Exception as ex:  # noqa: BLE001 - pyserial raises several unrelated types
            raise self._fail("write", ex) from ex
        if written != len(data):
            raise LinkError(f"serial write sent {written}/{len(data)} bytes")

    def read(self, size: int, timeout: float) -> bytes:
        try:
            self._serial.timeout = timeout
            return bytes(self._serial.read(size))
        except Exception as ex:  # noqa: BLE001
            raise self._fail("read", ex) from ex

    def discard_input(self, wait: float = 0.0) -> None:
        try:
            self._serial.reset_input_buffer()
            if wait > 0:
                self._serial.timeout = wait
                deadline = time.monotonic() + MAX_DISCARD_SECONDS
                while self._serial.read(256) and time.monotonic() < deadline:
                    pass
        except Exception as ex:  # noqa: BLE001
            raise self._fail("flush", ex) from ex


class TcpLink:
    """One TCP connection. Serial converters often accept a single client, so
    every framing attempt shares this socket instead of opening another."""

    def __init__(self, host: str, port: int, connect_timeout: float = 3.0):
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.description = f"{host}:{port}"
        self._sock: socket.socket | None = None

    @property
    def is_open(self) -> bool:
        return self._sock is not None

    def open(self) -> None:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.connect_timeout)
        except OSError as ex:
            raise LinkError(f"cannot connect to {self.host}:{self.port}: {ex}") from ex
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def ensure_open(self) -> None:
        if not self.is_open:
            log.info("Reconnecting to %s:%s", self.host, self.port)
            self.open()

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _peer_closed(self) -> LinkError:
        self.close()
        return LinkError(f"connection closed by {self.host}:{self.port}")

    def write(self, data: bytes) -> None:
        try:
            self._sock.settimeout(self.connect_timeout)
            self._sock.sendall(data)
        except OSError as ex:
            self.close()
            raise LinkError(f"send to {self.host}:{self.port} failed: {ex}") from ex

    def read(self, size: int, timeout: float) -> bytes:
        buf = bytearray()
        deadline = time.monotonic() + timeout
        while len(buf) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                self._sock.settimeout(remaining)
                chunk = self._sock.recv(size - len(buf))
            except TimeoutError:
                break
            except OSError as ex:
                self.close()
                raise LinkError(f"receive from {self.host}:{self.port} failed: {ex}") from ex
            if not chunk:
                raise self._peer_closed()
            buf += chunk
        return bytes(buf)

    def discard_input(self, wait: float = 0.0) -> None:
        if self._sock is None:
            return
        try:
            self._sock.settimeout(wait if wait > 0 else 0.0)
            deadline = time.monotonic() + MAX_DISCARD_SECONDS
            while time.monotonic() < deadline:
                chunk = self._sock.recv(4096)
                if not chunk:
                    raise self._peer_closed()
        except (TimeoutError, BlockingIOError):
            pass
        except OSError as ex:
            self.close()
            raise LinkError(f"receive from {self.host}:{self.port} failed: {ex}") from ex
