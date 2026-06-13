"""Tests for ECON-T trigger primitive decoder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))

from trigger_primitive import decode_word, _crc4, TriggerPrimitive


def _encode_word(et: int, cu: int, cv: int, bx: int,
                 tc: int, mod: int) -> int:
    body = (et << 27) | (cu << 22) | (cv << 17) | (bx << 13) | (tc << 8) | (mod << 4)
    crc  = _crc4(body >> 4)
    return body | crc


def test_decode_valid_word():
    word = _encode_word(et=10, cu=3, cv=14, bx=5, tc=2, mod=1)
    tp   = decode_word(word)
    assert tp.valid
    assert tp.et_raw == 10
    assert abs(tp.et_GeV - 5.0) < 1e-6
    assert tp.bx_mod16 == 5
    assert tp.module_id == 1


def test_crc_error_detected():
    word = _encode_word(et=10, cu=3, cv=14, bx=5, tc=2, mod=1)
    word ^= 0x1  # flip LSB -> CRC mismatch
    tp = decode_word(word)
    assert not tp.valid


def test_centroid_sign():
    # v >= 16 should be interpreted as negative
    word = _encode_word(et=5, cu=16, cv=20, bx=0, tc=0, mod=0)
    tp   = decode_word(word)
    assert tp.centroid_u_signed < 0
    assert tp.centroid_v_signed < 0


def test_zero_energy():
    word = _encode_word(et=0, cu=0, cv=0, bx=0, tc=0, mod=0)
    tp   = decode_word(word)
    assert tp.valid
    assert tp.et_GeV == 0.0


def test_max_energy():
    word = _encode_word(et=1023, cu=15, cv=15, bx=15, tc=31, mod=15)
    tp   = decode_word(word)
    assert tp.valid
    assert abs(tp.et_GeV - 511.5) < 1e-6
