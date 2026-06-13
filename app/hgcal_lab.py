"""
HGCAL Lab — Desktop analysis application for CMS HGCAL prototype readout.
Decode ECON-D frames, characterise HGCROC noise, map hex-cell occupancy,
estimate lpGBT bandwidth — all without hardware via demo mode.

Usage:
    python app/hgcal_lab.py
    python app/hgcal_lab.py --demo
    python app/hgcal_lab.py --screenshot
"""

from __future__ import annotations
import argparse
import math
import sys
import threading
import time
from collections import deque, Counter
from pathlib import Path

# Resolve analysis/ and data/ from source tree or frozen PyInstaller bundle.
def _setup_paths() -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent  # type: ignore[attr-defined]
    for sub in ("analysis", "data"):
        p = str(base / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    return base

_BASE_DIR = _setup_paths()

import customtkinter as ctk
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.collections import PolyCollection
from matplotlib.colors import Normalize
import numpy as np
from scipy.special import erfc

# ── Palette ──────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

C_BG      = "#0a0e1a"
C_SIDE    = "#0d1220"
C_CARD    = "#141929"
C_CARD2   = "#1a2035"
C_BORDER  = "#252d45"
C_ACCENT  = "#4a90e2"
C_OK      = "#2ecc71"
C_ERR     = "#ff4757"
C_WARN    = "#ffa502"
C_PURPLE  = "#a55eea"
C_TEAL    = "#26de81"
C_TEXT    = "#e8edf8"
C_MUTED   = "#6b7a99"
C_DIM     = "#2a3350"

PAGE_COLORS = {
    "dashboard": C_ACCENT,
    "decoder":   C_PURPLE,
    "noise":     C_TEAL,
    "occupancy": C_WARN,
    "bandwidth": C_OK,
}

matplotlib.rcParams.update({
    "figure.facecolor": C_CARD,
    "axes.facecolor":   "#0d1422",
    "axes.edgecolor":   C_BORDER,
    "text.color":       C_TEXT,
    "axes.labelcolor":  C_TEXT,
    "xtick.color":      C_MUTED,
    "ytick.color":      C_MUTED,
    "grid.color":       C_DIM,
    "grid.alpha":       0.6,
    "axes.titlecolor":  C_TEXT,
    "axes.titlesize":   11,
    "legend.facecolor": C_CARD,
    "legend.edgecolor": C_BORDER,
    "legend.labelcolor": C_TEXT,
    "axes.spines.top":  False,
    "axes.spines.right": False,
})

# ── Geometry ──────────────────────────────────────────────────────────────────
WAFER_CELLS = [(u, v) for u in range(-3, 4) for v in range(-3, 4) if abs(u + v) <= 3]

def hex_vertices(cx: float, cy: float, size: float = 26.0) -> np.ndarray:
    a = np.deg2rad(np.arange(0, 360, 60))
    return np.column_stack([cx + size * np.cos(a), cy + size * np.sin(a)])

def hex_to_pixel(u: int, v: int, size: float = 26.0) -> tuple[float, float]:
    return size * 1.5 * u, size * (math.sqrt(3) / 2 * u + math.sqrt(3) * v)

# ── Demo data generators ──────────────────────────────────────────────────────

def _scurve(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    return 0.5 * erfc((x - mu) / (np.sqrt(2) * sigma))

def demo_threshold_scan(n_ch: int = 72) -> list[dict]:
    rng = np.random.default_rng(7)
    thr = np.linspace(210, 300, 45)
    out = []
    for ch in range(n_ch):
        mu    = rng.normal(252, 4.1)
        sigma = abs(rng.normal(2.5, 0.3))
        eff   = np.clip(_scurve(thr, mu, sigma) + rng.normal(0, 0.005, len(thr)), 0, 1)
        out.append({"ch": ch, "mu": mu, "sigma": sigma, "thr": thr, "eff": eff})
    return out

def demo_occupancy_hits(n_events: int = 50_000, seed: int | None = None) -> list[tuple[int,int]]:
    """seed=None gives a fresh random result on every call — fixing the regenerate bug."""
    rng = np.random.default_rng(seed)
    weights = np.array([np.exp(-(u**2 + v**2) / 3.5) for u, v in WAFER_CELLS])
    weights /= weights.sum()
    idx = rng.choice(len(WAFER_CELLS), size=n_events * 3, p=weights)
    return [WAFER_CELLS[i] for i in idx]

# ── Shared widgets ────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """Metric card with a coloured accent bar at the bottom."""
    def __init__(self, parent, label: str, value: str = "—",
                 accent: str = C_ACCENT, sub: str = "", **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=12, **kw)
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(size=11),
                     text_color=C_MUTED).pack(anchor="w", padx=14, pady=(13, 1))
        self._val = ctk.CTkLabel(self, text=value,
                                  font=ctk.CTkFont("Consolas", 28, "bold"),
                                  text_color=accent)
        self._val.pack(anchor="w", padx=14)
        if sub:
            ctk.CTkLabel(self, text=sub, font=ctk.CTkFont(size=10),
                         text_color=C_DIM).pack(anchor="w", padx=14, pady=(0, 4))
        # coloured accent strip
        ctk.CTkFrame(self, height=3, fg_color=accent, corner_radius=0
                     ).pack(fill="x", side="bottom")

    def set(self, value: str, color: str | None = None):
        kw: dict = {"text": value}
        if color:
            kw["text_color"] = color
        self._val.configure(**kw)


class Plot(ctk.CTkFrame):
    """Thin wrapper around a Matplotlib figure embedded in a CTkFrame card."""
    def __init__(self, parent, figsize=(6, 3.8), **kw):
        super().__init__(parent, fg_color=C_CARD, corner_radius=12, **kw)
        self.fig    = Figure(figsize=figsize, tight_layout=True)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=2, pady=2)

    def clear(self) -> None:
        self.fig.clf()

    def draw(self) -> None:
        self.canvas.draw_idle()


