"""Driver registry. Add a manufacturer by subclassing ElevatorDriver and listing it here."""

from .base import CallRequest, CallResult, ConnectionConfig, DriverError, ElevatorDriver, Parameter
from .tke import TkeDriver

DRIVERS: dict[str, type[ElevatorDriver]] = {
    TkeDriver.id: TkeDriver,
}

__all__ = [
    "DRIVERS",
    "CallRequest",
    "CallResult",
    "ConnectionConfig",
    "DriverError",
    "ElevatorDriver",
    "Parameter",
    "TkeDriver",
]
