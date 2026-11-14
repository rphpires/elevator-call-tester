# Architecture

```
ui/app.py ─────► ui/worker.py ─────► drivers/<manufacturer>.py ─────► modbus.py ─────► links.py
 Tk widgets      one I/O thread      call → registers / frames        framing,          serial port /
 form from       serializes every    (ElevatorDriver)                 validation,       TCP socket
 driver params   connect/call/close                                   retries           (bytes only)
```

| Layer | Knows about | Does not know about |
|---|---|---|
| `links.py` | opening a port or socket, moving bytes, timeouts, discarding stale input | Modbus, elevators |
| `modbus.py` | RTU/MBAP frames, CRC, reply validation, exception codes, retries, framing detection | which registers mean what |
| `drivers/` | the manufacturer's register layout, field validation, floor and MCO rules | Tk, threads |
| `ui/` | widgets, language, saved settings, the worker thread | protocol details |

## Threading

Serial and TCP calls block for up to a few seconds. Every driver operation (`connect`,
`call`, `close`) runs on a **single** `IoWorker` thread:

- the window stays responsive,
- operations run strictly one after another, so a disconnect cannot interleave with a call
  in progress,
- Tk is touched only from the Tk thread. Form values are read into plain Python values
  *before* a task is submitted, and results come back through a queue that the Tk thread
  polls every 50 ms. Log records take the same route: a `QueueHandler` on the logger, drained
  by the Tk thread.

While an operation is running, or a connection is open, the controls that would change the
connection are disabled.

## Adding a manufacturer

1. Create `elevator_call_tester/drivers/<name>.py` with a subclass of
   `ElevatorDriver` (`drivers/base.py`):

   ```python
   class AcmeDriver(ElevatorDriver):
       id = "acme-modbus"
       name = "Acme (Modbus)"
       serial_settings = SerialSettings(9600, 8, "N", 1)  # None if there is no serial transport
       tcp_framings = (Framing.MBAP,)  # () if there is no TCP transport
       parameters = (
           Parameter("unit_id", "acme.unit_id", "1", "acme.unit_id.help"),
           Parameter("car", "acme.car", "A", choices=(("A", "acme.car.a"), ("B", "acme.car.b"))),
       )

       def connect(self, config: ConnectionConfig) -> None: ...
       def call(self, request: CallRequest) -> CallResult: ...
       def close(self) -> None: ...
       @property
       def is_connected(self) -> bool: ...
   ```

   `CallRequest` carries the origin and destination floors plus the driver's own parameter
   values, as strings straight from the form. Validate them in `call()` and raise
   `DriverError` with a message the technician can act on.

2. Register it in `drivers/__init__.py` (`DRIVERS`). It then appears in the
   **Elevator protocol** list, and the form is built from `parameters`.
3. Add the label and help keys to both languages in `i18n.py`. A test fails if a key is
   missing.
4. Reuse the pieces:
   - `ModbusClient` if the protocol is Modbus (any register layout; add a function code to
     `modbus.py` if 0x10 is not enough),
   - `SerialLink` / `TcpLink` for anything that is bytes over a serial port or a socket,
   - otherwise implement the `Link` protocol (for example, a vendor HTTP or UDP API) and
     keep the framing inside the driver.
5. Add tests with the `FakeLink` fixture in `tests/conftest.py`. If you can, also extend
   `simulator.py` so the driver can be exercised end to end without hardware.

`TkeDriver` (`drivers/tke.py`) is the reference implementation: parameter validation, a
small domain parser (the MCO map), building the register block, and mapping Modbus
outcomes to a `CallResult`.