def _toolbar(parent: ctk.CTkFrame) -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, fg_color=C_CARD, corner_radius=12)
    f.pack(fill="x", pady=(0, 10))
    return f

def _btn(parent, text: str, command, color=C_ACCENT, text_color="white", width=140):
    return ctk.CTkButton(parent, text=text, command=command, width=width,
                          fg_color=color, hover_color=color + "cc",
                          text_color=text_color, corner_radius=8)

def _label(parent, text: str, color=C_MUTED, size=11):
    return ctk.CTkLabel(parent, text=text, text_color=color,
                         font=ctk.CTkFont(size=size))

# ── Pages ─────────────────────────────────────────────────────────────────────

class DashboardPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._hit_history: deque[float] = deque(maxlen=80)
        self._err_history: deque[int]   = deque(maxlen=80)
        self._last_crc_count = 0
        self._build()

    def _build(self):
        # Stat cards
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", pady=(0, 12))
        for c in range(4):
            row.columnconfigure(c, weight=1, uniform="c")
        self._c_frames = StatCard(row, "Frames decoded", accent=C_ACCENT,  sub="total")
        self._c_errors = StatCard(row, "CRC errors",     accent=C_ERR,    sub="cumulative")
        self._c_hits   = StatCard(row, "Avg hits / BX",  accent=C_OK,     sub="Poisson mean")
        self._c_rate   = StatCard(row, "Frame rate",     accent=C_PURPLE, sub="frames / s")
        for i, c in enumerate([self._c_frames, self._c_errors, self._c_hits, self._c_rate]):
            c.grid(row=0, column=i, padx=(0,8) if i < 3 else 0, sticky="ew")

        # Bottom: log + rolling chart
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="both", expand=True)
        bot.columnconfigure(0, weight=5)
        bot.columnconfigure(1, weight=3)

        log_card = ctk.CTkFrame(bot, fg_color=C_CARD, corner_radius=12)
        log_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        _label(log_card, "Live event log", color=C_MUTED, size=12).pack(
            anchor="w", padx=14, pady=(12, 4))
        self._log = ctk.CTkTextbox(log_card, font=ctk.CTkFont("Consolas", 11),
                                    fg_color="#080c18", text_color=C_TEXT,
                                    state="disabled", wrap="none")
        self._log.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        # colour tags for OK / ERR lines
        self._log._textbox.tag_configure("ok",  foreground=C_OK)
        self._log._textbox.tag_configure("err", foreground=C_ERR)
        self._log._textbox.tag_configure("dim", foreground=C_MUTED)

        self._chart = Plot(bot, figsize=(4.2, 3.6))
        self._chart.grid(row=0, column=1, sticky="nsew")
        self._draw_idle()

    def _draw_idle(self):
        ax = self._chart.fig.add_subplot(111)
        ax.set_facecolor("#080c18")
        ax.text(0.5, 0.5, "Enable demo\nto stream data", ha="center", va="center",
                color=C_MUTED, fontsize=12, transform=ax.transAxes)
        ax.set_axis_off()
        self._chart.draw()

    def update_live(self, n_frames: int, n_errors: int, bx: int,
                     n_hits: float, fps: float):
        self._c_frames.set(f"{n_frames:,}")
        self._c_errors.set(str(n_errors),
                            color=C_ERR if n_errors else C_OK)
        self._c_hits.set(f"{n_hits:.1f}")
        self._c_rate.set(f"{fps:.1f}")

        new_err = n_errors - self._last_crc_count
        self._last_crc_count = n_errors
        self._hit_history.append(n_hits)
        self._err_history.append(new_err)

        ts  = time.strftime("%H:%M:%S")
        tag = "err" if new_err else ("dim" if n_frames % 5 != 0 else "ok")
        crc = "ERR" if new_err else "OK "
        line = f"[{ts}]  #{n_frames:>6}  bx={bx:04d}  hits={n_hits:>4.0f}  {crc}\n"
        self._log.configure(state="normal")
        self._log._textbox.insert("end", line, tag)
        self._log._textbox.see("end")
        self._log.configure(state="disabled")

        if n_frames % 8 == 0:
            self._redraw_chart()

    def _redraw_chart(self):
        self._chart.clear()
        ax = self._chart.fig.add_subplot(111)
        ax.set_facecolor("#080c18")
        xs = list(range(len(self._hit_history)))
        ys = list(self._hit_history)
        ax.fill_between(xs, ys, alpha=0.18, color=C_ACCENT)
        ax.plot(xs, ys, color=C_ACCENT, lw=1.6)

        err_xs = [i for i, e in enumerate(self._err_history) if e]
        err_ys = [self._hit_history[i] for i in err_xs
                  if i < len(self._hit_history)]
        if err_xs:
            ax.scatter(err_xs, err_ys, color=C_ERR, s=28, zorder=4,
                       label="CRC error")
            ax.legend(fontsize=8, loc="upper left")

        ax.set_xlabel("Recent BXs", fontsize=9)
        ax.set_ylabel("Hits / BX", fontsize=9)
        ax.set_title("Rolling hit rate", fontsize=10)
        ax.set_xlim(0, max(len(xs) - 1, 1))
        ax.set_ylim(0, max(max(ys, default=1) * 1.25, 5))
        ax.grid(True, alpha=0.4)
        self._chart.draw()


class DecoderPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app        = app
        self._frames_data = []
        self._build()

    def _build(self):
        tb = _toolbar(self)
        _btn(tb, "Load binary", self._load_file, C_ACCENT).pack(
            side="left", padx=12, pady=10)
        _btn(tb, "Load demo data", self._load_demo, "#7c3aed").pack(
            side="left", pady=10)
        self._info = _label(tb, "No file loaded")
        self._info.pack(side="left", padx=14)

        flt = ctk.CTkFrame(self, fg_color="transparent")
        flt.pack(fill="x", pady=(0, 8))
        _label(flt, "Chip ID:").pack(side="left")
        self._chip_var = ctk.StringVar(value="All")
        ctk.CTkOptionMenu(flt, variable=self._chip_var, width=80,
                           values=["All","0","1","2","3"],
                           command=lambda _: self._refresh()).pack(side="left", padx=6)
        self._err_only = ctk.CTkCheckBox(flt, text="CRC errors only",
                                          command=self._refresh, text_color=C_TEXT)
        self._err_only.pack(side="left", padx=12)
        self._stats_lbl = _label(flt, "")
        self._stats_lbl.pack(side="right", padx=12)

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=3)
        split.columnconfigure(1, weight=2)

        left = ctk.CTkFrame(split, fg_color=C_CARD, corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        _label(left, "Decoded frames", size=12).pack(anchor="w", padx=14, pady=(12,4))
        self._tbl = ctk.CTkTextbox(left, font=ctk.CTkFont("Consolas", 11),
                                    fg_color="#080c18", text_color=C_TEXT,
                                    state="disabled", wrap="none")
        self._tbl.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self._tbl._textbox.tag_configure("err", foreground=C_ERR)
        self._tbl._textbox.tag_configure("ok",  foreground=C_OK)
        self._tbl._textbox.tag_configure("hdr", foreground=C_MUTED)

        right = ctk.CTkFrame(split, fg_color=C_CARD, corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew")
        _label(right, "Channel hits", size=12).pack(anchor="w", padx=14, pady=(12,4))
        self._hits = ctk.CTkTextbox(right, font=ctk.CTkFont("Consolas", 11),
                                     fg_color="#080c18", text_color=C_TEXT,
                                     state="disabled", wrap="none")
        self._hits.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self._hits._textbox.tag_configure("addr",   foreground=C_ACCENT)
        self._hits._textbox.tag_configure("charge", foreground=C_OK)
        self._hits._textbox.tag_configure("time",   foreground=C_PURPLE)
        self._hits._textbox.tag_configure("hdr",    foreground=C_WARN)

        self._load_demo()

    def _load_file(self):
        from tkinter.filedialog import askopenfilename
        from econ_decoder import EconDecoder
        path = askopenfilename(filetypes=[("Binary","*.bin"),("All","*.*")])
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()
        dec = EconDecoder()
        self._frames_data = list(dec.decode_stream(data))
        self._info.configure(text=Path(path).name)
        self._refresh()

    def _load_demo(self):
        from generate_test_vectors import generate
        from econ_decoder import EconDecoder
        raw = generate(n_events=400, corrupt_rate=0.03)
        dec = EconDecoder()
        self._frames_data = list(dec.decode_stream(raw))
        n_err = dec.n_crc_errors
        self._info.configure(
            text=f"Demo  |  400 frames  |  {n_err} CRC errors ({n_err/4:.1f}%)")
        self._refresh()

    def _refresh(self):
        chip_f   = self._chip_var.get()
        err_only = bool(self._err_only.get())
        visible  = [f for f in self._frames_data
                    if (chip_f == "All" or f.chip_id == int(chip_f))
                    and (not err_only or not f.crc_ok)]

        n_err = sum(1 for f in visible if not f.crc_ok)
        self._stats_lbl.configure(
            text=f"{len(visible)} frames  |  {n_err} errors",
            text_color=C_ERR if n_err else C_MUTED)

        # --- frame table ---
        hdr = f"{'#':>5}  {'BX':>4}  {'Chip':>4}  {'Hits':>4}  {'CRC':>4}\n"
        sep = "─" * 34 + "\n"

        w = self._tbl
        w.configure(state="normal"); w._textbox.delete("1.0","end")
        w._textbox.insert("end", hdr, "hdr")
        w._textbox.insert("end", sep, "hdr")
        for i, fr in enumerate(visible[:500]):
            crc_ok = fr.crc_ok
            tag    = "ok" if crc_ok else "err"
            line   = f"{i:>5}  {fr.bx:>4}  {fr.chip_id:>4}  {len(fr.hits):>4}  "
            crc_s  = "OK " if crc_ok else "ERR"
            w._textbox.insert("end", line)
            w._textbox.insert("end", crc_s + "\n", tag)
        w.configure(state="disabled")

        # --- channel hits ---
        h = self._hits
        h.configure(state="normal"); h._textbox.delete("1.0","end")
        for fr in visible[:25]:
            if not fr.hits:
                continue
            h._textbox.insert("end", f" BX {fr.bx:04d}  chip {fr.chip_id}\n", "hdr")
            for hit in fr.hits[:12]:
                h._textbox.insert("end", f"  ({hit.u:+d},{hit.v:+d})", "addr")
                h._textbox.insert("end", f"  {hit.charge_fC:5.1f} fC", "charge")
                h._textbox.insert("end", f"  {hit.time_ns:5.1f} ns\n", "time")
        h.configure(state="disabled")


class NoisePage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._chs = demo_threshold_scan()
        self._build()

    def _build(self):
        tb = _toolbar(self)
        _btn(tb, "Load CSV",       self._load_csv,  C_ACCENT).pack(side="left", padx=12, pady=10)
        _btn(tb, "Demo data",      self._use_demo,  "#7c3aed").pack(side="left", pady=10)
        _label(tb, "Channel:").pack(side="left", padx=(20,4))
        self._ch_var = ctk.StringVar(value="0")
        ctk.CTkOptionMenu(tb, variable=self._ch_var, width=70,
                           values=[str(i) for i in range(72)],
                           command=lambda _: self._plot_scurve()
                           ).pack(side="left", pady=10)
        self._sum_lbl = _label(tb, "")
        self._sum_lbl.pack(side="right", padx=14)

        split = ctk.CTkFrame(self, fg_color="transparent")
        split.pack(fill="both", expand=True)
        split.columnconfigure(0, weight=1)
        split.columnconfigure(1, weight=1)

        self._p_scurve = Plot(split, figsize=(5.2, 4.2))
        self._p_scurve.grid(row=0, column=0, sticky="nsew", padx=(0,8))
        self._p_hist   = Plot(split, figsize=(5.2, 4.2))
        self._p_hist.grid(row=0, column=1, sticky="nsew")

        # Stats bar
        stats = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=12)
        stats.pack(fill="x", pady=(10, 0))
        for col in range(4):
            stats.columnconfigure(col, weight=1, uniform="s")
        self._s_ped   = StatCard(stats, "Mean pedestal",  accent=C_ACCENT, sub="DAC counts")
        self._s_enc   = StatCard(stats, "Mean ENC",       accent=C_TEAL,   sub="electrons")
        self._s_disp  = StatCard(stats, "Thr. dispersion", accent=C_WARN, sub="fC RMS")
        self._s_dead  = StatCard(stats, "Dead / noisy",   accent=C_ERR,   sub="channels")
        for i, s in enumerate([self._s_ped, self._s_enc, self._s_disp, self._s_dead]):
            s.grid(row=0, column=i, padx=(0,6) if i<3 else 0, pady=8, sticky="ew")

        self._use_demo()

    def _load_csv(self):
        from tkinter.filedialog import askopenfilename
        from noise_analysis import load_scan, fit_channel
        path = askopenfilename(filetypes=[("CSV","*.csv"),("All","*.*")])
        if not path:
            return
        scan = load_scan(path)
        self._chs = []
        for ch, (thr, eff) in scan.items():
            fit = fit_channel(thr, eff, ch)
            self._chs.append({"ch":ch,"mu":fit.mu_dac,"sigma":fit.sigma_dac,
                               "thr":thr,"eff":eff})
        self._refresh_all()

    def _use_demo(self):
        self._chs = demo_threshold_scan()
        self._refresh_all()

    def _refresh_all(self):
        self._plot_scurve()
        self._plot_hists()
        self._update_stats()

    def _update_stats(self):
        mus   = np.array([c["mu"]    for c in self._chs])
        sigs  = np.array([c["sigma"] for c in self._chs])
        encs  = sigs * 3125
        disp  = mus.std() * 0.5
        dead  = int(np.sum(sigs > 5))
        self._s_ped.set(f"{mus.mean():.1f}")
        self._s_enc.set(f"{encs.mean():.0f}")
        self._s_disp.set(f"{disp:.2f}")
        self._s_dead.set(str(dead), color=C_ERR if dead else C_OK)
        self._sum_lbl.configure(
            text=f"{len(self._chs)} channels  |  ENC {encs.mean():.0f} ± {encs.std():.0f} e⁻")

    def _plot_scurve(self):
        ch_idx = int(self._ch_var.get())
        ch = next((c for c in self._chs if c["ch"] == ch_idx), self._chs[0])
        self._p_scurve.clear()
        ax = self._p_scurve.fig.add_subplot(111)
        ax.set_facecolor("#080c18")
        ax.scatter(ch["thr"], ch["eff"], color=C_ACCENT, s=20, zorder=3,
                   label="Measured", alpha=0.85)
        xf = np.linspace(ch["thr"].min(), ch["thr"].max(), 300)
        ax.plot(xf, _scurve(xf, ch["mu"], ch["sigma"]),
                color=C_TEAL, lw=2.2, label="erfc fit")
        ax.axvline(ch["mu"], color=C_WARN, ls="--", lw=1.2,
                   label=f"Pedestal {ch['mu']:.1f}")
        ax.axvspan(ch["mu"]-ch["sigma"], ch["mu"]+ch["sigma"],
                   alpha=0.10, color=C_ACCENT)
        ax.set_xlabel("Threshold (DAC)")
        ax.set_ylabel("Hit efficiency")
        enc = ch["sigma"] * 3125
        ax.set_title(f"S-curve  ch {ch_idx}   ENC = {enc:.0f} e⁻")
        ax.legend(fontsize=9)
        ax.grid(True)
        ax.set_ylim(-0.04, 1.07)
        self._p_scurve.draw()

    def _plot_hists(self):
        mus  = np.array([c["mu"]    for c in self._chs])
        encs = np.array([c["sigma"] for c in self._chs]) * 3125 / 1000
        self._p_hist.clear()
        ax1, ax2 = self._p_hist.fig.subplots(2, 1)
        for ax in (ax1, ax2):
            ax.set_facecolor("#080c18")

        ax1.hist(mus, bins=22, color=C_ACCENT, edgecolor=C_CARD, lw=0.4, alpha=0.9)
        ax1.axvline(mus.mean(), color=C_WARN, ls="--", lw=1.4,
                    label=f"μ = {mus.mean():.1f} DAC")
        ax1.set_xlabel("Pedestal (DAC)")
        ax1.set_ylabel("Channels")
        ax1.set_title("Pedestal spread", fontsize=10)
        ax1.legend(fontsize=8)
        ax1.grid(True)

        ax2.hist(encs, bins=22, color=C_TEAL, edgecolor=C_CARD, lw=0.4, alpha=0.9)
        ax2.axvline(encs.mean(), color=C_WARN, ls="--", lw=1.4,
                    label=f"μ = {encs.mean():.2f} ke⁻")
        ax2.set_xlabel("ENC (ke⁻)")
        ax2.set_ylabel("Channels")
        ax2.set_title("Equiv. Noise Charge", fontsize=10)
        ax2.legend(fontsize=8)
        ax2.grid(True)

        self._p_hist.fig.tight_layout(pad=1.2)
        self._p_hist.draw()


class OccupancyPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._build()

    def _build(self):
        tb = _toolbar(self)
        self._regen_btn = _btn(tb, "Regenerate", self._generate, C_WARN,
                                text_color="#000", width=130)
        self._regen_btn.pack(side="left", padx=12, pady=10)
        _label(tb, "Layer:").pack(side="left", padx=(16, 4))
        self._layer = ctk.CTkOptionMenu(tb, width=70,
                                         values=[str(i) for i in range(1, 48)],
                                         command=self._generate)
        self._layer.set("12")
        self._layer.pack(side="left", pady=10)
        _label(tb, "Events:").pack(side="left", padx=(16, 4))
        self._nevt = ctk.CTkOptionMenu(tb, width=110,
                                        values=["10 000","50 000","200 000"],
                                        command=self._generate)
        self._nevt.set("50 000")
        self._nevt.pack(side="left", pady=10)
        _label(tb, "Colormap:").pack(side="left", padx=(16, 4))
        self._cmap = ctk.CTkOptionMenu(tb, width=110,
                                        values=["plasma","inferno","viridis","magma","hot"],
                                        command=self._generate)
        self._cmap.set("plasma")
        self._cmap.pack(side="left", pady=10)
        self._stat_lbl = _label(tb, "")
        self._stat_lbl.pack(side="right", padx=14)

        self._plot = Plot(self, figsize=(7.5, 5.8))
        self._plot.pack(fill="both", expand=True)
        self._generate()

    def _generate(self, _=None):
        self._regen_btn.configure(state="disabled", text="Working...")
        self.update_idletasks()
        try:
            n        = int(self._nevt.get().replace(" ", ""))
            hits     = demo_occupancy_hits(n)          # no seed → fresh random each call
            counter  = Counter(hits)
            occ      = {cell: counter.get(cell, 0) / n for cell in WAFER_CELLS}
            vals     = np.array(list(occ.values()))
            mean_r   = vals.mean()
            max_r    = vals.max()
            hot      = sum(1 for v in vals if v > mean_r * 2)
            dead     = sum(1 for v in vals if v < mean_r * 0.1)

            size = 28.0
            verts, values = [], []
            for (u, v), rate in occ.items():
                cx, cy = hex_to_pixel(u, v, size)
                verts.append(hex_vertices(cx, cy, size * 0.93))
                values.append(rate)

            norm = Normalize(vmin=0, vmax=max_r * 1.05)

            self._plot.clear()
            ax = self._plot.fig.add_subplot(111)
            ax.set_facecolor("#050810")
            col = PolyCollection(verts, array=np.array(values),
                                  cmap=self._cmap.get(), norm=norm,
                                  edgecolors="#050810", linewidths=1.0)
            ax.add_collection(col)
            for (u, v) in WAFER_CELLS:
                cx, cy = hex_to_pixel(u, v, size)
                ax.text(cx, cy, f"{u},{v}", ha="center", va="center",
                        fontsize=5.8, color="white", alpha=0.55)

            ax.set_xlim(-130, 130); ax.set_ylim(-130, 130)
            ax.set_aspect("equal"); ax.set_axis_off()
            cbar = self._plot.fig.colorbar(col, ax=ax, shrink=0.70, pad=0.01,
                                            label="Hit rate / event")
            cbar.ax.yaxis.label.set_color(C_TEXT)
            cbar.ax.tick_params(colors=C_MUTED)
            layer = self._layer.get()
            ax.set_title(f"HD wafer occupancy  ·  layer {layer}  ·  {n:,} events",
                         fontsize=12, pad=14, color=C_TEXT)
            self._plot.draw()

            self._stat_lbl.configure(
                text=f"mean {mean_r*100:.3f}%  max {max_r*100:.3f}%  "
                     f"hot {hot}  dead {dead}",
                text_color=C_ERR if (hot or dead) else C_MUTED)
        finally:
            self._regen_btn.configure(state="normal", text="Regenerate")


class BandwidthPage(ctk.CTkFrame):
    def __init__(self, parent, app):
        super().__init__(parent, fg_color="transparent")
        self._app = app
        self._build()

    # Fixed model: calibrated so curves span 20–95% across the PU/threshold space.
    # Physical basis: lpGBT 1.28 Gbps / 40 MHz = 32 bits/BX; after FEC & header
    # overhead ~28 usable bits/BX for zero-suppressed hit data + per-frame header
    # amortised over ~10 BXs.
    def _util(self, pu: float, thr: float) -> tuple[float, float]:
        base_occ = 0.007           # hits/channel/BX at PU 200, thr → 0
        occ      = base_occ * (pu / 200.0) * np.exp(-thr / 0.8)
        hits     = occ * 144       # 144 channels per ECON-D
        header_per_bx = 72 / 10   # 72-bit header amortised over 10 BXs
        bits_per_bx   = hits * 32 + header_per_bx
        return bits_per_bx / 32, hits  # 32 usable bits/BX on lpGBT

    def _build(self):
        # Control strip
        ctrl = ctk.CTkFrame(self, fg_color=C_CARD, corner_radius=12)
        ctrl.pack(fill="x", pady=(0, 10))
        for c in range(4):
            ctrl.columnconfigure(c, weight=1)

        for col, (lbl, attr_val, attr_lbl, attr_sl, lo, hi, steps, init) in enumerate([
            ("Pile-up (PU)",      "_pu_val",  "_pu_lbl",  "_pu_sl",    0, 200, 20, 200),
            ("Threshold (fC)",    "_thr_val", "_thr_lbl", "_thr_sl", 0.1, 8.0, 79, 0.5),
        ]):
            _label(ctrl, lbl).grid(row=0, column=col, padx=18, pady=(14,2))
            lobj = ctk.CTkLabel(ctrl, text="—",
                                 font=ctk.CTkFont("Consolas", 20, "bold"),
                                 text_color=C_ACCENT)
            lobj.grid(row=1, column=col, padx=18)
            setattr(self, attr_lbl, lobj)
            sl = ctk.CTkSlider(ctrl, from_=lo, to=hi, number_of_steps=steps,
                                command=self._on_change)
            sl.set(init)
            sl.grid(row=2, column=col, padx=18, pady=(2,14), sticky="ew")
            setattr(self, attr_sl, sl)

        self._util_lbl = ctk.CTkLabel(ctrl, text="—",
                                       font=ctk.CTkFont("Consolas", 20, "bold"),
                                       text_color=C_OK)
        _label(ctrl, "Link utilisation").grid(row=0, column=2, padx=18, pady=(14,2))
        self._util_lbl.grid(row=1, column=2, padx=18, rowspan=2)

        self._hits_lbl = ctk.CTkLabel(ctrl, text="—",
                                       font=ctk.CTkFont("Consolas", 20, "bold"),
                                       text_color=C_WARN)
        _label(ctrl, "Avg hits / BX").grid(row=0, column=3, padx=18, pady=(14,2))
        self._hits_lbl.grid(row=1, column=3, padx=18, rowspan=2)

        self._bw_plot = Plot(self, figsize=(8.5, 4.2))
        self._bw_plot.pack(fill="both", expand=True)
        self._on_change(None)

    def _on_change(self, _):
        pu  = self._pu_sl.get()
        thr = self._thr_sl.get()
        self._pu_lbl.configure(text=f"{pu:.0f}")
        self._thr_lbl.configure(text=f"{thr:.2f} fC")

        util, hits = self._util(pu, thr)
        col = C_ERR if util > 0.9 else (C_WARN if util > 0.7 else C_OK)
        self._util_lbl.configure(text=f"{util*100:.1f}%", text_color=col)
        self._hits_lbl.configure(text=f"{hits:.3f}")

        pus   = np.linspace(0, 200, 60)
        thrs  = [0.25, 0.5, 1.0, 2.0, 4.0]
        clrs  = [C_ERR, C_WARN, C_ACCENT, C_TEAL, C_OK]

        self._bw_plot.clear()
        ax = self._bw_plot.fig.add_subplot(111)
        ax.set_facecolor("#080c18")

        for thr_i, (thr_v, clr) in enumerate(zip(thrs, clrs)):
            utils = [self._util(p, thr_v)[0] * 100 for p in pus]
            active = abs(thr_v - thr) < 0.15
            ax.plot(pus, utils, color=clr, lw=2.6 if active else 1.2,
                    alpha=1.0 if active else 0.55,
                    label=f"{thr_v} fC")
            if active:
                ax.fill_between(pus, utils, alpha=0.08, color=clr)

        ax.axhline(90, color=C_ERR,  ls="--", lw=1.0, alpha=0.7, label="90% limit")
        ax.axhline(70, color=C_WARN, ls=":",  lw=1.0, alpha=0.7, label="70% target")
        ax.axvline(pu, color="white", ls="-", lw=0.8, alpha=0.3)
        ax.scatter([pu], [util * 100], color=col, s=70, zorder=5)

        ax.set_xlabel("Pile-up (PU)")
        ax.set_ylabel("lpGBT utilisation (%)")
        ax.set_title("Link utilisation vs pile-up  ·  1.28 Gbps lpGBT uplink")
        ax.legend(fontsize=9, title="ZS threshold", title_fontsize=9,
                  loc="upper left", ncol=2)
        ax.grid(True, alpha=0.35)
        ax.set_xlim(0, 200)
        ax.set_ylim(0, 105)
        self._bw_plot.draw()


# ── Main window ────────────────────────────────────────────────────────────────

class HGCALLab(ctk.CTk):
    def __init__(self, demo: bool = False):
        super().__init__()
        self.title("HGCAL Lab  v0.1")
        self.geometry("1300x820")
        self.minsize(1100, 700)
        self.configure(fg_color=C_BG)
        self._demo_running = False
        self._n_frames = 0
        self._n_errors = 0
        self._t_start  = time.monotonic()
        self._build_ui()
        self.show_page("dashboard")
        self._bind_keys()
        if demo:
            self.after(500, self._start_demo)

    def _build_ui(self):
        # ── Sidebar ───────────────────────────────────────────────────────────
        sb = ctk.CTkFrame(self, width=216, corner_radius=0, fg_color=C_SIDE)
        sb.pack(side="left", fill="y")
        sb.pack_propagate(False)

        logo = ctk.CTkFrame(sb, fg_color=C_CARD, corner_radius=12)
        logo.pack(fill="x", padx=12, pady=(18, 8))
        ctk.CTkLabel(logo, text="HGCAL",
                     font=ctk.CTkFont("Consolas", 26, "bold"),
                     text_color=C_ACCENT).pack(pady=(14, 0))
        ctk.CTkLabel(logo, text="Readout Lab",
                     font=ctk.CTkFont(size=11),
                     text_color=C_MUTED).pack(pady=(2, 14))

        self._nav_btns: dict[str, ctk.CTkButton] = {}
        pages = [
            ("dashboard", "  Dashboard"),
            ("decoder",   "  Frame Decoder"),
            ("noise",     "  Noise Analysis"),
            ("occupancy", "  Occupancy Map"),
            ("bandwidth", "  Bandwidth Budget"),
        ]
        nav = ctk.CTkFrame(sb, fg_color="transparent")
        nav.pack(fill="x", padx=8, pady=4)
        for key, label in pages:
            b = ctk.CTkButton(
                nav, text=label, anchor="w",
                fg_color="transparent", hover_color=C_CARD2,
                text_color=C_MUTED, font=ctk.CTkFont(size=13),
                height=42, corner_radius=9,
                command=lambda k=key: self.show_page(k),
            )
            b.pack(fill="x", pady=2)
            self._nav_btns[key] = b

        # Demo mode toggle
        demo_f = ctk.CTkFrame(sb, fg_color=C_CARD, corner_radius=12)
        demo_f.pack(fill="x", padx=12, pady=8)
        _label(demo_f, "Demo Mode", size=12).pack(pady=(12, 2))
        self._demo_sw = ctk.CTkSwitch(demo_f, text="",
                                       command=self._toggle_demo,
                                       progress_color=C_ACCENT)
        self._demo_sw.pack(pady=(2, 12))

        self._status_lbl = ctk.CTkLabel(
            sb, text="●  Disconnected", text_color=C_ERR,
            font=ctk.CTkFont(size=11))
        self._status_lbl.pack(side="bottom", pady=10)
        ctk.CTkLabel(sb, text="v 0.1.0", text_color=C_DIM,
                     font=ctk.CTkFont(size=10)).pack(side="bottom")

        # ── Main area ─────────────────────────────────────────────────────────
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        # Thin page-accent strip at the very top
        self._accent_bar = ctk.CTkFrame(main, height=3, fg_color=C_ACCENT,
                                         corner_radius=0)
        self._accent_bar.pack(fill="x")

        host = ctk.CTkFrame(main, fg_color="transparent")
        host.pack(fill="both", expand=True, padx=22, pady=18)

        self._pages = {
            "dashboard": DashboardPage(host, self),
            "decoder":   DecoderPage(host, self),
            "noise":     NoisePage(host, self),
            "occupancy": OccupancyPage(host, self),
            "bandwidth": BandwidthPage(host, self),
        }

    def _bind_keys(self):
        shortcuts = {"1":"dashboard","2":"decoder","3":"noise",
                     "4":"occupancy","5":"bandwidth"}
        for key, page in shortcuts.items():
            self.bind(f"<KeyPress-{key}>", lambda e, p=page: self.show_page(p))
        self.bind("<Control-d>", lambda _: self._toggle_demo())

    def show_page(self, name: str):
        color = PAGE_COLORS.get(name, C_ACCENT)
        self._accent_bar.configure(fg_color=color)
        for key, btn in self._nav_btns.items():
            active = key == name
            btn.configure(
                fg_color=C_CARD2 if active else "transparent",
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
        self._t_start = time.monotonic()
        self._n_frames = 0
        self._n_errors = 0
        self._status_lbl.configure(text="●  Streaming", text_color=C_OK)
        threading.Thread(target=self._demo_loop, daemon=True).start()

    def _demo_loop(self):
        rng = np.random.default_rng()
        while self._demo_running:
            self._n_frames += 1
            n_hits = float(rng.poisson(5.2))
            if rng.random() < 0.018:
                self._n_errors += 1
            bx  = self._n_frames % 3564
            fps = self._n_frames / max(time.monotonic() - self._t_start, 1e-9)
            try:
                self._pages["dashboard"].update_live(
                    self._n_frames, self._n_errors, bx, n_hits, fps)
            except Exception:
                pass
            time.sleep(0.06)

    # ── Screenshot helper ─────────────────────────────────────────────────────
    def take_screenshots(self):
        out = Path(__file__).parent.parent / "screenshots"
        out.mkdir(exist_ok=True)
        self._start_demo()
        self.update()
        time.sleep(1.0)
        for name in ["dashboard", "decoder", "noise", "occupancy", "bandwidth"]:
            self.show_page(name)
            self.update()
            time.sleep(0.6)
            self.update_idletasks()
            try:
                from PIL import ImageGrab
                x, y = self.winfo_rootx(), self.winfo_rooty()
                w, h = self.winfo_width(), self.winfo_height()
                ImageGrab.grab((x, y, x+w, y+h)).save(str(out / f"{name}.png"))
                print(f"  saved {name}.png")
            except Exception as e:
                print(f"  {name}: {e}")
        self._demo_running = False
        self.destroy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo",       action="store_true")
    ap.add_argument("--screenshot", action="store_true")
    args = ap.parse_args()
    app  = HGCALLab(demo=args.demo or args.screenshot)
    if args.screenshot:
        app.after(1500, app.take_screenshots)
    app.mainloop()


if __name__ == "__main__":
    main()
