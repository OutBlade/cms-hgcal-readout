"""Hexagonal cell occupancy map for HGCAL wafer visualisation.

Uses axial (u, v) hex coordinates consistent with the HGCAL geometry
convention. Renders a coloured hexagonal grid where each cell is coloured
by its hit rate relative to the mean.

Usage:
    python analysis/occupancy_map.py --input data/hits.npy --layer 12 --output occ.png
"""

from __future__ import annotations

import argparse
import numpy as np
from collections import Counter


# HGCAL HD wafer: 7x7 hex grid with corner cells removed -> 37 full cells
# Axial (u, v) coordinates for a type-HD half-wafer (simplified)
WAFER_CELLS_HD = [
    (u, v) for u in range(-3, 4) for v in range(-3, 4)
    if abs(u + v) <= 3
]


def hits_to_occupancy(hits_uv: list[tuple[int, int]],
                      n_events: int) -> dict[tuple[int, int], float]:
    counter = Counter(hits_uv)
    return {cell: counter.get(cell, 0) / n_events for cell in WAFER_CELLS_HD}


def hex_to_pixel(u: int, v: int, size: float = 30.0) -> tuple[float, float]:
    """Axial -> Cartesian for flat-top hexagons."""
    x = size * (3 / 2 * u)
    y = size * (np.sqrt(3) / 2 * u + np.sqrt(3) * v)
    return x, y


def hexagon_vertices(cx: float, cy: float, size: float) -> np.ndarray:
    angles = np.deg2rad(np.arange(0, 360, 60))
    xs = cx + size * np.cos(angles)
    ys = cy + size * np.sin(angles)
    return np.column_stack([xs, ys])


def plot_occupancy(occ: dict[tuple[int, int], float],
                   layer: int, output: str = "occupancy.png") -> None:
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        from matplotlib.collections import PolyCollection
        from matplotlib.colors import Normalize
        import matplotlib.cm as cm
    except ImportError:
        print("matplotlib not installed -- skipping plot")
        return

    size = 28.0
    verts, values = [], []
    for (u, v), rate in occ.items():
        cx, cy = hex_to_pixel(u, v, size)
        verts.append(hexagon_vertices(cx, cy, size * 0.95))
        values.append(rate)

    values = np.array(values)
    norm   = Normalize(vmin=0, vmax=values.max() * 1.1 or 1)
    cmap   = cm.plasma

    fig, ax = plt.subplots(figsize=(7, 6))
    col = PolyCollection(verts, array=values, cmap=cmap, norm=norm,
                         edgecolors="white", linewidths=0.5)
    ax.add_collection(col)
    ax.set_xlim(-120, 120)
    ax.set_ylim(-120, 120)
    ax.set_aspect("equal")
    ax.axis("off")

    cbar = fig.colorbar(col, ax=ax, shrink=0.8, pad=0.02)
    cbar.set_label("Hit rate per event")

    ax.set_title(f"HGCAL HD wafer occupancy — layer {layer}", fontsize=13)
    fig.tight_layout()
    plt.savefig(output, dpi=150, bbox_inches="tight")
    print(f"Occupancy map saved to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="HGCAL hex cell occupancy map")
    parser.add_argument("--input",  default=None,
                        help="Numpy file with columns [u, v] (one hit per row). "
                             "Omit to use synthetic data.")
    parser.add_argument("--layer",  type=int, default=1,
                        help="Layer number for plot title")
    parser.add_argument("--n-events", type=int, default=10_000)
    parser.add_argument("--output", default="occupancy.png")
    args = parser.parse_args()

    if args.input:
        arr = np.load(args.input)
        hits = [(int(r[0]), int(r[1])) for r in arr]
        n_events = args.n_events
    else:
        rng = np.random.default_rng(42)
        cells = WAFER_CELLS_HD
        # Simulate a hotspot near centre
        weights = np.array([np.exp(-(u**2 + v**2) / 4) for u, v in cells])
        weights /= weights.sum()
        indices = rng.choice(len(cells), size=args.n_events * 3, p=weights)
        hits = [cells[i] for i in indices]
        n_events = args.n_events

    occ = hits_to_occupancy(hits, n_events)
    plot_occupancy(occ, layer=args.layer, output=args.output)


if __name__ == "__main__":
    main()
