import struct

import pytest

from elevator_call_tester.drivers import CallRequest, ConnectionConfig, DriverError, TkeDriver
from elevator_call_tester.drivers.tke import (
    MSG_ACCESS_DENIED,
    MSG_ALREADY_ON_FLOOR,
    build_registers,
    parse_mco_map,
)
from elevator_call_tester.modbus import Framing, rtu_frame

from .test_modbus import OK_PDU, mbap_gateway, rtu_slave

SERIAL = ConnectionConfig(kind="serial", serial_port="COM3")
TCP_AUTO = ConnectionConfig(kind="tcp", host="10.0.0.5", port=4001, framing=Framing.AUTO)
PARAMS = {"unit_id": "1", "device": "4", "floor_offset": "0", "mco_map": "1:0-10;2:11-30", "message": "auto"}


def registers_of(frame: bytes) -> list[int]:
    # RTU: unit, func, addr(2), qty(2), bytes(1), data(16), crc(2)
    return list(struct.unpack(">8H", frame[7:23]))


# ------------------------------------------------------------- MCO map


def test_mco_map_example_from_docs():
    mco_map, warnings = parse_mco_map("1:4,6,7-18;2:20-99")
    assert warnings == []
    assert mco_map.resolve(4) == (1, True)
    assert mco_map.resolve(18) == (1, True)
    assert mco_map.resolve(20) == (2, True)
    assert mco_map.resolve(5) == (1, False)  # default fallback


def test_mco_map_bare_entry_is_fallback():
    mco_map, _ = parse_mco_map("1:1-3; 7")
    assert mco_map.resolve(50) == (7, False)


def test_mco_map_negative_floors():
    mco_map, _ = parse_mco_map("3:-3--1;1:-0-2")
    assert mco_map.resolve(-2) == (3, True)
    assert mco_map.resolve(0) == (1, True)


def test_mco_map_overlap_keeps_first_and_warns():
    mco_map, warnings = parse_mco_map("1:1-5;2:5-9")
    assert mco_map.resolve(5) == (1, True)
    assert warnings and "floor 5" in warnings[0]


@pytest.mark.parametrize("text", ["1:", "1:4-", "1:9-3", "x:1", "1:a", "1:1-5000", "1:0-1000"])
def test_mco_map_rejects_malformed(text):
    with pytest.raises(DriverError):
        parse_mco_map(text)


def test_mco_map_empty_uses_default():
    mco_map, _ = parse_mco_map("")
    assert mco_map.resolve(3) == (1, False)


# ----------------------------------------------------------- registers


def test_registers_layout():
    assert build_registers(5, 9, 4, 2, 2, 17, 0) == [3, 4, 7, 2, 0, 0, 17, 0]


def test_negative_offset_moves_floors_up():
    assert build_registers(1, 2, 0, 1, -2, 1, 0)[:3] == [3, 0, 4]


def test_floor_below_zero_after_offset_is_rejected():
    with pytest.raises(DriverError, match="origin floor"):
        build_registers(0, 5, 1, 1, 1, 1, 0)


# -------------------------------------------------------------- driver


def make_driver(fake_link, responder):
    links = []

    def factory(config):
        link = fake_link(responder)
        links.append(link)
        return link

    return TkeDriver(link_factory=factory), links


def test_serial_call_end_to_end(fake_link):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(SERIAL)
    result = driver.call(CallRequest(3, 15, PARAMS))
    assert result.accepted
    regs = registers_of(links[0].sent[0])
    assert regs == [3, 4, 15, 2, 0, 0, 1, 0]


def test_counter_increments_per_call(fake_link):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(SERIAL)
    driver.call(CallRequest(1, 2, PARAMS))
    driver.call(CallRequest(1, 2, PARAMS))
    assert [registers_of(f)[6] for f in links[0].sent] == [1, 2]


def test_same_floor_sends_already_on_floor(fake_link):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(SERIAL)
    driver.call(CallRequest(4, 4, PARAMS))
    assert registers_of(links[0].sent[0])[7] == MSG_ALREADY_ON_FLOOR


def test_explicit_display_message(fake_link):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(SERIAL)
    driver.call(CallRequest(1, 5, {**PARAMS, "message": str(MSG_ACCESS_DENIED)}))
    assert registers_of(links[0].sent[0])[7] == MSG_ACCESS_DENIED


@pytest.mark.parametrize(
    "params",
    [{"unit_id": "0"}, {"unit_id": "248"}, {"device": ""}, {"device": "abc"}, {"mco_map": "1:9-3"}],
)
def test_invalid_parameters_raise_before_sending(fake_link, params):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(SERIAL)
    with pytest.raises(DriverError):
        driver.call(CallRequest(1, 2, {**PARAMS, **params}))
    assert links[0].sent == []


def test_no_reply_returns_failed_result(fake_link):
    driver, _ = make_driver(fake_link, lambda req: b"")
    driver.connect(SERIAL)
    result = driver.call(CallRequest(1, 2, PARAMS))
    assert not result.accepted
    assert "no reply" in result.summary


def test_exception_reply_returns_failed_result(fake_link):
    driver, _ = make_driver(fake_link, lambda req: rtu_frame(1, bytes([0x90, 0x02])))
    driver.connect(SERIAL)
    result = driver.call(CallRequest(1, 2, PARAMS))
    assert not result.accepted and "0x02" in result.summary


def test_wrong_unit_id_gets_no_answer(fake_link):
    driver, _ = make_driver(fake_link, rtu_slave(unit=2))
    driver.connect(SERIAL)
    assert not driver.call(CallRequest(1, 2, PARAMS)).accepted


def test_framing_detection_is_cached_across_reconnects(fake_link):
    driver, links = make_driver(fake_link, rtu_slave())
    driver.connect(TCP_AUTO)
    driver.call(CallRequest(1, 2, PARAMS))
    assert len(links[0].sent) == 2  # probe + RTU
    driver.close()
    driver.connect(TCP_AUTO)
    driver.call(CallRequest(1, 2, PARAMS))
    assert len(links[1].sent) == 1


def test_forced_gateway_framing(fake_link):
    driver, links = make_driver(fake_link, mbap_gateway())
    driver.connect(ConnectionConfig(kind="tcp", host="h", port=502, framing=Framing.MBAP))
    assert driver.call(CallRequest(1, 2, PARAMS)).accepted
    assert links[0].sent[0][2:4] == b"\x00\x00"  # MBAP protocol id


@pytest.mark.parametrize(
    "config",
    [
        ConnectionConfig(kind="serial"),
        ConnectionConfig(kind="tcp", host="", port=502),
        ConnectionConfig(kind="tcp", host="h", port=0),
        ConnectionConfig(kind="tcp", host="h", port=70000),
        ConnectionConfig(kind="can"),
    ],
)
def test_invalid_connection_config(fake_link, config):
    driver, _ = make_driver(fake_link, rtu_slave())
    with pytest.raises(DriverError):
        driver.connect(config)
    assert not driver.is_connected


def test_call_requires_connection():
    with pytest.raises(DriverError, match="not connected"):
        TkeDriver().call(CallRequest(1, 2, PARAMS))


def test_ok_pdu_constant():
    assert bytes.fromhex("1000000008") == OK_PDU


def test_mco_map_accepts_1000_floors():
    mco_map, _ = parse_mco_map("1:0-999")
    assert mco_map.resolve(999) == (1, True)
