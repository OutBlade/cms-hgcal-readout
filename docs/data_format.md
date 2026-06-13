# ECON-D / ECON-T Data Format Reference

## ECON-D Frame Format

Frames are transmitted over the lpGBT uplink at 40 MHz.
Each frame is byte-aligned and consists of:

```
Byte offset  Width  Field
──────────── ──────────────────────────────────────────────────
0            1      Sync byte: 0xAC
1            1      Orbit number [7:0]  (low 8 bits of 32-bit orbit)
2–3          2      BX counter [15:0]   (bunch crossing, 0–3563)
4            1      N_hits [7:0]        (number of channel words)
5            1      Chip ID [7:0]       (ECON-D identifier on the module)
6            1      Reserved (0x00)
7            1      Header CRC-8/CCITT  (over bytes 0–6)
8..8+4N-1    4×N   Channel words       (N = N_hits)
8+4N         1      Frame CRC-8/CCITT  (over entire frame excluding this byte)
```

### Channel Word (32 bits, MSB first)

```
Bits    Width  Field
─────── ─────────────────────────────────────────────────────────
[31:24]   8   Channel address: u[7:4] | v[3:0]  (hex cell coords)
[23:12]  12   ADC value (12-bit, linear, ~80 fC full scale)
[11]      1   ToT flag (1 = Time-over-Threshold mode active)
[10]      1   Overflow flag (ADC saturated)
[ 9: 8]   2   Reserved
[ 7: 0]   8   ToA (Time of Arrival, 25 ns / 256 ≈ 97 ps LSB)
```

### Charge Conversion

```
Q [fC] = ADC × 80 / 4096
Q [e⁻] = Q [fC] × 6250  (1 fC = 6250 e⁻)
```

### CRC Polynomial

CRC-8/CCITT: x⁸ + x² + x¹ + x⁰  (0x07, no reflection, init=0x00)

---

## ECON-T Trigger Primitive Word (37 bits)

```
Bits      Width  Field
───────── ─────────────────────────────────────────────────────────
[36:27]    10   Energy sum E_T (0.5 GeV LSB, range 0–511.5 GeV)
[26:22]     5   Centroid u (signed 5-bit, range -16 to +15)
[21:17]     5   Centroid v (signed 5-bit, range -16 to +15)
[16:13]     4   Bunch crossing modulo 16
[12: 8]     5   Trigger cell address (within trigger tower)
[ 7: 4]     4   Module ID
[ 3: 0]     4   CRC-4/ITU (over upper 33 bits)
```

Centroid encoding: u/v are unsigned 5-bit values where ≥ 16 represents
negative numbers (i.e., u_signed = u_raw - 32 if u_raw >= 16 else u_raw,
equivalently a 5-bit two's complement interpretation would work too but
the CMS convention uses offset binary to avoid sign-extension ambiguity
across firmware versions).

### CRC-4/ITU Polynomial

x⁴ + x¹ + x⁰  (0x03), computed over the 33 most-significant bits of the
37-bit word (bits [36:4]).

---

## lpGBT Uplink Frame (32 bits @ 40 MHz)

```
Bits      Field
───────── ──────────────────────────────────────────────
[31:28]   Header nibble: 0xA (1010) for data frames
                         0x5 (0101) for idle frames
[27: 0]   28-bit user payload (ECON-D or ECON-T data)
```

Effective user bandwidth: 28 bits × 40 MHz = 1.12 Gbps out of 1.28 Gbps raw.
The remaining 0.16 Gbps carries the header, FEC overhead, and slow-control.
