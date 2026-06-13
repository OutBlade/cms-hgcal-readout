"""
HGCAL Lab -- Desktop analysis application for CMS HGCAL prototype readout.
Supports: ECON-D frame decoding, noise characterisation, occupancy mapping,
          bandwidth budget estimation, and real-time demo mode.

Usage:
    python app/hgcal_lab.py
    python app/hgcal_lab.py --demo        # start in demo mode
    python app/hgcal_lab.py --screenshot  # take page screenshots and exit
"""

from __future__ import annotations
import argparse
import math
import sys
import threading
import time
from collections import deque
from pathlib import Path

# Resolve analysis/ and data/ whether running from source or as a frozen bundle.
def _setup_paths() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)          # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent.parent
    for sub in ("analysis", "data"):
        p = str(base / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return base

_BASE_DIR = _setup_paths()

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize
import matplotlib.cm as cm
import numpy as np
from scipy.special import erfc
from scipy.optimize import curve_fit

# ── App-wide theme ───────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_ACCENT  = "#4a90d9"
C_OK      = "#2ecc71"
C_ERR     = "#e74c3c"
C_WARN    = "#f39c12"
C_BG      = "#0d1117"
C_SIDEBAR = "#161b22"
C_CARD    = "#21262d"
C_BORDER  = "#30363d"
C_TEXT    = "#e6edf3"
C_MUTED   = "#8b949e"

plt.rcParams.update({
    "figure.facecolor": C_BG,
    "axes.facecolor":   "#0f1b35",
    "axes.edgecolor":   C_BORDER,
    "text.color":       C_TEXT,
    "axes.labelcolor":  C_TEXT,
    "xtick.color":      C_MUTED,
    "ytick.color":      C_MUTED,
    "grid.color":       C_BORDER,
    "grid.alpha":       0.5,
    "axes.titlecolor":  C_TEXT,
    "axes.titlesize":   11,
    "legend.facecolor": C_CARD,
    "legend.edgecolor": C_BORDER,
})

# ── Demo data ────────────────────────────────────────────────────────────────

WAFER_CELLS = [(u, v) for u in range(-3, 4) for v in range(-3, 4) if abs(u + v) <= 3]


def _scurve(x, mu, sigma):
    return 0.5 * erfc((x - mu) / (np.sqrt(2) * sigma))


def demo_threshold_scan(n_channels: int = 72):
    rng = np.random.default_rng(7)
    thresholds = np.linspace(210, 300, 45)
    channels = []
    for ch in range(n_channels):
        mu    = rng.normal(252, 4.1)
        sigma = rng.normal(2.5, 0.3)
        eff   = _scurve(thresholds, mu, sigma) + rng.normal(0, 0.005, len(thresholds))
        eff   = np.clip(eff, 0, 1)
        channels.append({"ch": ch, "mu": mu, "sigma": sigma,
                         "thresholds": thresholds, "eff": eff})
    return channels


def demo_occupancy_hits(n_events: int = 50_000):
    rng = np.random.default_rng(42)
    weights = np.array([np.exp(-(u**2 + v**2) / 3.5) for u, v in WAFER_CELLS])
    weights /= weights.sum()
    idx = rng.choice(len(WAFER_CELLS), size=n_events * 3, p=weights)
    return [WAFER_CELLS[i] for i in idx], n_events


def hex_vertices(cx, cy, size=26):
    angles = np.deg2rad(np.arange(0, 360, 60))
    return np.column_stack([cx + size * np.cos(angles), cy + size * np.sin(angles)])


def hex_to_pixel(u, v, size=26):
    return size * 1.5 * u, size * (math.sqrt(3) / 2 * u + math.sqrt(3) * v)


# ── Reusable widgets ──────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    def __init__(self, parent, label: str, value: str = "0",
                 accent: str = C_ACCENT, **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=10, **kw)
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=11),
                     text_color=C_MUTED).pack(anchor="w", padx=14, pady=(12, 2))
        self._val = ctk.CTkLabel(self, text=value,
                                 font=ctk.CTkFont("Consolas", 26, "bold"),
                                 text_color=accent)
        self._val.pack(anchor="w", padx=14, pady=(0, 12))

    def set(self, value: str):
        self._val.configure(text=value)


class SectionHeader(ctk.CTkLabel):
    def __init__(self, parent, text: str, **kw):
        super().__init__(parent, text=text,
                         font=ctk.CTkFont(size=14, weight="bold"),
                         text_color=C_TEXT, **kw)


class EmbeddedPlot(ctk.CTkFrame):
    def __init__(self, parent, figsize=(6, 3.5), **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=10, **kw)
        self.fig = Figure(figsize=figsize, tight_layout=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    def clear(self):
        self.fig.clf()
        self.canvas.draw()

    def refresh(self):
        self.canvas.draw()


# ── Pages ─────────────────────────────────────────────────────────────────────

class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._log: deque[str] = deque(maxlen=120)
        self._build()

    def _build(self):
        # Title row
        title_row = ctk.CTkFrame(self, fg_color="transparent")
        title_row.pack(fill="x", pady=(0, 16))
        SectionHeader(title_row, "Dashboard").pack(side="left")
        self._link_badge = ctk.CTkLabel(
            title_row, text="  DEMO MODE  ",
            fg_color=C_WARN, corner_radius=6,
            font=ctk.CTkFont(size=10, weight="bold"), text_color="#000")
        # (shown only in demo mode via update_status)

        # Stat cards
        cards_row = ctk.CTkFrame(self, fg_color="transparent")
        cards_row.pack(fill="x", pady=(0, 16))
        for col in range(4):
            cards_row.columnconfigure(col, weight=1, uniform="card")

        self._card_frames  = StatCard(cards_row, "Frames decoded", accent=C_ACCENT)
        self._card_errors  = StatCard(cards_row, "CRC errors",     accent=C_ERR)
        self._card_hits    = StatCard(cards_row, "Avg hits / frame", accent=C_OK)
        self._card_bx      = StatCard(cards_row, "Last BX",        accent=C_WARN)
        for i, c in enumerate([self._card_frames, self._card_errors,
                                self._card_hits, self._card_bx]):
            c.grid(row=0, column=i, padx=(0, 10) if i < 3 else 0, sticky="ew")

        # Bottom row: log + mini bandwidth chart
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="both", expand=True)
        bottom.columnconfigure(0, weight=3)
        bottom.columnconfigure(1, weight=2)

        # Frame log
        log_frame = ctk.CTkFrame(bottom, fg_color=C_CARD, corner_radius=10)
        log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ctk.CTkLabel(log_frame, text="Frame log",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self._log_box = ctk.CTkTextbox(log_frame, font=ctk.CTkFont("Consolas", 11),
                                       fg_color="#0d1117", text_color=C_TEXT,
                                       state="disabled", wrap="none")
        self._log_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Mini plot
        self._mini_plot = EmbeddedPlot(bottom, figsize=(4.5, 3.5))
        self._mini_plot.grid(row=0, column=1, sticky="nsew")
        self._draw_idle_chart()

    def _draw_idle_chart(self):
        ax = self._mini_plot.fig.add_subplot(111)
        ax.text(0.5, 0.5, "Start demo mode\nto see live data",
                ha="center", va="center", color=C_MUTED, fontsize=12,
                transform=ax.transAxes)
        ax.set_axis_off()
        self._mini_plot.refresh()

    def update_counters(self, n_frames: int, n_errors: int, bx: int, n_hits: int):
        self._card_frames.set(f"{n_frames:,}")
        self._card_errors.set(str(n_errors))
        self._card_hits.set(f"{n_hits:.1f}")
        self._card_bx.set(f"{bx:04d}")
        crc = "OK" if not (n_frames % 50 == 0 and n_errors > 0) else "ERR"
        color = C_OK if crc == "OK" else C_ERR
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}]  frame={n_frames:>6}  bx={bx:>4}  hits={n_hits:>2}  CRC={crc}\n"
        self._log.append(line)
        self._log_box.configure(state="normal")
        self._log_box.insert("end", line)
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

        if n_frames % 20 == 0:
            self._update_chart(n_frames, n_errors)

    def _update_chart(self, n_frames: int, n_errors: int):
        self._mini_plot.fig.clf()
        ax = self._mini_plot.fig.add_subplot(111)
        ok_rate = max(0, n_frames - n_errors)
        bars = ax.bar(["Valid frames", "CRC errors"],
                      [ok_rate, n_errors],
                      color=[C_OK, C_ERR], width=0.5, edgecolor="none")
        ax.bar_label(bars, fmt="%d", color=C_TEXT, fontsize=10, padding=4)
        ax.set_title("Cumulative frame status")
        ax.set_ylim(0, max(10, n_frames * 1.15))
        ax.grid(axis="y")
        self._mini_plot.refresh()


class DecoderPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._frames_data = []
        self._build()

    def _build(self):
        SectionHeader(self, "ECON-D Frame Decoder").pack(anchor="w", pady=(0, 14))

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        toolbar.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(toolbar, text="Load binary file", width=140,
                      command=self._load_file).pack(side="left", padx=12, pady=10)
        ctk.CTkButton(toolbar, text="Load demo data", width=140,
                      fg_color=C_WARN, hover_color="#d68910", text_color="#000",
                      command=self._load_demo).pack(side="left", pady=10)
        self._file_label = ctk.CTkLabel(toolbar, text="No file loaded",
                                         text_color=C_MUTED, font=ctk.CTkFont(size=11))
        self._file_label.pack(side="left", padx=12)

        # Filter row
        filter_row = ctk.CTkFrame(self, fg_color="transparent")
        filter_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(filter_row, text="Filter chip ID:", text_color=C_MUTED).pack(side="left")
        self._chip_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(filter_row, variable=self._chip_var,
                          values=["All", "0", "1", "2", "3"],
                          command=lambda _: self._refresh_table(),
                          width=80).pack(side="left", padx=8)
        self._crc_only = ctk.CTkCheckBox(filter_row, text="Show CRC errors only",
                                          command=self._refresh_table)
        self._crc_only.pack(side="left", padx=12)

        # Main split
        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=3)
        split.columnconfigure(1, weight=2)

        # Frame table
        table_card = ctk.CTkFrame(split, fg_color=C_CARD, corner_radius=10)
        table_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ctk.CTkLabel(table_card, text="Decoded frames",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self._table = ctk.CTkTextbox(table_card, font=ctk.CTkFont("Consolas", 11),
                                      fg_color="#0d1117", text_color=C_TEXT,
                                      state="disabled", wrap="none")
        self._table.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Hex view
        hex_card = ctk.CTkFrame(split, fg_color=C_CARD, corner_radius=10)
        hex_card.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(hex_card, text="Channel hits",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C_MUTED).pack(anchor="w", padx=12, pady=(10, 4))
        self._hex_view = ctk.CTkTextbox(hex_card, font=ctk.CTkFont("Consolas", 11),
                                         fg_color="#0d1117", text_color=C_TEXT,
                                         state="disabled", wrap="none")
        self._hex_view.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._load_demo()

    def _load_file(self):
        from tkinter.filedialog import askopenfilename
        path = askopenfilename(filetypes=[("Binary files", "*.bin"), ("All", "*.*")])
        if not path:
            return
        sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
        from econ_decoder import EconDecoder
        with open(path, "rb") as f:
            data = f.read()
        decoder = EconDecoder()
        self._frames_data = list(decoder.decode_stream(data))
        self._file_label.configure(text=Path(path).name)
        self._refresh_table()

    def _load_demo(self):
        sys.path.insert(0, str(Path(__file__).parent.parent / "data"))
        sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
        from generate_test_vectors import generate
        from econ_decoder import EconDecoder
        raw = generate(n_events=300, corrupt_rate=0.03)
        decoder = EconDecoder()
        self._frames_data = list(decoder.decode_stream(raw))
        self._file_label.configure(text="[demo] 300 synthetic ECON-D frames  |  "
                                        f"CRC errors: {decoder.n_crc_errors}")
        self._refresh_table()

    def _refresh_table(self):
        chip_filter = self._chip_var.get()
        err_only    = bool(self._crc_only.get())

        lines = [f"{'#':>5}  {'Orbit':>5}  {'BX':>4}  {'Chip':>4}  "
                 f"{'Hits':>4}  {'CRC':>4}"]
        lines.append("-" * 42)

        hits_preview = []
        for i, f in enumerate(self._frames_data):
            if chip_filter != "All" and f.chip_id != int(chip_filter):
                continue
            if err_only and f.crc_ok:
                continue
            crc_label = "OK" if f.crc_ok else "ERR"
            lines.append(f"{i:>5}  {f.orbit:>5}  {f.bx:>4}  "
                         f"{f.chip_id:>4}  {len(f.hits):>4}  {crc_label:>4}")
            if len(hits_preview) < 60 and f.hits:
                hits_preview.append(
                    f"\n-- Frame {i}  BX={f.bx} --"
                )
                for h in f.hits[:8]:
                    hits_preview.append(
                        f"  ch ({h.u:2d},{h.v:2d})  ADC={h.adc:>4}  "
                        f"Q={h.charge_fC:>5.1f}fC  t={h.time_ns:>5.1f}ns"
                    )

        self._write(self._table, "\n".join(lines))
        self._write(self._hex_view, "\n".join(hits_preview))

    def _write(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("end", text)
        widget.configure(state="disabled")


class NoisePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._channels = demo_threshold_scan()
        self._build()

    def _build(self):
        SectionHeader(self, "Noise Analysis  --  HGCROC Threshold Scan").pack(
            anchor="w", pady=(0, 14))

        # Toolbar
        tb = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        tb.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(tb, text="Load CSV", width=120,
                      command=self._load_csv).pack(side="left", padx=12, pady=10)
        ctk.CTkButton(tb, text="Use demo data", width=130,
                      fg_color=C_WARN, hover_color="#d68910", text_color="#000",
                      command=self._use_demo).pack(side="left", pady=10)
        ctk.CTkLabel(tb, text="Channel:", text_color=C_MUTED).pack(side="left", padx=(20, 4))
        self._ch_var = ctk.StringVar(value="0")
        self._ch_menu = ctk.CTkOptionMenu(
            tb, variable=self._ch_var,
            values=[str(i) for i in range(72)],
            command=lambda _: self._plot_scurve(), width=70)
        self._ch_menu.pack(side="left", pady=10)

        # Plots
        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=1)

        self._scurve_plot = EmbeddedPlot(split, figsize=(5.5, 4))
        self._scurve_plot.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        self._hist_plot = EmbeddedPlot(split, figsize=(5.5, 4))
        self._hist_plot.grid(row=0, column=1, sticky="nsew")

        self._use_demo()

    def _load_csv(self):
        from tkinter.filedialog import askopenfilename
        path = askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if path:
            sys.path.insert(0, str(Path(__file__).parent.parent / "analysis"))
            from noise_analysis import load_scan, fit_channel
            scan = load_scan(path)
            self._channels = []
            for ch, (thr, eff) in scan.items():
                fit = fit_channel(thr, eff, ch)
                self._channels.append({
                    "ch": ch, "mu": fit.mu_dac, "sigma": fit.sigma_dac,
                    "thresholds": thr, "eff": eff,
                })
            self._plot_scurve()
            self._plot_histograms()

    def _use_demo(self):
        self._channels = demo_threshold_scan()
        self._plot_scurve()
        self._plot_histograms()

    def _plot_scurve(self):
        ch_idx = int(self._ch_var.get())
        ch = next((c for c in self._channels if c["ch"] == ch_idx), self._channels[0])

        self._scurve_plot.fig.clf()
        ax = self._scurve_plot.fig.add_subplot(111)

        ax.scatter(ch["thresholds"], ch["eff"],
                   color=C_ACCENT, s=22, zorder=3, label="Data")
        x_fit = np.linspace(ch["thresholds"].min(), ch["thresholds"].max(), 200)
        y_fit = _scurve(x_fit, ch["mu"], ch["sigma"])
        ax.plot(x_fit, y_fit, color=C_OK, lw=2, label=f"S-curve fit")
        ax.axvline(ch["mu"], color=C_WARN, ls="--", lw=1.2,
                   label=f"Pedestal = {ch['mu']:.1f} DAC")
        ax.axvspan(ch["mu"] - ch["sigma"], ch["mu"] + ch["sigma"],
                   alpha=0.12, color=C_ACCENT)
        ax.set_xlabel("Threshold (DAC counts)")
        ax.set_ylabel("Hit efficiency")
        ax.set_title(f"S-curve  --  channel {ch_idx}   "
                     f"ENC = {ch['sigma']*3125:.0f} e⁻")
        ax.legend(fontsize=9)
        ax.grid(True)
        ax.set_ylim(-0.05, 1.08)
        self._scurve_plot.refresh()

    def _plot_histograms(self):
        mus    = np.array([c["mu"]    for c in self._channels])
        sigmas = np.array([c["sigma"] for c in self._channels])
        encs   = sigmas * 3125

        self._hist_plot.fig.clf()
        axes = self._hist_plot.fig.subplots(1, 2)

        axes[0].hist(mus, bins=20, color=C_ACCENT, edgecolor="#0d1117", linewidth=0.5)
        axes[0].axvline(mus.mean(), color=C_WARN, ls="--", lw=1.5,
                        label=f"Mean={mus.mean():.1f}")
        axes[0].set_xlabel("Pedestal (DAC)")
        axes[0].set_ylabel("Channels")
        axes[0].set_title("Pedestal spread")
        axes[0].legend(fontsize=8)
        axes[0].grid(True)

        axes[1].hist(encs / 1000, bins=20, color=C_OK, edgecolor="#0d1117", linewidth=0.5)
        axes[1].axvline(encs.mean() / 1000, color=C_WARN, ls="--", lw=1.5,
                        label=f"Mean={encs.mean():.0f} e⁻")
        axes[1].set_xlabel("ENC (ke⁻)")
        axes[1].set_title("Equiv. Noise Charge")
        axes[1].legend(fontsize=8)
        axes[1].grid(True)

        self._hist_plot.refresh()


class OccupancyPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._build()

    def _build(self):
        SectionHeader(self, "Hex-Cell Occupancy Map").pack(anchor="w", pady=(0, 14))

        tb = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        tb.pack(fill="x", pady=(0, 12))
        ctk.CTkButton(tb, text="Regenerate demo", width=160,
                      fg_color=C_WARN, hover_color="#d68910", text_color="#000",
                      command=self._generate).pack(side="left", padx=12, pady=10)
        ctk.CTkLabel(tb, text="Layer:", text_color=C_MUTED).pack(side="left", padx=(16, 4))
        self._layer = ctk.CTkOptionMenu(tb, values=[str(i) for i in range(1, 29)],
                                         width=70, command=lambda _: self._generate())
        self._layer.set("12")
        self._layer.pack(side="left", pady=10)
        ctk.CTkLabel(tb, text="Events:", text_color=C_MUTED).pack(side="left", padx=(16, 4))
        self._nevt = ctk.CTkOptionMenu(
            tb, values=["10 000", "50 000", "100 000"],
            width=100, command=lambda _: self._generate())
        self._nevt.set("50 000")
        self._nevt.pack(side="left", pady=10)

        self._plot = EmbeddedPlot(self, figsize=(7, 5.5))
        self._plot.pack(fill="both", expand=True)
        self._generate()

    def _generate(self):
        n = int(self._nevt.get().replace(" ", ""))
        hits, n_events = demo_occupancy_hits(n)

        from collections import Counter
        counter = Counter(hits)
        occ = {cell: counter.get(cell, 0) / n_events for cell in WAFER_CELLS}

        size = 26
        verts, values = [], []
        for (u, v), rate in occ.items():
            cx, cy = hex_to_pixel(u, v, size)
            verts.append(hex_vertices(cx, cy, size * 0.94))
            values.append(rate)

        values = np.array(values)
        norm   = Normalize(vmin=0, vmax=values.max() * 1.1 or 1)

        self._plot.fig.clf()
        ax = self._plot.fig.add_subplot(111)
        col = PolyCollection(verts, array=values, cmap="plasma",
                             norm=norm, edgecolors="#0d1117", linewidths=0.8)
        ax.add_collection(col)

        # annotate each cell with its (u,v)
        for (u, v) in WAFER_CELLS:
            cx, cy = hex_to_pixel(u, v, size)
            ax.text(cx, cy, f"{u},{v}", ha="center", va="center",
                    fontsize=5.5, color="#ffffff", alpha=0.6)

        ax.set_xlim(-115, 115)
        ax.set_ylim(-115, 115)
        ax.set_aspect("equal")
        ax.set_axis_off()
        cbar = self._plot.fig.colorbar(col, ax=ax, shrink=0.72, pad=0.02)
        cbar.set_label("Hit rate / event")
        ax.set_title(f"HD wafer occupancy  --  layer {self._layer.get()}  "
                     f"({n:,} events)", fontsize=12, pad=12)
        self._plot.refresh()


class BandwidthPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._build()

    def _build(self):
        SectionHeader(self, "lpGBT Bandwidth Budget").pack(anchor="w", pady=(0, 14))

        # Controls
        ctrl = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=10)
        ctrl.pack(fill="x", pady=(0, 12))
        ctrl.columnconfigure((0, 1, 2, 3), weight=1)

        ctk.CTkLabel(ctrl, text="Pile-up (PU)",
                     text_color=C_MUTED).grid(row=0, column=0, padx=16, pady=(12, 2))
        self._pu_val = ctk.CTkLabel(ctrl, text="200",
                                     font=ctk.CTkFont("Consolas", 18, "bold"),
                                     text_color=C_ACCENT)
        self._pu_val.grid(row=1, column=0, padx=16)
        self._pu_slider = ctk.CTkSlider(ctrl, from_=0, to=200, number_of_steps=20,
                                         command=self._on_change)
        self._pu_slider.set(200)
        self._pu_slider.grid(row=2, column=0, padx=16, pady=(2, 14), sticky="ew")

        ctk.CTkLabel(ctrl, text="Threshold (fC)",
                     text_color=C_MUTED).grid(row=0, column=1, padx=16, pady=(12, 2))
        self._thr_val = ctk.CTkLabel(ctrl, text="0.50 fC",
                                      font=ctk.CTkFont("Consolas", 18, "bold"),
                                      text_color=C_ACCENT)
        self._thr_val.grid(row=1, column=1, padx=16)
        self._thr_slider = ctk.CTkSlider(ctrl, from_=0.1, to=8.0, number_of_steps=79,
                                          command=self._on_change)
        self._thr_slider.set(0.5)
        self._thr_slider.grid(row=2, column=1, padx=16, pady=(2, 14), sticky="ew")

        ctk.CTkLabel(ctrl, text="Link util.",
                     text_color=C_MUTED).grid(row=0, column=2, padx=16, pady=(12, 2))
        self._util_val = ctk.CTkLabel(ctrl, text="--",
                                       font=ctk.CTkFont("Consolas", 18, "bold"),
                                       text_color=C_OK)
        self._util_val.grid(row=1, column=2, padx=16, rowspan=2)

        ctk.CTkLabel(ctrl, text="Avg hits / BX",
                     text_color=C_MUTED).grid(row=0, column=3, padx=16, pady=(12, 2))
        self._hits_val = ctk.CTkLabel(ctrl, text="--",
                                       font=ctk.CTkFont("Consolas", 18, "bold"),
                                       text_color=C_WARN)
        self._hits_val.grid(row=1, column=3, padx=16, rowspan=2)

        # Plot
        self._bw_plot = EmbeddedPlot(self, figsize=(8, 4))
        self._bw_plot.pack(fill="both", expand=True)

        self._on_change(None)

    def _utilisation(self, pu: float, thr: float) -> tuple[float, float]:
        n_ch = 144
        occ  = 0.01 * (pu / 200.0) * np.exp(-thr / 1.0)
        hits = occ * n_ch
        bpbx = 72 + hits * 32   # header 72 bits + 32 bits per hit
        util = bpbx / 28        # 28 usable bits/BX on lpGBT
        return util, hits

    def _on_change(self, _):
        pu  = self._pu_slider.get()
        thr = self._thr_slider.get()
        self._pu_val.configure(text=f"{pu:.0f}")
        self._thr_val.configure(text=f"{thr:.2f} fC")

        util, hits = self._utilisation(pu, thr)
        color = C_ERR if util > 1.0 else (C_WARN if util > 0.8 else C_OK)
        self._util_val.configure(text=f"{util*100:.1f}%", text_color=color)
        self._hits_val.configure(text=f"{hits:.1f}")

        # Heatmap: PU x threshold
        pus  = np.arange(0, 210, 10)
        thrs = np.array([0.25, 0.5, 1.0, 2.0, 4.0])

        self._bw_plot.fig.clf()
        ax = self._bw_plot.fig.add_subplot(111)
        for thr_val in thrs:
            utils = [self._utilisation(p, thr_val)[0] * 100 for p in pus]
            lw = 2.5 if abs(thr_val - thr) < 0.05 else 1
            ax.plot(pus, utils, lw=lw, label=f"{thr_val} fC", marker="none")

        ax.axhline(100, color=C_ERR, ls="--", lw=1.2, label="100% (saturation)")
        ax.axhline(80,  color=C_WARN, ls=":",  lw=1.0, label="80% warning")
        ax.axvline(pu,  color="white", ls="-", lw=0.7, alpha=0.4)
        ax.set_xlabel("Pile-up (PU)")
        ax.set_ylabel("lpGBT utilisation (%)")
        ax.set_title("Link utilisation vs pile-up and threshold")
        ax.legend(fontsize=9, title="Threshold", title_fontsize=9)
        ax.grid(True)
        ax.set_xlim(0, 200)
        ax.set_ylim(0, 160)
        self._bw_plot.refresh()


