# HGCAL Detector and Electronics Architecture

## Overview

The CMS High Granularity Calorimeter (HGCAL) replaces the existing endcap
electromagnetic and hadronic calorimeters for the HL-LHC Phase-2 upgrade,
scheduled to begin operation ~2029.

### Why high granularity?

At 200 pile-up interactions per bunch crossing, conventional calorimeters lose
the ability to resolve individual showers. The HGCAL solves this with:
- ~6 million individual readout channels
- 47 longitudinal layers (Ce-E: 26 silicon, Ce-H: 21 silicon + scintillator)
- Hexagonal cell geometry (0.5 cm² and 1.1 cm² cells)
- Timing resolution < 50 ps per hit (silicon) enabling 4D shower reconstruction

---

## Electronics Chain

```
                    ┌─────────────────────────────────────────────────────┐
                    │                  DETECTOR MODULE                    │
  Si/Sc cell  ──►  │  HGCROC (×2)  ──►  ECON-D / ECON-T               │
  (72 ch each)     └────────────────────────────┬────────────────────────┘
                                                 │  lpGBT optical link
                                                 │  1.28 Gbps uplink
                                                 ▼
                   ┌─────────────────────────────────────────────────────┐
                   │              BACKEND (SERENITY / FC7)               │
                   │   Xilinx Virtex UltraScale+  ──► DAQ / Trigger     │
                   └─────────────────────────────────────────────────────┘
```

### HGCROC

The HGCROC (High Granularity Calorimeter ReadOut Chip) is a 72-channel ASIC
designed in 130 nm CMOS technology. Key features:
- Shaping amplifier (CR-RC², peaking time ~25 ns)
- 12-bit ADC for low occupancy channels
- Time-over-Threshold (ToT) mode for high-charge channels
- Time-of-Arrival (ToA) measurement with 25 ps binning
- Autonomous zero-suppression with programmable threshold

### ECON-D (Data Concentrator)

The ECON-D aggregates data from two HGCROCs (144 channels) and formats it for
the lpGBT uplink:
- Accepts 36-bit HGCROC output words at 40 MHz
- Applies additional zero-suppression
- Formats channel hits into 32-bit words with 8-byte frame header
- CRC-8/CCITT frame integrity check
- Maximum output: ~144 channel words + overhead per BX

### ECON-T (Trigger Concentrator)

The ECON-T processes the same 144 channels and computes coarse energy sums
(trigger primitives) at 40 MHz for the Level-1 trigger path:
- Sums charge over programmable trigger cells (groups of ~3 channels)
- Outputs 37-bit trigger primitive words including centroid position
- Latency: < 12.5 µs (L1 budget)

### lpGBT

The Low Power GigaBit Transceiver (lpGBT) is a radiation-tolerant ASIC
(65 nm CMOS) managing the optical link between detector modules and the
counting room:
- Downlink: 2.56 Gbps (clock, configuration, slow-control)
- Uplink: 1.28 Gbps (data + trigger)
- FEC: Reed-Solomon or PRBS-based
- Total data bandwidth per module: ~1.28 Gbps

---

## Data Rates

| Level | Rate | Mechanism |
|---|---|---|
| HGCROC output | ~36 Gbps/module | Raw ADC, all channels |
| After ECON-D ZS | ~1.28 Gbps/module | Zero-suppressed |
| After L1 accept (3.5 kHz) | ~36 Gbps/module | Full readout |
| Total HGCAL | ~10 Tbps (raw) → ~1 Tbps (ZS) | — |

---

## Prototype Testing at IPE / KIT

The IPE group operates bench test stands for module qualification before
installation at DESY/CERN. A typical qualification run:

1. **Threshold scan** -- sweep HGCROC internal DAC, measure hit rate per channel
   -> extract pedestal and ENC (this toolkit: `noise_analysis.py`)
2. **Gain scan** -- inject known charge via internal CalPulse, verify ADC linearity
3. **Timing scan** -- vary injection delay, fit S-curve for ToA calibration
4. **Occupancy check** -- verify no dead/hot channels with cosmics or lab source
   -> visualise with `occupancy_map.py`
5. **Link integrity** -- run extended PRBS capture through ECON-D chain, count CRC errors
   -> decode with `econ_decoder.py`

---

## References

- CMS Phase-2 HGCAL TDR: CERN-LHCC-2017-023
- HGCROC v3 manual: CMS internal
- lpGBT manual: CERN-ACC-2019-0054
- ECON-D specification: CMS HGCAL DPG TWiki (internal)
