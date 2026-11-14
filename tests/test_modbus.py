import struct

import pytest

from elevator_call_tester.crc import crc16_modbus
from elevator_call_tester.modbus import (
    FrameError,
    Framing,
    ModbusClient,
    ModbusExceptionResponse,
    ModbusTimeout,
    check_write_response,
    mbap_frame,
    parse_mbap_reply,
    parse_rtu_reply,
    rtu_frame,
    write_multiple_registers_pdu,
)

VALUES = [3, 1, 7, 2, 0, 0, 42, 0]
PDU = write_multiple_registers_pdu(0, VALUES)
OK_PDU = bytes.fromhex("1000000008")


def rtu_reply(unit, pdu):
    return rtu_frame(unit, pdu)


def test_pdu_layout():
    assert PDU[:6] == bytes.fromhex("10 0000 0008 10")
    assert struct.unpack(">8H", PDU[6:]) == tuple(VALUES)


@pytest.mark.parametrize("values", [[], [0] * 124, [-1], [0x10000]])
def test_pdu_rejects_bad_values(values):
    with pytest.raises(ValueError):
        write_multiple_registers_pdu(0, values)


def test_rtu_frame_matches_reference_bytes():
    # Frame produced by the original tool for the same registers.
    frame = rtu_frame(1, write_multiple_registers_pdu(0, [3, 1, 7, 1, 0, 0, 1, 0]))
    assert frame.hex(" ") == ("01 10 00 00 00 08 10 00 03 00 01 00 07 00 01 00 00 00 00 00 01 00 00 1e 69")


def test_mbap_frame_header():
    frame = mbap_frame(0x1234, 5, PDU)
    assert frame[:7] == struct.pack(">HHHB", 0x1234, 0, len(PDU) + 1, 5)
    assert frame[7:] == PDU


def test_parse_rtu_reply_checks_crc_and_unit():
    good = rtu_reply(1, OK_PDU)
    assert parse_rtu_reply(good, 1) == OK_PDU
    with pytest.raises(FrameError, match="CRC"):
        parse_rtu_reply(good[:-1] + bytes([good[-1] ^ 1]), 1)
    with pytest.raises(FrameError, match="slave"):
        parse_rtu_reply(good, 2)
    with pytest.raises(FrameError, match="short"):
        parse_rtu_reply(b"\x01\x10", 1)


def test_parse_mbap_reply_checks_header():
    good = mbap_frame(7, 1, OK_PDU)
    assert parse_mbap_reply(good, 7, 1) == OK_PDU
    with pytest.raises(FrameError, match="transaction"):
        parse_mbap_reply(good, 8, 1)
    with pytest.raises(FrameError, match="unit"):
        parse_mbap_reply(good, 7, 2)
    with pytest.raises(FrameError, match="protocol"):
        parse_mbap_reply(good[:2] + b"\x00\x01" + good[4:], 7, 1)
    with pytest.raises(FrameError, match="length"):
        parse_mbap_reply(good + b"\x00", 7, 1)


def test_check_write_response():
    check_write_response(OK_PDU, 0, 8)
    with pytest.raises(FrameError, match="echoes"):
        check_write_response(bytes.fromhex("1000000007"), 0, 8)
    with pytest.raises(FrameError, match="function"):
        check_write_response(bytes.fromhex("0300000008"), 0, 8)
    with pytest.raises(ModbusExceptionResponse) as info:
        check_write_response(bytes.fromhex("9002"), 0, 8)
    assert info.value.code == 2


# ------------------------------------------------------------- client


def rtu_slave(unit=1, reply_pdu=OK_PDU):
    """Answers valid RTU frames for ``unit``; ignores anything else (bad CRC = noise)."""

    def respond(request):
        if len(request) < 4 or crc16_modbus(request) != 0 or request[0] != unit:
            return b""
        return rtu_frame(unit, reply_pdu)

    return respond


def mbap_gateway(reply_pdu=OK_PDU):
    def respond(request):
        tid, proto, length, unit = struct.unpack(">HHHB", request[:7])
        if proto != 0 or length != len(request) - 6:
            return b""
        return mbap_frame(tid, unit, reply_pdu)

    return respond


def test_rtu_write_success(fake_link):
    link = fake_link(rtu_slave())
    client = ModbusClient(link, Framing.RTU)
    result = client.write_registers(1, 0, VALUES)
    assert result.attempts == 1 and result.framing is Framing.RTU
    assert link.sent == [rtu_frame(1, PDU)]


def test_rtu_timeout_retries_then_fails(fake_link):
    link = fake_link()
    client = ModbusClient(link, Framing.RTU, attempts=3)
    with pytest.raises(ModbusTimeout):
        client.write_registers(1, 0, VALUES)
    assert len(link.sent) == 3


def test_rtu_exception_reply_is_read_as_5_bytes_and_not_retried(fake_link):
    link = fake_link(rtu_slave(reply_pdu=bytes([0x90, 0x02])))
    client = ModbusClient(link, Framing.RTU)
    with pytest.raises(ModbusExceptionResponse) as info:
        client.write_registers(1, 0, VALUES)
    assert info.value.code == 2
    assert len(link.sent) == 1


