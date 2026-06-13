"""Generate synthetic ECON-D binary test vectors.

Produces a binary file containing N valid (and optionally corrupt) ECON-D
frames that can be used for CI regression testing and decoder development
without real hardware.

Usage:
    python data/generate_test_vectors.py --n-events 500 --output data/test_run.bin
    python data/generate_test_vectors.py --n-events 100 --corrupt-rate 0.05 --output data/test_corrupt.bin
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
from econ_decoder import crc8, SYNC_BYTE


def build_frame(orbit: int, bx: int, chip_id: int,
                hits: list[tuple[int, int, int, bool, int]],
                corrupt_crc: bool = False) -> bytes:
    """Build one ECON-D frame.

    hits: list of (u, v, adc, tot_flag, toa)
    """
    n_hits = len(hits)

    # Build payload
    payload = bytearray()
    for u, v, adc, tot, toa in hits:
        addr = ((u & 0xF) << 4) | (v & 0xF)
        tot_bit = 1 if tot else 0
        word = (addr << 24) | ((adc & 0xFFF) << 12) | (tot_bit << 11) | (toa & 0xFF)
        payload += struct.pack('>I', word)

    # Header (8 bytes)
    hdr = bytearray(8)
    hdr[0] = SYNC_BYTE
    hdr[1] = orbit & 0xFF
    struct.pack_into('>H', hdr, 2, bx & 0xFFFF)
    hdr[4] = n_hits & 0xFF
    hdr[5] = chip_id & 0xFF
    hdr[6] = 0x00
    hdr[7] = crc8(bytes(hdr[:7]))

    # Frame CRC
    frame_crc = crc8(bytes(hdr) + bytes(payload))
    if corrupt_crc:
        frame_crc ^= 0xFF  # flip all bits -> guaranteed error

    return bytes(hdr) + bytes(payload) + bytes([frame_crc])


def generate(n_events: int, chip_id: int = 0,
             corrupt_rate: float = 0.0,
             seed: int = 42) -> bytes:
    rng = np.random.default_rng(seed)
    output = bytearray()

    for i in range(n_events):
        orbit  = (i // 3564) & 0xFF
        bx     = i % 3564
        n_hits = int(rng.poisson(5))          # ~5 hits/event on average
        hits   = []
        for _ in range(n_hits):
            u   = int(rng.integers(0, 8))
            v   = int(rng.integers(0, 8))
            adc = int(rng.integers(100, 512))  # above threshold
            tot = bool(rng.random() < 0.05)
            toa = int(rng.integers(0, 256))
            hits.append((u, v, adc, tot, toa))

        corrupt = rng.random() < corrupt_rate
        output += build_frame(orbit, bx, chip_id, hits, corrupt_crc=corrupt)

    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate ECON-D test vectors")
    parser.add_argument("--n-events",     type=int,   default=1000)
    parser.add_argument("--chip-id",      type=int,   default=0)
    parser.add_argument("--corrupt-rate", type=float, default=0.0,
                        help="Fraction of frames with bad CRC (0.0 - 1.0)")
    parser.add_argument("--output",       default="data/test_run.bin")
    parser.add_argument("--seed",         type=int,   default=42)
    args = parser.parse_args()

    data = generate(args.n_events, args.chip_id, args.corrupt_rate, args.seed)
    out  = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)

    print(f"Wrote {len(data)} bytes ({args.n_events} frames) to {out}")
    if args.corrupt_rate > 0:
        expected = int(args.n_events * args.corrupt_rate)
        print(f"Expected CRC errors: ~{expected}")


if __name__ == "__main__":
    main()
