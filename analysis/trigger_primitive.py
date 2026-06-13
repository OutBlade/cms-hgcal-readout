"""ECON-T trigger primitive decoder.

The ECON-T transmits 37-bit trigger sum words at 40 MHz to the Level-1 trigger
backend via the Stage-1 TPG (Trigger Primitive Generator).

37-bit word layout (MSB first):
  [36:27]  Energy sum E_T (10 bits, 0.5 GeV LSB)
  [26:22]  Centroid u (5 bits, signed)
  [21:17]  Centroid v (5 bits, signed)
  [16:13]  Bunch crossing (4 bits, modulo 16)
  [12: 8]  Trigger cell address (5 bits)
  [ 7: 4]  Module ID (4 bits)
  [ 3: 0]  Frame CRC nibble (4 bits)
"""

from __future__ import annotations

from dataclasses import dataclass
import numpy as np


ET_LSB_GEV = 0.5  # GeV per LSB


@dataclass
class TriggerPrimitive:
    et_raw: int
    centroid_u: int
    centroid_v: int
    bx_mod16: int
    tc_address: int
    module_id: int
    crc4: int
    valid: bool = True

    @property
    def et_GeV(self) -> float:
        return self.et_raw * ET_LSB_GEV

    @property
    def centroid_u_signed(self) -> int:
        return self.centroid_u - 16 if self.centroid_u >= 16 else self.centroid_u

    @property
    def centroid_v_signed(self) -> int:
        return self.centroid_v - 16 if self.centroid_v >= 16 else self.centroid_v


def _crc4(word37_no_crc: int) -> int:
    """CRC-4/ITU over the upper 33 bits."""
    poly = 0x3
    crc = 0
    for i in range(32, -1, -1):
        bit = (word37_no_crc >> i) & 1
        if (crc >> 3) ^ bit:
            crc = ((crc << 1) ^ poly) & 0xF
        else:
            crc = (crc << 1) & 0xF
    return crc


def decode_word(word: int) -> TriggerPrimitive:
    """Decode a single 37-bit trigger primitive word."""
    et_raw     = (word >> 27) & 0x3FF
    cu         = (word >> 22) & 0x1F
    cv         = (word >> 17) & 0x1F
    bx         = (word >> 13) & 0xF
    tc_addr    = (word >>  8) & 0x1F
    module_id  = (word >>  4) & 0xF
    crc_recv   = word & 0xF

    crc_calc   = _crc4(word >> 4)
    valid      = (crc_recv == crc_calc)

    return TriggerPrimitive(et_raw, cu, cv, bx, tc_addr, module_id, crc_recv, valid)


def decode_array(words: np.ndarray) -> list[TriggerPrimitive]:
    return [decode_word(int(w)) for w in words]


def summary_table(primitives: list[TriggerPrimitive]) -> str:
    valid = [p for p in primitives if p.valid]
    lines = [
        f"{'BX':>4}  {'E_T (GeV)':>9}  {'u':>4}  {'v':>4}  {'TC':>3}  {'Mod':>3}  CRC",
        "-" * 48,
    ]
    for p in valid[:20]:
        lines.append(
            f"{p.bx_mod16:>4}  {p.et_GeV:>9.1f}  "
            f"{p.centroid_u_signed:>4}  {p.centroid_v_signed:>4}  "
            f"{p.tc_address:>3}  {p.module_id:>3}  {'OK' if p.valid else 'ERR'}"
        )
    if len(valid) > 20:
        lines.append(f"  ... ({len(valid) - 20} more)")
    lines.append(f"\nTotal: {len(primitives)}  Valid: {len(valid)}  "
                 f"CRC errors: {len(primitives) - len(valid)}")
    return "\n".join(lines)