def test_busy_exception_is_retried(fake_link):
    replies = [bytes([0x90, 0x06]), OK_PDU]
    link = fake_link(lambda req: rtu_frame(1, replies.pop(0)))
    result = ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES)
    assert result.attempts == 2


def test_corrupted_reply_is_retried(fake_link):
    replies = [rtu_frame(1, OK_PDU)[:-1] + b"\x00", rtu_frame(1, OK_PDU)]
    link = fake_link(lambda req: replies.pop(0))
    assert ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES).attempts == 2


def test_stale_bytes_are_discarded_before_sending(fake_link):
    link = fake_link(rtu_slave())
    link.rx += b"\xde\xad"  # late reply to an earlier request
    assert ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES).attempts == 1


def test_link_failure_reopens_and_retries(fake_link):
    link = fake_link(rtu_slave())
    link.open()
    link.fail_next_write = True
    result = ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES)
    assert result.attempts == 2
    assert link.opened == 2


def test_mbap_transaction_ids_increase(fake_link):
    link = fake_link(mbap_gateway())
    client = ModbusClient(link, Framing.MBAP)
    client.write_registers(1, 0, VALUES)
    client.write_registers(1, 0, VALUES)
    assert [struct.unpack(">H", f[:2])[0] for f in link.sent] == [1, 2]


def test_mbap_reply_with_old_transaction_id_alone_is_not_accepted(fake_link):
    link = fake_link(lambda req: mbap_frame(999, 1, OK_PDU))
    with pytest.raises(ModbusTimeout):
        ModbusClient(link, Framing.MBAP, attempts=1).write_registers(1, 0, VALUES)


def test_mbap_late_reply_is_skipped_and_current_one_accepted(fake_link):
    def respond(request):
        tid = struct.unpack(">H", request[:2])[0]
        return mbap_frame(tid - 1, 1, OK_PDU) + mbap_frame(tid, 1, OK_PDU)

    result = ModbusClient(fake_link(respond), Framing.MBAP).write_registers(1, 0, VALUES)
    assert result.attempts == 1


@pytest.mark.parametrize("noise", [b"\x00", b"\xff\x00", bytes(range(20, 40))])
def test_rtu_stray_bytes_before_reply_are_skipped(fake_link, noise):
    link = fake_link(lambda req: noise + rtu_frame(1, OK_PDU))
    assert ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES).attempts == 1


def test_rtu_endless_noise_is_a_frame_error(fake_link):
    link = fake_link(lambda req: b"\x55" * 100)
    with pytest.raises(FrameError, match="no RTU reply start"):
        ModbusClient(link, Framing.RTU, attempts=1).write_registers(1, 0, VALUES)


def test_idle_socket_closed_by_peer_reconnects_without_losing_the_attempt(fake_link):
    from elevator_call_tester.links import LinkError

    link = fake_link(rtu_slave())
    link.open()
    original = link.discard_input

    def closed_once(wait=0.0):
        link.discard_input = original
        raise LinkError("connection closed")

    link.discard_input = closed_once
    assert ModbusClient(link, Framing.RTU).write_registers(1, 0, VALUES).attempts == 1
    assert link.opened == 2


def test_auto_link_drop_after_mbap_probe_still_tries_rtu(fake_link):
    from elevator_call_tester.links import LinkError

    link = fake_link(rtu_slave())
    original_write = link.write

    def write(data):
        if crc16_modbus(data) != 0:  # the MBAP probe: converter drops the socket
            link._open = False
            raise LinkError("connection closed")
        original_write(data)

    link.write = write
    client = ModbusClient(link, Framing.AUTO)
    assert client.write_registers(1, 0, VALUES).framing is Framing.RTU
    assert client.detected is Framing.RTU


def test_auto_detects_gateway(fake_link):
    link = fake_link(mbap_gateway())
    client = ModbusClient(link, Framing.AUTO)
    assert client.write_registers(1, 0, VALUES).framing is Framing.MBAP
    assert client.detected is Framing.MBAP
    assert len(link.sent) == 1


def test_auto_detects_transparent_converter_and_remembers(fake_link):
    link = fake_link(rtu_slave())
    client = ModbusClient(link, Framing.AUTO)
    assert client.write_registers(1, 0, VALUES).framing is Framing.RTU
    assert len(link.sent) == 2  # MBAP probe, then RTU
    client.write_registers(1, 0, VALUES)
    assert len(link.sent) == 3  # no more probing


def test_auto_gateway_exception_is_reported_not_probed_as_rtu(fake_link):
    link = fake_link(mbap_gateway(reply_pdu=bytes([0x90, 0x02])))
    client = ModbusClient(link, Framing.AUTO)
    with pytest.raises(ModbusExceptionResponse):
        client.write_registers(1, 0, VALUES)
    assert client.detected is Framing.MBAP
    assert len(link.sent) == 1


def test_auto_forgets_detection_after_total_failure(fake_link):
    link = fake_link(rtu_slave())
    client = ModbusClient(link, Framing.AUTO)
    client.write_registers(1, 0, VALUES)
    link.responder = lambda req: b""
    with pytest.raises(ModbusTimeout):
        client.write_registers(1, 0, VALUES)
    assert client.detected is None
