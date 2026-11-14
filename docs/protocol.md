# Protocol

## TK Elevator destination call

One call is one Modbus **function 0x10 (write multiple registers)** that writes **8 holding
registers starting at address 0x0000**. The register block is the same over every transport;
only the framing around it changes.

| Register | Content | Notes |
|---:|---|---|
| 0 | Origin floor − floor offset | must land in 0..65535 |
| 1 | Device number at the origin | terminal / reader id configured in the elevator system |
| 2 | Destination floor − floor offset | must land in 0..65535 |
| 3 | Destination MCO | from the MCO map (below) |
| 4 | Mode + type | fixed `0` |
| 5 | Call parameter | fixed `0` |
| 6 | Call counter | +1 per call, wraps at 65536 |
| 7 | Display message | `0` none, `2` already on this floor, `11` access denied |

Values are 16-bit big-endian, as Modbus requires.

**Floor offset.** It is subtracted from both floors, so the access control floor numbering
can differ from the elevator's. With an offset of `-2`, floor 1 is sent as 3. If a floor
minus the offset falls below 0, the call is refused before anything is sent. The original
tool sent the value wrapped to 65535-something, and the elevator then got a nonsense floor.

**Display message.** In "Automatic" mode, the tool sends `2` (already on this floor) when
origin equals destination and `0` otherwise. You can also choose `0`, `2` or `11` explicitly,
which helps when testing the terminal display.

**Counter.** Retries resend the *same* register block, counter included, so the controller
can tell a retry from a new call. Only the MBAP transaction id changes between attempts.

### MCO map

```
<mco>:<floors>[;<mco>:<floors>...][;<fallback mco>]
floors = floor | start-end, separated by commas
```

| Input | Meaning |
|---|---|
| `1:4,6,7-18;2:20-99` | MCO 1 serves 4, 6, 7–18; MCO 2 serves 20–99; anything else uses MCO 1 (default) |
| `1:0-10;3` | MCO 1 serves 0–10; anything else uses MCO 3 |
| `2:-3--1;1:0-40` | MCO 2 serves basements −3 to −1 |

The lookup uses the destination floor **before** the offset. A reversed range (`9-3`), a range
with no end (`4-`), non-numeric text, or a range wider than 1000 floors is rejected with a
message. If two entries claim the same floor, the first one wins and the log shows a warning.

## Framings

### Serial: Modbus RTU

19200 baud, 8 data bits, **even** parity, 1 stop bit. Frame: `slave | PDU | CRC-16` (CRC low
byte first).

Example: origin 3 → destination 15, device 4, MCO 2, counter 1, slave 1:

```
TX  01 10 00 00 00 08 10  00 03 00 04 00 0F 00 02 00 00 00 00 00 01 00 00  2C FC
    |  |  addr  qty   len  r0    r1    r2    r3    r4    r5    r6    r7     CRC
    slave  function 0x10
RX  01 10 00 00 00 08 C1 CF                     normal reply: echo of address and quantity
RX  01 90 02 CD C1                              exception reply: 0x90 = 0x10|0x80, code 0x02
```

The reader sizes the reply from its function byte: 8 bytes for a normal reply, 5 for an
exception. A fixed 8-byte read would wait out the whole timeout on every exception. Stray
bytes before the reply (RS-485 turnaround glitches, converter leftovers) are skipped, up to
32 of them, until the slave address and function byte line up.

### IP: Modbus TCP gateway (MBAP)

The gateway takes Modbus TCP and re-frames it as RTU on its serial side. The frame is the MBAP
header plus the PDU, without CRC. The **unit id** in the header is the slave address on the
gateway's serial side, the same "Gateway address" field as in serial mode.

```
TX  00 01 00 00 00 17 01  10 00 00 00 08 10 00 03 00 04 00 0F 00 02 00 00 00 00 00 01 00 00
    tid   proto len   unit PDU
RX  00 01 00 00 00 06 01  10 00 00 00 08        normal reply
RX  00 01 00 00 00 03 01  90 0B                 gateway exception 0x0B: the elevator did not answer
```

The reply must echo the transaction id, protocol 0, the unit id, and a length field that
matches the bytes received. Each request uses a new transaction id. A late reply to an
earlier request is recognized by its old id, then ignored, and the tool keeps waiting for the
current reply.

### IP: transparent converter (raw RTU over TCP)

Serial device servers in "TCP server / raw" mode work like a long serial cable. The socket
carries the RTU frame unchanged, CRC included. The converter's serial port must be set to
**19200 8E1**.

## Converter detection ("Detect automatically")

Both converter types accept a TCP connection in the same way. Only the first exchange tells
them apart:

1. Send the call as **MBAP**. A real gateway always answers, at least with an exception.
   - A valid MBAP reply means it is a gateway. An exception reply also proves the framing;
     the tool reports the exception and does not try RTU.
2. If there is no valid MBAP reply (silence for 1 s, an invalid frame, or the converter
   closing the socket), clear the socket, reconnect if needed, and send the call as **raw RTU**.
   Only the elevator's own reply can carry a correct CRC, so a valid RTU reply proves the
   converter is transparent.
3. The result is remembered for that IP:port, across reconnects too, until a call fails on
   every attempt.

A transparent converter forwards the MBAP probe to the RS-485 bus. The elevator discards it
because its CRC is invalid. A gateway that takes longer than 1 s to answer would instead get
the RTU probe, which it may misread as an MBAP request. If you know the converter type, select
it: that skips the probe entirely.

Both framings travel over **one** TCP connection. Many converters accept a single client, so
a second socket would be refused.

## Timing, validation and retries

| | Value |
|---|---|
| Reply timeout (first byte) | 1.0 s |
| Inter-character timeout (rest of the frame) | 0.2 s |
| Attempts per call | 3, with 100 ms between them |
| TCP connect timeout | 3 s |

Before each request, pending input is discarded. Replies that arrive later are handled
when they are read: MBAP replies with an old transaction id are ignored, and garbage before an
RTU reply is skipped. RTU has no transaction id, so a reply to attempt N arriving during attempt
N+1 is accepted. That is harmless, because both attempts carry the same registers.
Every reply is checked for CRC (RTU), slave or unit id, function, echoed address and quantity,
and the MBAP header. The tool retries on a timeout, an invalid frame, a link error, and the
exception codes 0x05 (acknowledge), 0x06 (busy) and 0x0B (gateway target did not respond).
Other exception codes mean the request is wrong, so the tool reports them without retrying.

If the serial adapter disappears or the TCP peer closes the connection, the link is reopened
on the next attempt.

| Code | Name | Usual cause in the field |
|---|---|---|
| 0x01 | illegal function | device is not the elevator interface, or does not accept 0x10 |
| 0x02 | illegal data address | wrong register map or interface firmware |
| 0x03 | illegal data value | a register value is out of the accepted range (floor, MCO, device) |
| 0x04 | server device failure | elevator interface error |
| 0x06 | server device busy | try again |
| 0x0A | gateway path unavailable | gateway routing / unit id not configured |
| 0x0B | gateway target device failed to respond | gateway is fine; nothing answered on its serial side |
