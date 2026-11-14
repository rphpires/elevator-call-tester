"""Modbus framing (RTU and TCP/MBAP) and a small client for register writes.

Only what elevator destination-call interfaces need today: function 0x10
(write multiple registers). Frames are built and validated here; the bytes
travel over a :class:`~elevator_call_tester.links.Link`.
"""

from __future__ import annotations

import enum
import logging
import struct
import time
from dataclasses import dataclass

from .crc import crc16_modbus
from .links import Link, LinkError

log = logging.getLogger(__name__)

FUNC_WRITE_MULTIPLE_REGISTERS = 0x10
MAX_WRITE_REGISTERS = 123
MAX_RTU_RESYNC_BYTES = 32
MBAP_HEADER_LEN = 7  # transaction id(2) + protocol id(2) + length(2) + unit id(1)

EXCEPTION_NAMES = {
    0x01: "illegal function",
    0x02: "illegal data address",
    0x03: "illegal data value",
    0x04: "server device failure",
    0x05: "acknowledge",
    0x06: "server device busy",
    0x08: "memory parity error",
    0x0A: "gateway path unavailable",
    0x0B: "gateway target device failed to respond",
}

# Exception codes worth retrying: the request itself was fine.
RETRYABLE_EXCEPTIONS = {0x05, 0x06, 0x0B}


class Framing(str, enum.Enum):
    RTU = "rtu"  # slave + PDU + CRC (serial line, or a transparent TCP converter)
    MBAP = "mbap"  # Modbus TCP header + PDU, no CRC (Modbus TCP gateway)
    AUTO = "auto"  # TCP only: probe MBAP, then RTU, and remember what answered


class ModbusError(Exception):
    """Base class for every failure of a Modbus exchange."""


class ModbusTimeout(ModbusError):
    pass


class FrameError(ModbusError):
    """A reply arrived but it is not a valid answer to the request."""


class StaleReply(FrameError):
    """A well-formed MBAP reply to an earlier request (old transaction id)."""


class ModbusExceptionResponse(ModbusError):
    def __init__(self, function: int, code: int):
        self.function = function
        self.code = code
        name = EXCEPTION_NAMES.get(code, "unknown exception")
        super().__init__(f"Modbus exception 0x{code:02X} ({name}) for function 0x{function:02X}")


def hexdump(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data) or "(empty)"


# --------------------------------------------------------------------- frames


def write_multiple_registers_pdu(address: int, values: list[int]) -> bytes:
    if not 1 <= len(values) <= MAX_WRITE_REGISTERS:
        raise ValueError(f"register count must be 1..{MAX_WRITE_REGISTERS}, got {len(values)}")
    if not 0 <= address <= 0xFFFF:
        raise ValueError(f"register address out of range: {address}")
    for index, value in enumerate(values):
        if not 0 <= value <= 0xFFFF:
            raise ValueError(f"register {address + index} value {value} does not fit in 16 bits")
    header = struct.pack(">BHHB", FUNC_WRITE_MULTIPLE_REGISTERS, address, len(values), len(values) * 2)
    return header + struct.pack(f">{len(values)}H", *values)


def rtu_frame(unit: int, pdu: bytes) -> bytes:
    body = bytes([unit & 0xFF]) + pdu
    return body + struct.pack("<H", crc16_modbus(body))


