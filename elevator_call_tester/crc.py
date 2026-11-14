"""CRC-16/MODBUS (poly 0xA001 reflected, init 0xFFFF)."""


def _build_table() -> tuple[int, ...]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
        table.append(crc)
    return tuple(table)


_TABLE = _build_table()


def crc16_modbus(data: bytes, crc: int = 0xFFFF) -> int:
    """Return the Modbus RTU CRC of ``data``. On the wire it goes low byte first."""
    for byte in data:
        crc = (crc >> 8) ^ _TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF
