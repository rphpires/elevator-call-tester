# Field guide

A checklist for the first call on site. Every action is written to the on-screen log and to a
session file (**Open log folder**); attach that file to any support ticket.

Log folder: `%LOCALAPPDATA%\ElevatorCallTester\logs` on Windows,
`~/.local/state/elevator-call-tester/logs` on Linux. The last 50 sessions are kept.

## Before you start

- Agree with the people responsible for the elevator system **when** you will place test
  calls. These are real calls: cars will move.
- Get from the elevator side: the interface **slave address** (gateway address), the
  **device numbers** of the terminals, the **MCO per floor range**, and whether access
  control floors and elevator floors are numbered the same (if not, you need the **floor
  offset**).

## Serial (RS-485)

1. Connect a USB–RS-485 adapter: A to A (D+), B to B (D−), and signal ground if there is a
   terminal for it. On a bus with more than two devices, terminate only the ends.
2. In the app: **Connection type → Serial (Modbus RTU)**, choose the port (**Refresh** after
   plugging in the adapter; you can also type a name such as `COM7` or `/dev/ttyUSB0`), then
   **Connect**.
   The line settings are fixed at **19200 8E1** by the protocol.
3. Fill in the call (next section) and press **Place call**.

## IP converter

1. Find out which converter type you have:
   - **Modbus TCP gateway:** the converter "speaks Modbus TCP" and is configured with a
     Modbus RTU master or slave on its serial side.
   - **Transparent converter / serial device server** in TCP server or raw socket mode.
     Set its serial port to **19200 baud, 8 data bits, even parity, 1 stop bit**.
2. In the app: **Connection type → IP converter (TCP)**, the converter IP, and the TCP port
   (502 for gateways; transparent converters often use 4001 or similar).
3. Leave **Converter type** on *Detect automatically* the first time. The log shows what was
   detected, and later calls go straight to it. Only one client can usually connect to the
   converter at a time, so close any other software connected to it.
4. **Connect**, fill in the call, **Place call**.

## Filling in the call

| Field | What to enter |
|---|---|
| Origin floor / Destination floor | Floors as the access control system numbers them |
| Gateway address | Modbus slave address of the elevator interface (default 1) |
| Device | Terminal number at the origin floor |
| Floor offset | Subtracted from both floors before sending (`-2` sends floor 1 as 3) |
| Destination MCOs | e.g. `1:4,6,7-18;2:20-99` (see the `?` button) |
| Display message | Automatic, or force a message to test the terminal display |

A good first test is a call between two nearby floors served by the same MCO. Then try one
floor from each MCO range.

## Reading the result

- **`Call accepted by unit 1 (RTU, attempt 1)`**: the elevator interface accepted the
  frame. If the car still does not come, the issue is on the elevator side: device number,
  MCO, floor mapping, or the elevator's own configuration.
- **`Call failed` / `Call rejected`**: see [troubleshooting.md](troubleshooting.md). The
  lines just above in the log show exactly what was sent (`TX`) and received (`RX`).
