"""lpGBT link bandwidth budget estimator.

Estimates the lpGBT uplink utilisation as a function of pile-up (PU)
and zero-suppression threshold for the HGCAL readout.

lpGBT uplink: 1.28 Gbps, 32 bits per 25 ns bunch crossing.
After FEC and overhead: ~28 usable bits per BX.

Usage:
    python analysis/bandwidth_budget.py --pileup 200 --threshold 0.5
"""

from __future__ import annotations

import argparse
import numpy as np

# lpGBT parameters
LPGBT_RATE_GBPS  = 1.28
BX_PERIOD_NS     = 25.0
BITS_PER_BX      = int(LPGBT_RATE_GBPS * 1e9 * BX_PERIOD_NS * 1e-9)  # 32
OVERHEAD_BITS    = 4     # lpGBT frame header per BX
USABLE_BITS_PER_BX = BITS_PER_BX - OVERHEAD_BITS  # 28

# HGCAL channel parameters
CHANNELS_PER_HGCROC = 72
ECON_D_CHANNELS     = 2 * CHANNELS_PER_HGCROC  # two HGCROCs per ECON-D
BITS_PER_HIT        = 32   # one 32-bit channel word per hit
HEADER_BITS         = 64 + 8   # 8-byte header + 1-byte CRC

# Occupancy model: roughly Poisson with mean proportional to PU
# At PU=200, ~0.01 hit/channel/BX for a minimum-bias event mix (MIP threshold)
BASE_OCCUPANCY_PER_CH = 0.01   # hits per channel per BX at PU=200, threshold=0.5 fC


def expected_hits(n_channels: int, pileup: int, threshold_fC: float) -> float:
    """Simple occupancy model: linear in PU, exponential in threshold."""
    occ = BASE_OCCUPANCY_PER_CH * (pileup / 200.0) * np.exp(-threshold_fC / 1.0)
    return occ * n_channels


def bits_per_bx(n_channels: int, pileup: int, threshold_fC: float) -> float:
    hits = expected_hits(n_channels, pileup, threshold_fC)
    return HEADER_BITS + hits * BITS_PER_HIT


def utilisation(pileup: int, threshold_fC: float) -> float:
    bpb = bits_per_bx(ECON_D_CHANNELS, pileup, threshold_fC)
    return bpb / USABLE_BITS_PER_BX


def print_table(pileups: list[int], thresholds: list[float]) -> None:
    print(f"lpGBT utilisation (%) — ECON-D ({ECON_D_CHANNELS} channels)\n")
    header = "PU\\Thr(fC)  " + "  ".join(f"{t:>7.1f}" for t in thresholds)
    print(header)
    print("-" * len(header))
    for pu in pileups:
        row = f"{pu:>10d}  "
        for thr in thresholds:
            u = utilisation(pu, thr) * 100
            flag = " (!)" if u > 80 else ""
            row += f"{u:>7.1f}{flag}  "
        print(row)
    print()
    print("(!) marks utilisation > 80% — link saturation risk")


def main() -> None:
    parser = argparse.ArgumentParser(description="lpGBT bandwidth budget")
    parser.add_argument("--pileup",    type=int,   default=200)
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Zero-suppression threshold in fC")
    parser.add_argument("--table",     action="store_true",
                        help="Print full PU x threshold table")
    args = parser.parse_args()

    if args.table:
        print_table(
            pileups=[0, 50, 100, 140, 200],
            thresholds=[0.25, 0.5, 1.0, 2.0, 4.0],
        )
    else:
        u = utilisation(args.pileup, args.threshold)
        hits = expected_hits(ECON_D_CHANNELS, args.pileup, args.threshold)
        bpb  = bits_per_bx(ECON_D_CHANNELS, args.pileup, args.threshold)
        print(f"PU={args.pileup}  threshold={args.threshold} fC")
        print(f"Expected hits/BX  : {hits:.1f}")
        print(f"Bits/BX           : {bpb:.0f}  (budget: {USABLE_BITS_PER_BX})")
        print(f"Link utilisation  : {u*100:.1f}%")


if __name__ == "__main__":
    main()