# ── Main window ───────────────────────────────────────────────────────────────

class HGCALLab(ctk.CTk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.title("HGCAL Lab  --  IPE / KIT")
        self.geometry("1280x800")
        self.minsize(1100, 700)
        self.configure(fg_color=C_BG)
        self._demo_running = False
        self._frame_count  = 0
        self._crc_errors   = 0
        self._build_ui()
        self.show_page("dashboard")
        if demo:
            self.after(400, self._start_demo)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0,
                                     fg_color=C_SIDEBAR)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # Logo
        logo = ctk.CTkFrame(self.sidebar, fg_color=C_CARD, corner_radius=10)
        logo.pack(fill="x", padx=12, pady=(18, 6))
        ctk.CTkLabel(logo, text="HGCAL",
                     font=ctk.CTkFont("Consolas", 24, "bold"),
                     text_color=C_ACCENT).pack(pady=(12, 0))
        ctk.CTkLabel(logo, text="Readout Lab",
                     font=ctk.CTkFont(size=11),
                     text_color=C_MUTED).pack(pady=(0, 4))
        ctk.CTkLabel(logo, text="IPE / KIT",
                     font=ctk.CTkFont(size=9),
                     text_color=C_BORDER).pack(pady=(0, 10))

        # Nav
        self._nav_btns: dict[str, ctk.CTkButton] = {}
        nav = [
            ("dashboard",  "■  Dashboard"),
            ("decoder",    "■  Frame Decoder"),
            ("noise",      "■  Noise Analysis"),
            ("occupancy",  "■  Occupancy Map"),
            ("bandwidth",  "■  Bandwidth Budget"),
        ]
        nav_wrap = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        nav_wrap.pack(fill="x", padx=8, pady=6)
        for key, label in nav:
            btn = ctk.CTkButton(
                nav_wrap, text=label, anchor="w",
                fg_color="transparent", hover_color=C_CARD,
                text_color=C_MUTED, font=ctk.CTkFont(size=13),
                height=40, corner_radius=8,
                command=lambda k=key: self.show_page(k),
            )
            btn.pack(fill="x", pady=2)
            self._nav_btns[key] = btn

        # Demo toggle
        demo_card = ctk.CTkFrame(self.sidebar, fg_color=C_CARD, corner_radius=10)
        demo_card.pack(fill="x", padx=12, pady=8)
        ctk.CTkLabel(demo_card, text="Demo Mode",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=C_MUTED).pack(pady=(10, 2))
        self._demo_sw = ctk.CTkSwitch(demo_card, text="",
                                       command=self._toggle_demo,
                                       progress_color=C_ACCENT)
        self._demo_sw.pack(pady=(2, 10))

        # Status
        self._status_lbl = ctk.CTkLabel(
            self.sidebar, text="●  Disconnected",
            text_color=C_ERR, font=ctk.CTkFont(size=11))
        self._status_lbl.pack(side="bottom", pady=10)
        ctk.CTkLabel(self.sidebar, text="v 0.1.0",
                     text_color=C_BORDER,
                     font=ctk.CTkFont(size=10)).pack(side="bottom")

        # Main area
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        self._page_host = ctk.CTkFrame(main, fg_color="transparent")
        self._page_host.pack(fill="both", expand=True, padx=20, pady=20)

        self._pages = {
            "dashboard": DashboardPage(self._page_host, self),
            "decoder":   DecoderPage(self._page_host, self),
            "noise":     NoisePage(self._page_host, self),
            "occupancy": OccupancyPage(self._page_host, self),
            "bandwidth": BandwidthPage(self._page_host, self),
        }

    def show_page(self, name: str):
        for key, btn in self._nav_btns.items():
            active = key == name
            btn.configure(
                fg_color=C_CARD if active else "transparent",
                text_color=C_TEXT if active else C_MUTED,
            )
        for key, page in self._pages.items():
            if key == name:
                page.pack(fill="both", expand=True)
            else:
                page.pack_forget()

    def _toggle_demo(self):
        if self._demo_sw.get():
            self._start_demo()
        else:
            self._demo_running = False
            self._status_lbl.configure(text="●  Disconnected", text_color=C_ERR)

    def _start_demo(self):
        self._demo_sw.select()
        self._demo_running = True
        self._status_lbl.configure(text="●  Demo Mode", text_color=C_WARN)
        threading.Thread(target=self._demo_loop, daemon=True).start()

    def _demo_loop(self):
        rng = np.random.default_rng()
        while self._demo_running:
            self._frame_count += 1
            n_hits = int(rng.poisson(5.2))
            if rng.random() < 0.02:
                self._crc_errors += 1
            bx = self._frame_count % 3564
            try:
                self._pages["dashboard"].update_counters(
                    self._frame_count, self._crc_errors, bx, n_hits)
            except Exception:
                pass
            time.sleep(0.08)

    # ── Screenshot helper ─────────────────────────────────────────────────────

    def take_screenshots(self):
        out = Path(__file__).parent.parent / "screenshots"
        out.mkdir(exist_ok=True)
        pages = ["dashboard", "decoder", "noise", "occupancy", "bandwidth"]
        self._start_demo()
        self.update()
        time.sleep(0.6)

        for name in pages:
            self.show_page(name)
            self.update()
            time.sleep(0.5)
            self.update_idletasks()
            path = out / f"{name}.png"
            # Use PIL to grab the window
            try:
                from PIL import ImageGrab
                x = self.winfo_rootx()
                y = self.winfo_rooty()
                w = self.winfo_width()
                h = self.winfo_height()
                img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                img.save(str(path))
                print(f"  saved {path.name}")
            except Exception as e:
                print(f"  screenshot failed: {e}")

        self._demo_running = False
        self.destroy()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo",       action="store_true")
    parser.add_argument("--screenshot", action="store_true")
    args = parser.parse_args()

    app = HGCALLab(demo=args.demo or args.screenshot)
    if args.screenshot:
        app.after(1200, app.take_screenshots)
    app.mainloop()


if __name__ == "__main__":
    main()
