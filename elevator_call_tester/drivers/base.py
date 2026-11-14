"""Extension point: one :class:`ElevatorDriver` per manufacturer protocol.

A driver turns a generic :class:`CallRequest` (origin floor, destination
floor, plus its own declared :class:`Parameter` values) into bytes on a link.
The UI renders the parameter form from ``parameters`` and never needs to know
the protocol. See ``docs/architecture.md`` for how to add a manufacturer.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..links import SerialSettings
from ..modbus import Framing


class DriverError(Exception):
    """Invalid parameters, or a call the elevator did not accept. Message is shown to the user."""


@dataclass(frozen=True)
class Parameter:
    key: str
    label: str  # i18n key
    default: str = ""
    help: str | None = None  # i18n key
    choices: tuple[tuple[str, str], ...] = ()  # (value, i18n label key); empty = free text


@dataclass(frozen=True)
class ConnectionConfig:
    kind: str  # "serial" or "tcp"
    serial_port: str = ""
    host: str = ""
    port: int = 0
    framing: Framing = Framing.AUTO


@dataclass(frozen=True)
class CallRequest:
    origin_floor: int
    destination_floor: int
    params: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class CallResult:
    accepted: bool
    summary: str


class ElevatorDriver(abc.ABC):
    id: str
    name: str
    parameters: tuple[Parameter, ...] = ()
    serial_settings: SerialSettings | None = None  # None = no serial transport
    tcp_framings: tuple[Framing, ...] = ()  # empty = no TCP transport
    default_tcp_port: int = 502

    @property
    def transports(self) -> tuple[str, ...]:
        kinds = []
        if self.serial_settings is not None:
            kinds.append("serial")
        if self.tcp_framings:
            kinds.append("tcp")
        return tuple(kinds)

    @abc.abstractmethod
    def connect(self, config: ConnectionConfig) -> None:
        """Open the link. Raises DriverError or LinkError."""

    @abc.abstractmethod
    def call(self, request: CallRequest) -> CallResult:
        """Send one call. Raises DriverError for invalid input."""

    @abc.abstractmethod
    def close(self) -> None:
        """Release the link. Must be safe to call twice."""

    @property
    @abc.abstractmethod
    def is_connected(self) -> bool:
        """True between a successful connect() and close()."""
