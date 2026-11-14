"""TK Elevator (formerly thyssenkrupp Elevator) destination call over Modbus.

One call = one function 0x10 write of 8 holding registers from address 0.
The same layout travels over a serial line (Modbus RTU, 19200 8E1) or a TCP
converter (Modbus TCP gateway, or a transparent converter carrying raw RTU).
Register map and field notes: ``docs/protocol.md``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..links import Link, SerialLink, SerialSettings, TcpLink
from ..modbus import Framing, ModbusClient, ModbusError, ModbusExceptionResponse
from .base import CallRequest, CallResult, ConnectionConfig, DriverError, ElevatorDriver, Parameter

log = logging.getLogger(__name__)

START_REGISTER = 0x0000
REGISTER_COUNT = 8

MSG_NONE = 0
MSG_ALREADY_ON_FLOOR = 2
MSG_ACCESS_DENIED = 11

DEFAULT_MCO = 1
DEFAULT_UNIT_ID = 1

SERIAL = SerialSettings(baudrate=19200, bytesize=8, parity="E", stopbits=1)


def parse_int(text: str, name: str, lo: int, hi: int, default: int | None = None) -> int:
    text = (text or "").strip()
    if not text:
        if default is None:
            raise DriverError(f"{name} is required")
        return default
    try:
        value = int(text)
    except ValueError:
        raise DriverError(f"{name} must be an integer, got {text!r}") from None
    if not lo <= value <= hi:
        raise DriverError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


# ------------------------------------------------------------------ MCO map

_RANGE = re.compile(r"^\s*(-?\d+)\s*(?:-\s*(-?\d+)\s*)?$")


@dataclass(frozen=True)
class McoMap:
    """Which MCO (TKE group controller output) serves each destination floor."""

    floors: dict[int, int]  # floor -> MCO
    fallback: int = DEFAULT_MCO

    def resolve(self, floor: int) -> tuple[int, bool]:
        """Return (mco, mapped). ``mapped`` is False when the fallback was used."""
        if floor in self.floors:
            return self.floors[floor], True
        return self.fallback, False


def parse_mco_map(text: str) -> tuple[McoMap, list[str]]:
    """Parse ``1:4,6,7-18;2:20-99``. A bare entry (``2``) is the fallback MCO.

    Floors may be negative (``1:-2-5`` is -2..5). Returns the map plus warnings
    for overlaps; malformed input raises DriverError.
    """
    floors: dict[int, int] = {}
    warnings: list[str] = []
    fallback: int | None = None

    for entry in (text or "").split(";"):
        entry = entry.strip()
        if not entry:
            continue
        mco_text, sep, ranges = entry.partition(":")
        mco = parse_int(mco_text, f"MCO in {entry!r}", 0, 0xFFFF)
        if not sep:
            if fallback is not None and fallback != mco:
                warnings.append(f"fallback MCO {fallback} replaced by {mco}")
            fallback = mco
            continue
        if not ranges.strip():
            raise DriverError(f"MCO entry {entry!r} has no floors after ':'")
        for part in ranges.split(","):
            match = _RANGE.match(part)
            if not match:
                raise DriverError(f"invalid floor range {part.strip()!r} in {entry!r}")
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) is not None else start
            if end < start:
                raise DriverError(f"floor range {part.strip()!r} is reversed")
            if end - start >= 1000:
                raise DriverError(f"floor range {part.strip()!r} is too large")
            for floor in range(start, end + 1):
                previous = floors.get(floor)
                if previous is not None and previous != mco:
                    warnings.append(f"floor {floor} mapped to MCO {previous} and {mco}; keeping {previous}")
                    continue
                floors[floor] = mco

    return McoMap(floors, DEFAULT_MCO if fallback is None else fallback), warnings


# -------------------------------------------------------------- registers


def build_registers(
    origin_floor: int,
    destination_floor: int,
    device: int,
    mco: int,
    floor_offset: int,
    counter: int,
    message: int,
) -> list[int]:
    """The 8 call registers. Raises DriverError if a value does not fit in 16 bits."""
    origin = origin_floor - floor_offset
    destination = destination_floor - floor_offset
    for name, value in (("origin floor", origin), ("destination floor", destination)):
        if not 0 <= value <= 0xFFFF:
            raise DriverError(
                f"{name} minus floor offset is {value}; the elevator expects 0..65535. Check the floor offset."
            )
    return [
        origin,  # 0 origin floor (after offset)
        device,  # 1 device / terminal number at the origin
        destination,  # 2 destination floor (after offset)
        mco,  # 3 destination MCO
        0,  # 4 mode + type (fixed)
        0,  # 5 call parameter (fixed)
        counter & 0xFFFF,  # 6 call counter
        message,  # 7 display message
    ]


# ----------------------------------------------------------------- driver


class TkeDriver(ElevatorDriver):
    id = "tke-modbus"
    name = "TK Elevator (Modbus)"
    serial_settings = SERIAL
    tcp_framings = (Framing.AUTO, Framing.MBAP, Framing.RTU)
    default_tcp_port = 502
    parameters = (
        Parameter("unit_id", "tke.unit_id", str(DEFAULT_UNIT_ID), "tke.unit_id.help"),
        Parameter("device", "tke.device", "1", "tke.device.help"),
        Parameter("floor_offset", "tke.floor_offset", "0", "tke.floor_offset.help"),
        Parameter("mco_map", "tke.mco_map", "1", "tke.mco_map.help"),
        Parameter(
            "message",
            "tke.message",
            "auto",
            "tke.message.help",
            choices=(
                ("auto", "tke.message.auto"),
                (str(MSG_NONE), "tke.message.none"),
                (str(MSG_ALREADY_ON_FLOOR), "tke.message.already_on_floor"),
                (str(MSG_ACCESS_DENIED), "tke.message.access_denied"),
            ),
        ),
    )

    def __init__(self, link_factory=None):
        self._link_factory = link_factory or self._default_link
        self._link: Link | None = None
        self._client: ModbusClient | None = None
        self._config: ConnectionConfig | None = None
        # The converter type at an address does not change between reconnects.
        self._framing_cache: dict[tuple[str, int], Framing] = {}
        self.counter = 0

    @staticmethod
    def _default_link(config: ConnectionConfig) -> Link:
        if config.kind == "serial":
            return SerialLink(config.serial_port, SERIAL)
        return TcpLink(config.host, config.port)

    @property
    def is_connected(self) -> bool:
        # A dropped socket or unplugged adapter is reopened on the next call,
        # so the session stays up until close().
        return self._client is not None

    def connect(self, config: ConnectionConfig) -> None:
        self.close()
        if config.kind == "serial":
            if not config.serial_port:
                raise DriverError("no serial port selected")
            framing = Framing.RTU
        elif config.kind == "tcp":
            if not config.host.strip():
                raise DriverError("no converter IP address")
            if not 1 <= config.port <= 65535:
                raise DriverError(f"TCP port must be between 1 and 65535, got {config.port}")
            framing = config.framing
        else:
            raise DriverError(f"unknown transport {config.kind!r}")

        link = self._link_factory(config)
        log.info("Connecting to %s", link.description)
        link.open()
        self._link, self._config = link, config
        self._client = ModbusClient(link, framing)
        if config.kind == "tcp":
            cached = self._framing_cache.get((config.host, config.port))
            if framing is Framing.AUTO and cached:
                self._client.detected = cached
                log.info("Converter type already known for this address: %s", cached.value)
            elif framing is Framing.AUTO:
                log.info("Converter type will be detected on the first call")
            log.info("A transparent converter must be set to %s and TCP server / raw mode", SERIAL)
        log.info("Connected to %s", link.description)

    def close(self) -> None:
        if self._link is not None:
            self._link.close()
            log.info("Disconnected from %s", self._link.description)
        self._link = self._client = self._config = None

    def call(self, request: CallRequest) -> CallResult:
        if self._client is None or self._config is None:
            raise DriverError("not connected")
        params = request.params
        unit = parse_int(params.get("unit_id", ""), "Gateway address", 1, 247, DEFAULT_UNIT_ID)
        device = parse_int(params.get("device", ""), "Device", 0, 0xFFFF)
        offset = parse_int(params.get("floor_offset", ""), "Floor offset", -0xFFFF, 0xFFFF, 0)
        mco_map, warnings = parse_mco_map(params.get("mco_map", ""))
        for warning in warnings:
            log.warning("MCO map: %s", warning)

        message_choice = (params.get("message") or "auto").strip()
        if message_choice == "auto":
            same_floor = request.origin_floor == request.destination_floor
            message = MSG_ALREADY_ON_FLOOR if same_floor else MSG_NONE
        else:
            message = parse_int(message_choice, "Display message", 0, 0xFFFF)

        mco, mapped = mco_map.resolve(request.destination_floor)
        if not mapped:
            log.info("Floor %s not in the MCO map; using MCO %s", request.destination_floor, mco)

        registers = build_registers(
            request.origin_floor,
            request.destination_floor,
            device,
            mco,
            offset,
            (self.counter + 1) & 0xFFFF,
            message,
        )
        self.counter = (self.counter + 1) & 0xFFFF

        log.info(
            "Call: origin floor %s -> destination floor %s, device %s, MCO %s, offset %s, message %s, counter %s",
            request.origin_floor,
            request.destination_floor,
            device,
            mco,
            offset,
            message,
            registers[6],
        )
        log.info("Registers 0-7: %s", registers)

        try:
            result = self._client.write_registers(unit, START_REGISTER, registers)
        except ModbusExceptionResponse as ex:
            self._remember_framing()
            log.error("Call rejected: %s", ex)
            return CallResult(False, str(ex))
        except ModbusError as ex:
            log.error("Call failed: %s", ex)
            if self._config.kind == "tcp" and self._config.framing is Framing.AUTO:
                self._framing_cache.pop((self._config.host, self._config.port), None)
            return CallResult(False, str(ex))

        self._remember_framing()
        summary = f"accepted by unit {unit} ({result.framing.value.upper()}, attempt {result.attempts})"
        log.info("Call %s", summary)
        return CallResult(True, summary)

    def _remember_framing(self) -> None:
        if self._config and self._config.kind == "tcp" and self._client and self._client.detected:
            self._framing_cache[(self._config.host, self._config.port)] = self._client.detected
