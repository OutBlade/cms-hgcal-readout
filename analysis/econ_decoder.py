"""ECON-D frame decoder.

Parses the binary output of the ECON-D data concentrator into structured
hit records. The frame format follows the HGCAL CMS Phase-2 specification:

  [ 64-bit header | N x 32-bit channel words | 8-bit CRC ]

Header fields (MSB first):
  [63:56]  Sync word  0xAC
  [55:48]  Orbit number (low 8 bits)
  [47:32]  BX counter (16 bits)
  [31:24]  N_hits (8 bits, number of payload words)
  [23:16]  ECON-D chip ID (8 bits)
  [15: 8]  Reserved
  [ 7: 0]  Header CRC-8

Channel word (32 bits):
  [31:24]  Channel address (u[3:0] | v[3:0])
  [23:12]  ADC value (12 bits)
  [11: 8]  ToT flag + overflow bits
  [ 7: 0]  ToA (8 bits, 25ns / 256)
"""

from __future__ import annotations

import struct
import argparse
from dataclasses import dataclass, field
from typing import Iterator
import numpy as np


SYNC_BYTE = 0xAC
CRC8_POLY = 0x07  # CRC-8/CCITT


# ---------------------------------------------------------------------------
# CRC-8 helper
# ---------------------------------------------------------------------------

def _build_crc_table() -> list[int]:
    table = []
    for byte in range(256):
        crc = byte
        for _ in range(8):
            crc = ((crc << 1) ^ CRC8_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        table.append(crc)
    return table


_CRC_TABLE = _build_crc_table()


def crc8(data: bytes | bytearray) -> int:
    crc = 0
    for byte in data:
        crc = _CRC_TABLE[crc ^ byte]
    return crc


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ChannelHit:
    u: int
    v: int
    adc: int
    tot_flag: bool
    overflow: bool
    toa: int

    @property
    def charge_fC(self) -> float:
        """Rough ADC -> fC conversion assuming 80 fC full-scale / 4096."""
        return self.adc * 80.0 / 4096.0

    @property
    def time_ns(self) -> float:
        return self.toa * 25.0 / 256.0


@dataclass
class EconFrame:
    orbit: int
    bx: int
    chip_id: int
    hits: list[ChannelHit] = field(default_factory=list)
    crc_ok: bool = True


# ---------------------------------------------------------------------------
# Decoder
# ---------------------------------------------------------------------------

class EconDecoder:
    """Stateful decoder that consumes a raw byte stream of ECON-D frames."""

    def __init__(self, chip_id_filter: int | None = None) -> None:
        self.chip_id_filter = chip_id_filter
        self.n_frames = 0
        self.n_crc_errors = 0

    def decode_stream(self, data: bytes) -> Iterator[EconFrame]:
        pos = 0
        while pos + 9 <= len(data):  # minimum frame: 8-byte header + 1-byte CRC
            if data[pos] != SYNC_BYTE:
                pos += 1
                continue

            # Parse 8-byte header
            if pos + 8 > len(data):
                break
            hdr = data[pos:pos + 8]
            orbit     = hdr[1]
            bx        = struct.unpack_from('>H', hdr, 2)[0]
            n_hits    = hdr[4]
            chip_id   = hdr[5]
            hdr_crc   = hdr[7]

            if crc8(hdr[:7]) != hdr_crc:
                pos += 1
                continue

            if self.chip_id_filter is not None and chip_id != self.chip_id_filter:
                pos += 8 + n_hits * 4 + 1
                continue

            payload_start = pos + 8
            payload_end   = payload_start + n_hits * 4
            crc_pos       = payload_end

            if crc_pos + 1 > len(data):
                break

            payload = data[payload_start:payload_end]
            received_crc = data[crc_pos]
            computed_crc = crc8(hdr + payload)

            frame = EconFrame(orbit=orbit, bx=bx, chip_id=chip_id,
                              crc_ok=(received_crc == computed_crc))

            if not frame.crc_ok:
                self.n_crc_errors += 1

            for i in range(n_hits):
                word = struct.unpack_from('>I', payload, i * 4)[0]
                addr     = (word >> 24) & 0xFF
                adc      = (word >> 12) & 0xFFF
                tot_flag = bool(word & (1 << 11))
                overflow = bool(word & (1 << 10))
                toa      = word & 0xFF
                u = (addr >> 4) & 0xF
                v = addr & 0xF
                frame.hits.append(ChannelHit(u, v, adc, tot_flag, overflow, toa))

            self.n_frames += 1
            yield frame
            pos = crc_pos + 1

    def summary(self) -> str:
        rate = self.n_crc_errors / self.n_frames if self.n_frames else 0.0
        return (
            f"Frames decoded : {self.n_frames}\n"
            f"CRC errors     : {self.n_crc_errors}  ({rate:.2%})\n"
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Decode ECON-D binary stream")
    parser.add_argument("input", help="Raw binary file from ECON-D capture")
    parser.add_argument("--chip-id", type=int, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()

    with open(args.input, "rb") as f:
        data = f.read()

    decoder = EconDecoder(chip_id_filter=args.chip_id)
    for n, frame in enumerate(decoder.decode_stream(data)):
        if args.max_frames and n >= args.max_frames:
            break
        if not args.summary:
            crc_label = "OK" if frame.crc_ok else "ERR"
            print(f"Frame {n:05d}  orbit={frame.orbit} bx={frame.bx:04d}  "
                  f"chip={frame.chip_id}  hits={len(frame.hits)}  CRC={crc_label}")

    print(decoder.summary())


if __name__ == "__main__":
    main()
