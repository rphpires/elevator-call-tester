# Troubleshooting

The log lines that matter are `TX` (what was sent), `RX` (what came back) and the line right
after them. Frame layouts are in [protocol.md](protocol.md).

## Connecting

| Message | Check |
|---|---|
| `cannot open serial port COMx: ... PermissionError / Access is denied` | Another program holds the port (old session, terminal, vendor tool). Close it. |
| `cannot open serial port ... FileNotFoundError` | Adapter unplugged or a different COM number. Press **Refresh**. |
| `cannot connect to <ip>:<port>: timed out` | Wrong IP or subnet, firewall, or converter off. Ping it first. |
| `cannot connect to <ip>:<port>: ... refused` | Wrong TCP port, or the converter already has a client (many accept only one). |

## Calls

| Message | Meaning | Check |
|---|---|---|
| `no reply within 1.00s` (serial) | Nothing came back | A/B swapped, wrong slave address, no common ground, adapter driver set to the wrong mode (RS-232 / RS-422) |
| `not a Modbus TCP gateway (...); trying raw RTU` | Normal during detection on a transparent converter | — |
| `no reply` on both framings (IP) | The converter answered neither framing | Transparent converter: serial settings must be 19200 8E1 and the mode TCP server/raw; also check the RS-485 wiring and the slave address. Gateway: unit id and serial-side configuration. |
| `RTU reply CRC mismatch` | Bytes came back corrupted | Parity or baud rate mismatch on a converter, noise, missing termination on long runs |
| `RTU reply from slave N, expected M` | Another device answered | Two devices share the address, or the gateway address is wrong |
| `reply echoes address ... / count ...` | Device answered but not to this request | Wrong device type at that address |
| `ignored: MBAP transaction id ..., expected ...` | Late reply from an earlier request, skipped | Gateway slower than the 1 s timeout; frequent occurrences point at a slow or overloaded gateway |
| `skipped N stray byte(s) before the reply` | Noise before the reply, recovered | Occasional is normal on RS-485; constant means bad termination, biasing or grounding |
| `Modbus exception 0x0B (gateway target device failed to respond)` | The gateway is reachable, the elevator behind it is not | Wiring and settings on the gateway's serial side, unit id → slave mapping |
| `Modbus exception 0x0A (gateway path unavailable)` | Gateway has no route for this unit id | Gateway routing table |
| `Modbus exception 0x02 / 0x03` | The elevator interface refused the content | Register map version, floor / MCO / device out of the configured range |
| `connection closed by <ip>:<port>` | Converter dropped the socket | Idle timeout on the converter. The tool reconnects on the next attempt. |
| `origin floor minus floor offset is -1` | Refused before sending | The offset makes the floor negative; check its sign |
| `MCO map: floor N mapped to MCO a and b` | Overlapping ranges | First entry wins; fix the map |

## The call is accepted but no car comes

The interface acknowledged the Modbus write, so communication is fine. On the elevator side,
check:

- the device number belongs to a terminal at the origin floor,
- the MCO serves the destination floor,
- the floor offset makes access control floor N match elevator floor N,
- the elevator group is in a mode that accepts destination calls.
