"""Tests for ECON-D frame decoder."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
sys.path.insert(0, str(Path(__file__).parent.parent / "data"))

from econ_decoder import EconDecoder, crc8
from generate_test_vectors import generate, build_frame


def test_crc8_known_values():
    assert crc8(b'\x00') == 0x00
    assert crc8(b'\xFF') == 0xF7
    assert crc8(b'\xAC\x01\x00\x0A\x03\x00\x00') is not None


def test_round_trip_single_frame():
    hits = [(2, 3, 300, False, 128), (5, 1, 450, False, 64)]
    frame_bytes = build_frame(orbit=1, bx=42, chip_id=0, hits=hits)
    decoder = EconDecoder()
    frames = list(decoder.decode_stream(frame_bytes))
    assert len(frames) == 1
    f = frames[0]
    assert f.orbit == 1
    assert f.bx == 42
    assert f.crc_ok
    assert len(f.hits) == 2
    assert f.hits[0].u == 2
    assert f.hits[0].v == 3
    assert f.hits[0].adc == 300


def test_round_trip_bulk():
    data = generate(n_events=200, corrupt_rate=0.0)
    decoder = EconDecoder()
    frames = list(decoder.decode_stream(data))
    assert len(frames) == 200
    assert decoder.n_crc_errors == 0


def test_corrupt_frames_detected():
    data = generate(n_events=100, corrupt_rate=0.2)
    decoder = EconDecoder()
    list(decoder.decode_stream(data))
    assert decoder.n_crc_errors > 0


def test_chip_id_filter():
    frames_chip0 = build_frame(0, 0, chip_id=0, hits=[(1, 1, 200, False, 0)])
    frames_chip1 = build_frame(0, 1, chip_id=1, hits=[(2, 2, 300, False, 0)])
    combined = frames_chip0 + frames_chip1

    decoder = EconDecoder(chip_id_filter=0)
    frames = list(decoder.decode_stream(combined))
    assert len(frames) == 1
    assert frames[0].chip_id == 0


def test_empty_stream():
    decoder = EconDecoder()
    frames = list(decoder.decode_stream(b''))
    assert frames == []


def test_charge_conversion():
    hits = [(0, 0, 2048, False, 0)]
    frame_bytes = build_frame(0, 0, 0, hits)
    decoder = EconDecoder()
    frames = list(decoder.decode_stream(frame_bytes))
    hit = frames[0].hits[0]
    # 2048 / 4096 * 80 fC = 40 fC
    assert abs(hit.charge_fC - 40.0) < 0.01
