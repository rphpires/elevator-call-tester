from elevator_call_tester.crc import crc16_modbus


def test_check_value():
    # CRC-16/MODBUS catalogue check value.
    assert crc16_modbus(b"123456789") == 0x4B37


def test_known_modbus_frame():
    # Read holding registers 0..9 of slave 1: 01 03 00 00 00 0A C5 CD
    crc = crc16_modbus(bytes.fromhex("01030000000A"))
    assert crc.to_bytes(2, "little") == bytes.fromhex("C5CD")


def test_frame_with_its_crc_checks_to_zero():
    body = bytes.fromhex("011000000008")
    frame = body + crc16_modbus(body).to_bytes(2, "little")
    assert crc16_modbus(frame) == 0
