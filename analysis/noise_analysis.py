"""Noise characterisation from HGCROC threshold scans.

Given a CSV with columns [channel, threshold_DAC, n_hits, n_total], fits
a complementary error function (S-curve) per channel to extract:
  - Pedestal (mu): threshold at 50% efficiency
  - ENC (sigma): noise in DAC counts -> converted to electrons
  - Threshold dispersion across the wafer

Usage:
    python analysis/noise_analysis.py data/threshold_scan.csv --plot
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np
from scipy.optimize import curve_fit
from scipy.special import erfc


# 1 DAC count ≈ 0.5 fC ≈ 3125 e- for the HGCROC internal DAC
DAC_TO_ELECTRONS = 3125.0


@dataclass
class ChannelFit:
    channel: int
    mu_dac: float
    sigma_dac: float
    mu_err: float
    sigma_err: float
    converged: bool

    @property
    def enc_electrons(self) -> float:
        return self.sigma_dac * DAC_TO_ELECTRONS

    @property
    def pedestal_fC(self) -> float:
        return self.mu_dac * 0.5


def _scurve(threshold: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    """Complementary error function model for threshold scan efficiency."""
    return 0.5 * erfc((threshold - mu) / (np.sqrt(2) * sigma))


def fit_channel(thresholds: np.ndarray, efficiencies: np.ndarray,
                channel: int) -> ChannelFit:
    # Initial guess: mu at 50% efficiency point, sigma = 1 DAC
    mid = np.interp(0.5, efficiencies[::-1], thresholds[::-1])
    p0 = [mid, 1.0]
    try:
        popt, pcov = curve_fit(_scurve, thresholds, efficiencies,
                               p0=p0, maxfev=2000,
                               bounds=([0, 0.01], [1023, 50]))
        perr = np.sqrt(np.diag(pcov))
        return ChannelFit(channel, popt[0], popt[1], perr[0], perr[1], True)
    except (RuntimeError, ValueError):
        return ChannelFit(channel, float('nan'), float('nan'),
                          float('nan'), float('nan'), False)


def load_scan(path: str) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    """Returns {channel: (thresholds, efficiencies)}."""
    import csv
    rows: dict[int, list] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ch = int(row["channel"])
            thr = float(row["threshold_DAC"])
            eff = int(row["n_hits"]) / int(row["n_total"])
            rows.setdefault(ch, []).append((thr, eff))

    result = {}
    for ch, points in rows.items():
        points.sort(key=lambda x: x[0])
        arr = np.array(points)
        result[ch] = (arr[:, 0], arr[:, 1])
    return result


def analyse(path: str, plot: bool = False) -> list[ChannelFit]:
    scan = load_scan(path)
    fits: list[ChannelFit] = []

    for ch, (thr, eff) in scan.items():
        fits.append(fit_channel(thr, eff, ch))

    good = [f for f in fits if f.converged]
    if not good:
        print("ERROR: no channels converged", file=sys.stderr)
        return fits

    mus    = np.array([f.mu_dac for f in good])
    sigmas = np.array([f.sigma_dac for f in good])
    encs   = np.array([f.enc_electrons for f in good])

    print(f"Channels fit successfully: {len(good)} / {len(fits)}")
    print(f"Pedestal  mean={mus.mean():.1f}  std={mus.std():.2f}  DAC counts")
    print(f"Noise     mean={sigmas.mean():.2f}  std={sigmas.std():.2f}  DAC counts")
    print(f"ENC       mean={encs.mean():.0f}  std={encs.std():.0f}  e-")
    print(f"Threshold dispersion (sigma RMS): {mus.std():.2f} DAC = "
          f"{mus.std() * 0.5:.2f} fC")

    dead  = [f.channel for f in fits if not f.converged]
    noisy = [f.channel for f in good if f.sigma_dac > 5.0]
    if dead:
        print(f"Dead channels  ({len(dead)}): {dead}")
    if noisy:
        print(f"Noisy channels ({len(noisy)}): {noisy}")

    if plot:
        _plot(good, mus, sigmas)

    return fits


def _plot(fits: list[ChannelFit], mus: np.ndarray, sigmas: np.ndarray) -> None:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib not installed -- skipping plot")
        return

    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    axes[0].hist(mus, bins=30, color="steelblue", edgecolor="white")
    axes[0].set_xlabel("Pedestal (DAC counts)")
    axes[0].set_ylabel("Channels")
    axes[0].set_title("Pedestal distribution")

    axes[1].hist(sigmas * DAC_TO_ELECTRONS / 1000, bins=30,
                 color="darkorange", edgecolor="white")
    axes[1].set_xlabel("ENC (ke⁻)")
    axes[1].set_title("Equivalent Noise Charge")

    axes[2].hist(mus - mus.mean(), bins=30, color="mediumseagreen", edgecolor="white")
    axes[2].set_xlabel("Pedestal - <pedestal> (DAC)")
    axes[2].set_title("Threshold dispersion")

    fig.tight_layout()
    plt.savefig("noise_analysis.png", dpi=150)
    print("Plot saved to noise_analysis.png")


def main() -> None:
    parser = argparse.ArgumentParser(description="HGCROC threshold scan analysis")
    parser.add_argument("input", help="CSV file with threshold scan data")
    parser.add_argument("--plot", action="store_true", help="Generate plots")
    args = parser.parse_args()
    analyse(args.input, plot=args.plot)


if __name__ == "__main__":
    main()
