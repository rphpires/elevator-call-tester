"""A minimal elevator-side simulator for trying the tool without hardware.

Listens on TCP and answers function 0x10 writes the way the two converter
types do:

* ``gateway``: Modbus TCP gateway (MBAP in, MBAP out).
* ``transparent``: a serial-to-TCP converter in raw mode with the controller
  behind it (RTU in, RTU out; anything without a valid CRC is ignored, like on
  a real RS-485 bus).

    python -m elevator_call_tester.simulator --mode transparent --port 5020

It decodes each accepted call with the TK Elevator register layout and logs it.
"""

from __future__ import annotations

import argparse
import logging
import socket
import struct
import threading

from .crc import crc16_modbus
from .modbus import FUNC_WRITE_MULTIPLE_REGISTERS, MBAP_HEADER_LEN, mbap_frame, rtu_frame

log = logging.getLogger("simulator")

REGISTER_NAMES = (
    "origin",
    "device",
    "destination",
    "mco",
    "mode",
    "parameter",
    "counter",
    "message",
)


def _handle_pdu(pdu: bytes, calls: list) -> bytes:
    """Return the reply PDU for a request PDU."""
    if not pdu or pdu[0] != FUNC_WRITE_MULTIPLE_REGISTERS:
        return bytes([(pdu[0] if pdu else 0) | 0x80, 0x01])
    if len(pdu) < 6:
        return bytes([0x90, 0x03])
    address, count, byte_count = struct.unpack(">HHB", pdu[1:6])
    if byte_count != count * 2 or len(pdu) != 6 + byte_count:
        return bytes([0x90, 0x03])
    values = list(struct.unpack(f">{count}H", pdu[6:]))
    calls.append((address, values))
    if address == 0 and count == len(REGISTER_NAMES):
        log.info("call %s", ", ".join(f"{n}={v}" for n, v in zip(REGISTER_NAMES, values, strict=True)))
    else:
        log.info("write %s registers at %s: %s", count, address, values)
    return pdu[:5]


class Simulator:
    def __init__(
        self, mode: str, unit: int = 1, host: str = "127.0.0.1", port: int = 0, exception_code: int | None = None
    ):
        if mode not in ("gateway", "transparent"):
            raise ValueError("mode must be 'gateway' or 'transparent'")
        self.mode = mode
        self.unit = unit
        self.exception_code = exception_code
        self.calls: list[tuple[int, list[int]]] = []
        self._server = socket.create_server((host, port))
        self.address = self._server.getsockname()[:2]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> Simulator:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._server.close()
        self._thread.join(timeout=2)

    def __enter__(self) -> Simulator:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _serve(self) -> None:
        self._server.settimeout(0.1)
        while not self._stop.is_set():
            try:
                conn, peer = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            log.info("client %s:%s connected", *peer[:2])
            with conn:
                self._session(conn)

    def _reply_pdu(self, pdu: bytes) -> bytes:
        if self.exception_code is not None:
            return bytes([pdu[0] | 0x80, self.exception_code])
        return _handle_pdu(pdu, self.calls)

    def _session(self, conn: socket.socket) -> None:
        conn.settimeout(0.1)
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = conn.recv(1024)
            except TimeoutError:
                # Inter-frame silence: whatever is buffered is one frame.
                if buf:
                    self._frame(conn, buf)
                    buf = b""
                continue
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            if self.mode == "gateway":
                buf = self._drain_mbap(conn, buf)

    def _drain_mbap(self, conn: socket.socket, buf: bytes) -> bytes:
        while len(buf) >= MBAP_HEADER_LEN:
            tid, proto, length, unit = struct.unpack(">HHHB", buf[:MBAP_HEADER_LEN])
            if proto != 0 or not 2 <= length <= 254:
                return b""  # not MBAP: a gateway drops the connection's garbage
            if len(buf) < 6 + length:
                return buf
            pdu, buf = buf[MBAP_HEADER_LEN : 6 + length], buf[6 + length :]
            if unit != self.unit:
                conn.sendall(mbap_frame(tid, unit, bytes([pdu[0] | 0x80, 0x0B])))
                continue
            conn.sendall(mbap_frame(tid, unit, self._reply_pdu(pdu)))
        return buf

    def _frame(self, conn: socket.socket, frame: bytes) -> None:
        if self.mode == "gateway":
            return
        if len(frame) < 4 or crc16_modbus(frame[:-2]) != struct.unpack("<H", frame[-2:])[0]:
            log.info("ignored %d bytes without a valid RTU CRC", len(frame))
            return
        if frame[0] != self.unit:
            return  # another slave on the bus
        conn.sendall(rtu_frame(self.unit, self._reply_pdu(frame[1:-2])))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=("gateway", "transparent"), default="gateway")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5020)
    parser.add_argument("--unit", type=int, default=1, help="slave address / unit id (default 1)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    sim = Simulator(args.mode, args.unit, args.host, args.port)
    log.info("%s simulator on %s:%s, unit %s (Ctrl+C to stop)", args.mode, *sim.address, args.unit)
    sim.start()
    try:
        sim._thread.join()
    except KeyboardInterrupt:
        sim.stop()


if __name__ == "__main__":
    main()
