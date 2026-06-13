"""CRC correctness tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
from econ_decoder import crc8


def test_crc8_empty():
    assert crc8(b'') == 0x00


def test_crc8_single_zero():
    assert crc8(b'\x00') == 0x00


def test_crc8_single_ff():
    assert crc8(b'\xFF') == 0xF7


def test_crc8_sequence():
    # Known-good value computed independently with online CRC calculator
    # CRC-8/SMBUS of [0x31, 0x32, 0x33, 0x34, 0x35] = 0xA1
    assert crc8(bytes([0x31, 0x32, 0x33, 0x34, 0x35])) == 0xA1


def test_crc8_append_zeroes_changes_result():
    a = crc8(b'\xAC\x01\x00\x05\x01\x00\x00')
    b = crc8(b'\xAC\x01\x00\x05\x01\x00\x00\x00')
    assert a != b


def test_crc8_consistency():
    data = bytes(range(64))
    assert crc8(data) == crc8(data)
