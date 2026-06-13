# CMS HGCAL Prototype Readout Analysis

A Python toolkit for decoding, validating, and analyzing data from **CMS High Granularity Calorimeter (HGCAL)** prototype modules — targeting the ECON-D/ECON-T data concentrator chain and FPGA-based readout boards used at the Institute for Data Processing and Electronics (IPE), KIT.

---

## Motivation

The High-Luminosity LHC upgrade replaces the CMS endcap calorimeters with the HGCAL: ~6 million silicon channels arranged in hexagonal cells across 47 longitudinal layers. Reading out this detector requires a multi-stage electronics chain:

```
Si/Sc detector cell
      |
   HGCROC          ← 72-channel ASIC (shaping, ADC, ToT/ToA)
      |
   ECON-D / ECON-T ← data & trigger concentrators
      |  (lpGBT @ 1.28 Gbps)
   SERENITY/FC7    ← FPGA readout card (Virtex UltraScale+)
      |
   DAQ back-end
```

Validating this chain on the bench -- parsing raw frames, checking CRCs, mapping channel IDs to hexagonal geometry, and characterizing noise -- is the bottleneck that slows module qualification. This toolkit automates it.

---

## Repository Structure

```
cms-hgcal-readout/
├── analysis/
│   ├── econ_decoder.py          ← ECON-D frame parser (32-bit words → channel hits)
│   ├── trigger_primitive.py     ← ECON-T 37-bit trigger primitive decoder
│   ├── noise_analysis.py        ← Pedestal, ENC, threshold scan analysis
│   ├── occupancy_map.py         ← Hexagonal cell occupancy visualiser
│   ├── lpgbt_frame.py           ← lpGBT uplink frame format helpers
│   └── bandwidth_budget.py      ← Link utilisation estimator
├── firmware/
│   ├── rtl/
│   │   ├── lpgbt_rx.vhd         ← lpGBT receiver state machine (VHDL)
│   │   └── econ_frame_check.vhd ← CRC-8/CCITT checker
│   └── sim/
│       └── tb_lpgbt_rx.vhd      ← Self-checking testbench
├── data/
│   └── generate_test_vectors.py ← Produces synthetic ECON-D frames for CI
├── notebooks/
│   └── prototype_analysis.ipynb ← End-to-end analysis walkthrough
├── docs/
│   ├── hgcal_architecture.md    ← Detector and electronics overview
│   └── data_format.md           ← ECON-D/T frame format reference
├── tests/
│   ├── test_econ_decoder.py
│   ├── test_trigger_primitive.py
│   └── test_crc.py
├── .github/workflows/
│   └── ci.yml
├── requirements.txt
└── setup.py
```

---

## Key Features

### ECON-D Frame Decoder
Parses the ECON-D output data format (64-bit header + variable-length payload) into structured hit records:
- CRC-8/CCITT integrity check on every frame
- Automatic detection of header corruption / orbit-sync loss
- Channel ID → (u, v, layer) hexagonal coordinate mapping

### ECON-T Trigger Primitive Decoder
Decodes the 37-bit trigger sum words sent to the Level-1 trigger:
- Energy sum (E_T) in trigger tower granularity
- Mean position (centroid u, v)
- Bunch-crossing tagging

### Noise Characterisation
Given a threshold-scan dataset (N_hits vs threshold per channel):
- S-curve fit (complementary error function) per channel
- Extracts: pedestal mu, noise sigma (ENC), and threshold dispersion
- Flags dead / noisy channels automatically

| Metric | Typical HGCROC value | Tool output |
|---|---|---|
| Pedestal | ~250 ADC counts | Mean ± std per channel |
| ENC (Si) | ~1500 e⁻ | Sigma from S-curve fit |
| ENC (Sc) | ~2000 e⁻ | Sigma from S-curve fit |
| Threshold dispersion | < 0.5 fC | RMS across 72 ch |

### Occupancy Maps
Renders hit-rate maps on the actual HGCAL hexagonal wafer geometry using axial hex coordinates (u, v):

```
Occupancy at 1 × MIP threshold, layer 12 — 100k events
        ·  ·  ·  ·
      ·  ■  ·  ■  ·
    ·  ■  ■  ■  ■  ·
      ·  ■  ■  ■  ·
        ·  ·  ·  ·
```

### Bandwidth Budget Calculator
Estimates lpGBT link utilisation as a function of pile-up (PU) and zero-suppression threshold -- critical for demonstrating the readout chain can sustain HL-LHC rates (PU 200, 40 MHz bunch crossing).

---

## Quick Start

```bash
git clone https://github.com/OutBlade/cms-hgcal-readout
cd cms-hgcal-readout
pip install -r requirements.txt

# Generate synthetic test data
python data/generate_test_vectors.py --n-events 1000 --output data/test_run.bin

# Decode and inspect
python analysis/econ_decoder.py data/test_run.bin --summary

# Run noise analysis on a threshold scan CSV
python analysis/noise_analysis.py data/threshold_scan_example.csv --plot

# Launch the notebook
jupyter notebook notebooks/prototype_analysis.ipynb
```

---

## FPGA Firmware

The `firmware/rtl/` directory contains synthesisable VHDL for the FPGA readout side:

- **`lpgbt_rx.vhd`** -- 1.28 Gbps lpGBT uplink receiver: comma detection, frame alignment, FEC decoding stub, and 32-bit word extraction.
- **`econ_frame_check.vhd`** -- CRC-8/CCITT pipeline checker; asserts `frame_err` if the received CRC does not match the computed value within the same clock cycle as the last data byte.

Simulation targets use GHDL (open-source VHDL simulator) and are integrated into CI:

```bash
cd firmware/sim
ghdl -a ../rtl/lpgbt_rx.vhd tb_lpgbt_rx.vhd
ghdl -r tb_lpgbt_rx --wave=tb.ghw
```

---

## Testing

```bash
pytest tests/ -v
```

All tests are data-driven: `generate_test_vectors.py` produces known-good and known-bad frames so the decoder round-trip is verified end-to-end.

---

## Physics Context

The HGCAL will operate at instantaneous luminosity 5 × 10³⁴ cm⁻² s⁻¹ with up to 200 simultaneous pp interactions per bunch crossing. The readout challenge:

- ~6 × 10⁶ channels → O(10 Tbps) raw data rate
- Trigger latency budget: 12.5 µs (L1 accept)
- Selective readout: only ~1% of channels above threshold per event

This toolkit helps measure how close bench prototypes come to meeting those targets before integration into the full system test at DESY and CERN.

---

## Requirements

- Python >= 3.11
- numpy, scipy, matplotlib, uproot, awkward, tqdm
- (optional) ROOT / PyROOT for `.root` file input
- (optional) GHDL >= 3.0 for firmware simulation

---

## References

1. CMS Collaboration, *The Phase-2 Upgrade of the CMS Endcap Calorimeter*, CERN-LHCC-2017-023.
2. Frontend Electronics Overview, CMS HGCAL TWiki (internal).
3. Moreira et al., *The lpGBT: a radiation tolerant ASIC for data, timing, trigger and control applications*, TWEPP 2019.
4. Zabi et al., *The CMS Level-1 Trigger Endcap Calorimeter Upgrade*, JINST 2021.

---

## License

MIT — see [LICENSE](LICENSE).

> Developed as part of a student research project at KIT, in the context of the IPE/EPS HGCAL readout activities. Contact: barbarakallfelz94@gmail.com