def mbap_frame(transaction_id: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", transaction_id & 0xFFFF, 0, len(pdu) + 1, unit & 0xFF) + pdu


def check_write_response(pdu: bytes, address: int, count: int) -> None:
    """Validate a function 0x10 reply PDU (function + address + quantity)."""
    if not pdu:
        raise FrameError("empty reply PDU")
    function = pdu[0]
    if function == FUNC_WRITE_MULTIPLE_REGISTERS | 0x80:
        if len(pdu) < 2:
            raise FrameError("truncated exception reply")
        raise ModbusExceptionResponse(FUNC_WRITE_MULTIPLE_REGISTERS, pdu[1])
    if function != FUNC_WRITE_MULTIPLE_REGISTERS:
        raise FrameError(f"reply function 0x{function:02X}, expected 0x{FUNC_WRITE_MULTIPLE_REGISTERS:02X}")
    if len(pdu) != 5:
        raise FrameError(f"reply PDU has {len(pdu)} bytes, expected 5")
    echo_address, echo_count = struct.unpack(">HH", pdu[1:5])
    if (echo_address, echo_count) != (address, count):
        raise FrameError(f"reply echoes address {echo_address} / count {echo_count}, expected {address} / {count}")


def parse_rtu_reply(frame: bytes, unit: int) -> bytes:
    """Check CRC and slave address; return the PDU."""
    if len(frame) < 4:
        raise FrameError(f"RTU reply too short ({len(frame)} bytes)")
    body, received = frame[:-2], struct.unpack("<H", frame[-2:])[0]
    if crc16_modbus(body) != received:
        raise FrameError("RTU reply CRC mismatch")
    if body[0] != unit & 0xFF:
        raise FrameError(f"RTU reply from slave {body[0]}, expected {unit & 0xFF}")
    return body[1:]


def parse_mbap_reply(frame: bytes, transaction_id: int, unit: int) -> bytes:
    """Check the MBAP header against the request; return the PDU."""
    if len(frame) < MBAP_HEADER_LEN + 1:
        raise FrameError(f"MBAP reply too short ({len(frame)} bytes)")
    tid, protocol, length, reply_unit = struct.unpack(">HHHB", frame[:MBAP_HEADER_LEN])
    if protocol != 0:
        raise FrameError(f"MBAP protocol id {protocol}, expected 0")
    if tid != transaction_id & 0xFFFF:
        raise StaleReply(f"MBAP transaction id {tid}, expected {transaction_id & 0xFFFF}")
    if length != len(frame) - 6:
        raise FrameError(f"MBAP length field {length} does not match {len(frame) - 6} bytes received")
    if reply_unit != unit & 0xFF:
        raise FrameError(f"MBAP reply from unit {reply_unit}, expected {unit & 0xFF}")
    return frame[MBAP_HEADER_LEN:]


# --------------------------------------------------------------- reading


def read_rtu_reply(link: Link, unit: int, timeout: float, char_timeout: float) -> bytes:
    """Read one RTU reply to a 0x10 request, sized from its function byte.

    An exception reply is 5 bytes and a normal one 8; reading a fixed 8 would
    stall for the whole timeout on every exception. Stray bytes before the
    reply (RS-485 turnaround glitches, converter leftovers) are skipped until
    the slave address and a plausible function byte line up.
    """
    head = link.read(2, timeout)
    if not head:
        raise ModbusTimeout(f"no reply within {timeout:.2f}s")
    skipped = bytearray()
    while True:
        if len(head) < 2:
            raise FrameError(f"RTU reply cut after {hexdump(bytes(skipped) + head)}")
        if head[0] == unit & 0xFF and head[1] in (FUNC_WRITE_MULTIPLE_REGISTERS, FUNC_WRITE_MULTIPLE_REGISTERS | 0x80):
            break
        if len(skipped) >= MAX_RTU_RESYNC_BYTES:
            link.discard_input(wait=char_timeout)
            raise FrameError(f"no RTU reply start found in {hexdump(bytes(skipped) + head)}")
        skipped.append(head[0])
        head = head[1:] + link.read(1, char_timeout)
    if skipped:
        log.info("  skipped %d stray byte(s) before the reply: %s", len(skipped), hexdump(bytes(skipped)))
    rest_len = 3 if head[1] & 0x80 else 6  # exception code + CRC, or address + quantity + CRC
    rest = link.read(rest_len, char_timeout)
    frame = head + rest
    if len(rest) < rest_len:
        raise FrameError(f"RTU reply truncated: {hexdump(frame)}")
    return frame


def read_mbap_reply(link: Link, timeout: float, char_timeout: float) -> bytes:
    header = link.read(MBAP_HEADER_LEN, timeout)
    if not header:
        raise ModbusTimeout(f"no reply within {timeout:.2f}s")
    if len(header) < MBAP_HEADER_LEN:
        raise FrameError(f"MBAP header truncated: {hexdump(header)}")
    length = struct.unpack(">H", header[4:6])[0]
    if not 2 <= length <= 254:
        link.discard_input(wait=char_timeout)
        raise FrameError(f"implausible MBAP length {length}: {hexdump(header)}")
    rest = link.read(length - 1, char_timeout)
    frame = header + rest
    if len(rest) < length - 1:
        raise FrameError(f"MBAP reply truncated: {hexdump(frame)}")
    return frame


# ---------------------------------------------------------------- client


@dataclass
class WriteResult:
    framing: Framing
    attempts: int
    request: bytes
    reply: bytes


class ModbusClient:
    """Write registers over a link, with validation, retries and framing detection."""

    def __init__(
        self,
        link: Link,
        framing: Framing,
        *,
        timeout: float = 1.0,
        char_timeout: float = 0.2,
        attempts: int = 3,
        retry_delay: float = 0.1,
    ):
        if attempts < 1:
            raise ValueError("attempts must be >= 1")
        self.link = link
        self.framing = framing
        self.detected: Framing | None = None if framing is Framing.AUTO else framing
        self.timeout = timeout
        self.char_timeout = char_timeout
        self.attempts = attempts
        self.retry_delay = retry_delay
        self._transaction_id = 0

    def write_registers(self, unit: int, address: int, values: list[int]) -> WriteResult:
        pdu = write_multiple_registers_pdu(address, values)
        last_error: ModbusError | None = None
        for attempt in range(1, self.attempts + 1):
            if attempt > 1:
                time.sleep(self.retry_delay)
                log.info("Retry %d/%d", attempt, self.attempts)
            try:
                framing, request, reply = self._exchange(unit, address, len(values), pdu)
                return WriteResult(framing, attempt, request, reply)
            except ModbusExceptionResponse as ex:
                log.warning("  %s", ex)
                last_error = ex
                if ex.code not in RETRYABLE_EXCEPTIONS:
                    raise
            except (ModbusError, LinkError) as ex:
                log.warning("  %s", ex)
                last_error = ex if isinstance(ex, ModbusError) else ModbusError(str(ex))
        if self.framing is Framing.AUTO and not isinstance(last_error, ModbusExceptionResponse):
            self.detected = None
        assert last_error is not None
        raise last_error

    # A single request/response; raises on any failure.
    def _exchange(self, unit: int, address: int, count: int, pdu: bytes) -> tuple[Framing, bytes, bytes]:
        if self.detected is not None:
            request, reply = self._send(self.detected, unit, address, count, pdu)
            return self.detected, request, reply

        # Detection. A real gateway always answers (even if only with an
        # exception), so silence or a non-MBAP reply rules MBAP out.
        try:
            request, reply = self._send(Framing.MBAP, unit, address, count, pdu)
        except ModbusExceptionResponse:
            self._detected_as(Framing.MBAP)
            raise
        except (ModbusError, LinkError) as ex:
            # A converter may also drop the socket on a frame it does not understand.
            log.info("  not a Modbus TCP gateway (%s); trying raw RTU", ex)
            try:
                self.link.discard_input(wait=self.char_timeout)
            except LinkError:
                pass  # _send reconnects
        else:
            self._detected_as(Framing.MBAP)
            return Framing.MBAP, request, reply

        try:
            request, reply = self._send(Framing.RTU, unit, address, count, pdu)
        except ModbusExceptionResponse:
            self._detected_as(Framing.RTU)  # a valid CRC proves the framing
            raise
        self._detected_as(Framing.RTU)
        return Framing.RTU, request, reply

    def _detected_as(self, framing: Framing) -> None:
        if self.detected != framing:
            self.detected = framing
            log.info(
                "Converter type detected: %s",
                "Modbus TCP gateway" if framing is Framing.MBAP else "transparent (raw RTU over TCP)",
            )

    def _send(self, framing: Framing, unit: int, address: int, count: int, pdu: bytes) -> tuple[bytes, bytes]:
        if framing is Framing.MBAP:
            self._transaction_id = (self._transaction_id + 1) & 0xFFFF
            tid = self._transaction_id
            request = mbap_frame(tid, unit, pdu)
        else:
            request = rtu_frame(unit, pdu)

        self.link.ensure_open()
        try:
            self.link.discard_input()
        except LinkError:
            # The peer closed the idle socket; reconnect now instead of losing this attempt.
            self.link.open()
        log.info("TX %s: %s", framing.value.upper(), hexdump(request))
        self.link.write(request)
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                if framing is Framing.MBAP:
                    remaining = max(deadline - time.monotonic(), self.char_timeout)
                    reply = read_mbap_reply(self.link, remaining, self.char_timeout)
                else:
                    reply = read_rtu_reply(self.link, unit, self.timeout, self.char_timeout)
                log.info("RX %s: %s", framing.value.upper(), hexdump(reply))
                if framing is Framing.MBAP:
                    reply_pdu = parse_mbap_reply(reply, tid, unit)
                else:
                    reply_pdu = parse_rtu_reply(reply, unit)
                check_write_response(reply_pdu, address, count)
            except StaleReply as ex:
                # Late answer to an earlier attempt: drop it and keep waiting for ours.
                log.info("  ignored: %s", ex)
                if time.monotonic() >= deadline:
                    raise ModbusTimeout(f"no current reply within {self.timeout:.2f}s") from ex
                continue
            except FrameError:
                self.link.discard_input(wait=self.char_timeout)
                raise
            break
        return request, reply
