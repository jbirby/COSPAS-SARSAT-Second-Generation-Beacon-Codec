# T.018 Reference Vectors — M1 Spec Harvest

**Source:** C/S T.018, Issue 1 Revision 7, March 2021 (approved by CSC-64).
**Companion:** C/S T.021, Preliminary Issue A, June 2018 (type-approval standard).

All values below are quoted verbatim from the spec; this document is the authoritative input for the sgb-codec implementation.

---

## 1. BCH(250,202) error-correcting code (Appendix B.1)

Shortened form of a (255,207) Bose-Chaudhuri-Hocquenghem code over GF(2). Corrects up to 6 bit errors in the 250-bit pattern.

### Minimal polynomials

```
m1(X)  = X^8 + X^4 + X^3 + X^2 + 1
m3(X)  = X^8 + X^6 + X^5 + X^4 + X^2 + X + 1
m5(X)  = X^8 + X^7 + X^6 + X^5 + X^4 + X + 1
m7(X)  = X^8 + X^6 + X^5 + X^3 + 1
m9(X)  = X^8 + X^7 + X^5 + X^4 + X^3 + X^2 + 1
m11(X) = X^8 + X^7 + X^6 + X^5 + X^2 + X + 1
```

### Generator polynomial

```
g(X) = LCM(m1, m3, m5, m7, m9, m11)
     = X^48 + X^47 + X^46 + X^42 + X^41 + X^40 + X^39 + X^38 + X^37
       + X^35 + X^33 + X^32 + X^31
       + X^26 + X^24 + X^23 + X^22 + X^20 + X^19 + X^18 + X^17 + X^16
       + X^13 + X^12 + X^11 + X^10
       + X^7 + X^4 + X^2 + X + 1
```

49-bit binary representation (leftmost = X^48, rightmost = X^0):

```
1110001111110101110000101110111110011110010010111
```

### Encoding procedure

1. Form the 202-bit information polynomial `m(X) = b1·X^201 + b2·X^200 + … + b202`.
2. Prepend 5 zero bits (to restore the (255,207) framing; padding zeros do not change the output).
3. Right-shift m(X) by 48 bits (i.e. append 48 zero bits as LSBs).
4. Divide the resulting bit string by g(X) modulo 2 (long division, no borrow).
5. The 48-bit remainder r(X) is the BCH parity, appended as bits 203–250.

### Canonical test vector (Appendix B.1)

Main-field inputs:

| Field | Decimal | Binary | Bits |
|---|---|---|---|
| TAC number | 230 | 0000000011100110 | 1–16 |
| Serial number | 573 | 00001000111101 | 17–30 |
| Country code | 201 | 0011001001 | 31–40 |
| Status of homing device | 1 | 1 | 41 |
| RLS function | 0 | 0 | 42 |
| Test protocol | 0 | 0 | 43 |
| Encoded GNSS location (48.79315°N, 69.00876°E) | — | `0 0110000 110010110000110 0 01000101 000000100011111` | 44–90 |
| Vessel ID | 0 | 47 bits all 0 | 91–137 |
| Beacon Type | 0 | 000 | 138–140 |
| Spare bits | 16383 | 11111111111111 | 141–154 |

Rotating Field 0 (G.008 Objective Requirements) inputs:

| Field | Decimal | Binary | Bits |
|---|---|---|---|
| Rotating Field Identifier | 0 | 0000 | 155–158 |
| Elapsed Time since activation | 1 h 27 min | 000001 | 159–164 |
| Time from last encoded location | 6 min 24 s | 00000000110 | 165–175 |
| Altitude of encoded location | 430.24 m | 0000110100 | 176–185 |
| Dilution of precision | HDOP<1, VDOP<2 | 00000001 | 186–193 |
| Activation notification | Manual | 00 | 194–195 |
| Remaining battery capacity | >75% | 101 | 196–198 |
| GNSS status | 3D | 10 | 199–200 |
| Spare bits | 0 | 00 | 201–202 |

Full 202-bit message (hex, as transmitted):

```
00E608F4C986196188A047C000000000000FFFC0100C1A00960
```

Ground-segment representation (two leading `0` bits + bits 1–202):

```
0039823D32618658622811F0000000000003FFF004030680258
```

Computed 48-bit BCH parity (remainder):

```
010010010010101001001111110001010111101001001001
```

---

## 2. PRN spreading LFSR (Section 2.2.3, Table 2.2, Appendix D)

### Generator polynomial

```
G(x) = X^23 + X^18 + 1
```

### Topology

23-bit shift register, registers labelled 22..0. Output is taken from register 0. Feedback: register 0 XOR register 18 → goes into register 22 on each shift. Period = 2^23 − 1 = 8,388,607 chips; 38,400 chips are consumed per burst, leaving 218 possible non-overlapping segment pairs.

### Initialization values and first-64-chip ground truth

| Mode | Channel | Initial state (reg 22..0) | First 64 chips (hex, leftmost first) |
|---|---|---|---|
| Normal | I | `00000000000000000000001` | `8000 0108 4212 84A1` |
| Normal | Q | `00110101100000111111100` | `3F83 58BA D030 F231` |
| Self-Test | I | `10100101100100111110000` | `0F93 4A4D 4CF3 028D` |
| Self-Test | Q | `01111001110100100101000` | `1497 3DC7 16CD E124` |

Appendix D gives a cycle-by-cycle trace for Normal I from initial state `000…001` confirming the `8000 0108 4212 84A1` output — this is the primary unit test for `sgb_prn.py`.

### Bit-to-PRN mapping (Table 2.4 + Table 2.3)

| Data bit | PRN sequence applied | Signal level |
|---|---|---|
| 0 | Non-inverted | +1.0 |
| 1 | Inverted (XOR with all-1s) | −1.0 |

---

## 3. DSSS-OQPSK signal parameters (Section 2.2, 2.3)

| Parameter | Value |
|---|---|
| Chip rate (average) | 38,400 ± 0.6 chips/s |
| Chip rate variation | ± 0.6 chips/s² |
| Chips per bit (per channel I or Q) | 256 |
| Effective chips per bit (I+Q combined) | 128 |
| Information bit rate | 300 bit/s (150 bit/s on each of I, Q) |
| I/Q offset | ½-chip period, I leading Q (± 1% tolerance over burst) |
| I/Q amplitude balance | within 15% peak-to-peak over burst |
| EVM | < 15% over any 150 ms window |
| Burst duration | 1000 ms ± 1 ms (at 90% power points) |
| Preamble duration | 166.7 ms = 6400 chips |
| Useful message duration | 673.3 ms |
| BCH parity duration | 160 ms |
| Modulation | OQPSK |
| RF carrier (real beacon) | 406.05 MHz |
| Rise/fall time | < 0.5 ms between 10% and 90% power points |
| Preamble I/Q content | All bits = 0 (PRN transmitted uninverted) |

### Pulse shaping — important correction vs. project brief

The spec does **not** mandate root-raised-cosine. Section 2.3.2 states:

> Acceptable types of output filters that may be used, if necessary, to meet the spurious emissions mask include [filtered rectangular, half-sine (i.e., IEEE 802.15.4-2015, Section 12.2.6), root-raised cosine, and triangular].

The only hard constraints are:
- In-band spurious emissions must not exceed the Figure 2-5 mask (100 Hz RBW).
- Out-of-band emissions < 1% of total transmitted power.
- Phase change limited to 90° per half-chip transition.

**For the codec we will default to half-sine (IEEE 802.15.4-2015 § 12.2.6) pulse shaping** — it's widely used in OQPSK systems, has a clean closed-form, and is explicitly called out as acceptable. Swappable via a parameter.

---

## 4. Main-field bit layout (Table 3.1, Section 3.2)

| Bits | Width | Field |
|---|---|---|
| 1–16 | 16 | TAC number (0–65,535; 65,521–65,535 reserved for system beacons) |
| 17–30 | 14 | Serial number within TAC (0–16,383) |
| 31–40 | 10 | Country code (ITU MID) |
| 41 | 1 | Status of homing device |
| 42 | 1 | RLS function |
| 43 | 1 | Test protocol |
| 44 | 1 | N/S flag (N=0, S=1) |
| 45–51 | 7 | Latitude degrees (0–90) |
| 52–66 | 15 | Latitude decimal fraction |
| 67 | 1 | E/W flag (E=0, W=1) |
| 68–75 | 8 | Longitude degrees (0–180) |
| 76–90 | 15 | Longitude decimal fraction |
| 91–93 | 3 | Vessel ID type selector |
| 94–137 | 44 | Vessel identity (schema determined by 91–93) |
| 138–140 | 3 | Beacon Type (000=ELT, 001=EPIRB, 010=PLB, 011=ELT(DT), 111=System, others spare) |
| 141–154 | 14 | Spare bits (all 1s normally; all 0s for cancellation) |
| 155–202 | 48 | Rotating field (includes 4-bit identifier at 155–158) |
| 203–250 | 48 | BCH(250,202) parity |

Location default (no fix):
- Lat (44–66) = `1 1111111 000001111100000`
- Lon (67–90) = `1 11111111 111110000011111`

### Vessel ID type (bits 91–93)

| Code | Meaning | Identity encoding (bits 94–137) |
|---|---|---|
| 000 | No aircraft/maritime identity | All 0 |
| 001 | Maritime MMSI | 30-bit MMSI (94–123) + 14-bit EPIRB-AIS supplementary (124–137); no-AIS default = `10101010101010` |
| 010 | Radio call sign | 7 × 6-bit modified-Baudot, left-justified, spares = `100100` |
| 011 | Aircraft Registration Marking (Tail Number) | 7 × 6-bit modified-Baudot, right-justified |
| 100 | Aviation 24-bit ICAO address | 24-bit binary + 20 spare zeros, OR 24-bit + 3-letter operator (3×5 bits) + 5 spares |
| 101 | Aircraft operator + serial number | 3-letter operator (3×5 bits) + 12-bit serial + 17 spare 1s |
| 110 | Spare | — |
| 111 | Reserved for system testing | — |

### Modified Baudot code (Table 3.2)

6-bit codes (MSB..LSB) for 26 letters + digits 0–9 + space (`100100`) + hyphen (`011000`) + slash (`010111`). Full table transcribed in T018-2021.txt lines 1149–1184 (to be copied verbatim into the codec constants file).

---

## 5. Rotating fields (Section 3.3, Tables 3.3–3.8)

16 rotating field types, selected by the 4-bit identifier at bits 155–158 within the rotating-field block.

| # | Identifier | Name | Source table |
|---|---|---|---|
| 0 | 0000 | G.008 Objective Requirements | Table 3.3 |
| 1 | 0001 | ELT(DT) In-Flight Emergency | Table 3.4 |
| 2 | 0010 | RLS (Return Link Service) | Table 3.5 |
| 3 | 0011 | National Use | Table 3.6 |
| 4–14 | 0100..1110 | Spare (default all 0) | Table 3.7 |
| 15 | 1111 | Cancellation Message | Table 3.8 |

### Type 0 — G.008 Objective Requirements (Table 3.3)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Rotating Field Identifier | `0000` |
| 5–10 | 159–164 | 6 | Elapsed Time since activation | 0–63 hours, 1-hour steps, truncated; >63 → 63 |
| 11–21 | 165–175 | 11 | Time from last encoded location | 0–2046 min, 1-min steps, truncated; no fix ever → 2047 |
| 22–31 | 176–185 | 10 | Altitude of Encoded Location | −400 to 15952 m, 16 m steps; ≤−400 = all 0; no altitude = all 1 |
| 32–39 | 186–193 | 8 | Dilution of Precision | 4-bit HDOP + 4-bit VDOP (see spec DOP-code table) |
| 40–41 | 194–195 | 2 | Activation notification | 00 manual, 01 automatic by beacon, 10 automatic external, 11 spare |
| 42–44 | 196–198 | 3 | Remaining battery capacity | 000 ≤5% → 101 >75–100%, 110 reserved, 111 unknown |
| 45–46 | 199–200 | 2 | GNSS status | 00 no fix, 01 2D, 10 3D, 11 spare |
| 47–48 | 201–202 | 2 | Spare | `00` |

### Type 1 — ELT(DT) In-Flight Emergency (Table 3.4)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Identifier | `0001` |
| 5–21 | 159–175 | 17 | Time of last encoded location | Seconds since midnight UTC (0–86399); 1-sec resolution; unavailable / >24 h old = all 1 |
| 22–31 | 176–185 | 10 | Altitude | Same as Type 0 |
| 32–35 | 186–189 | 4 | Triggering event | 0001 manual crew, 0100 G-switch/deformation, 1000 automatic from avionics; others spare; most-recent event wins |
| 36–37 | 190–191 | 2 | GNSS status | Same as Type 0 |
| 38–39 | 192–193 | 2 | Remaining battery | 00 ≤33, 01 33–66, 10 >66, 11 unknown |
| 40–48 | 194–202 | 9 | Spare | All 0 |

### Type 2 — RLS (Table 3.5)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Identifier | `0010` |
| 5–6 | 159–160 | 2 | Unassigned | All 0 |
| 7–12 | 161–166 | 6 | Beacon RLS Capability | Bit 7 = auto Ack Type-1 accepted; bit 8 = manual RLM Type-2 accepted (at least one must be 1); bits 9–12 = reserved all 0 |
| 13–15 | 167–169 | 3 | RLS Provider | 001 Galileo, 010 GLONASS, others spare |
| 16–37 | 170–191 | 22 | Beacon Feedback (RLM acknowledgement) | Bit 16 Type-1 received flag; bit 17 Type-2 received flag; bits 18–37 = copy of RLM bits 61–80 when bit 16 set; various reserved/invalid combinations |
| 38–48 | 192–202 | 11 | Unassigned | All 0 |

### Type 3 — National Use (Table 3.6)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Identifier | `0011` |
| 5–48 | 159–202 | 44 | National use | Defined by national administrations; default all 0 |

### Types 4–14 — Spare (Table 3.7)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Identifier | `0100`..`1110` |
| 5–48 | 159–202 | 44 | Spares | All 0 |

### Type 15 — Cancellation (Table 3.8)

| Bits (rotating) | Bits (msg) | # | Field | Encoding |
|---|---|---|---|---|
| 1–4 | 155–158 | 4 | Identifier | `1111` |
| 5–46 | 159–200 | 42 | Fixed | All 1 |
| 47–48 | 201–202 | 2 | Method of deactivation | 00 spare, 10 manual by user, 01 automatic by external means, 11 spare |

### Rotating field scheduling (Table 3.9)

| Beacon class | Self-test | Normal | Cancellation |
|---|---|---|---|
| Standard (not ELT(DT), not RLS, not national) | Field #0 | Field #0 every burst | Field #15 |
| ELT(DT) | Field #1 | Field #1 every burst | Field #15 |
| RLS-enabled | Field #2 | Alternating #2 (odd bursts) and #0 (even bursts) | Field #15 |
| National use | Field #3 | #3 + #0 per national schedule | Field #15 |

Main 154-bit field is transmitted in every burst regardless.

---

## 6. 23-Hex ID derivation (Section 3.6, Appendix B.2)

The 23 Hex ID is **never transmitted**; it is generated by the ground segment (or at manufacture for labelling) by extracting bits from the 250-bit message and concatenating with fixed bits.

### Table 3.10 — 23 Hex ID composition

| Hex ID bits | Width | Source | Content |
|---|---|---|---|
| 1 | 1 | (fixed) | `1` |
| 2–11 | 10 | Msg bits 31–40 | C/S Country Code |
| 12 | 1 | (fixed) | `1` |
| 13 | 1 | (fixed) | `0` |
| 14 | 1 | (fixed) | `1` |
| 15–30 | 16 | Msg bits 1–16 | C/S TAC Number |
| 31–44 | 14 | Msg bits 17–30 | Beacon Serial Number |
| 45 | 1 | Msg bit 43 | Test Protocol flag |
| 46–48 | 3 | Msg bits 91–93 | Vessel ID type selector |
| 49–92 | 44 | Msg bits 94–137 | Vessel ID |
| **Total** | **92 bits = 23 hex chars** | | |

### Notes

1. Bits 1, 12, 13, 14 = `1101` prevents collisions with first-generation beacon 15-hex IDs.
2. The first 60 bits of the 23-Hex ID form a "15 Hex ID" (= truncation to first 15 hex chars), used for RLS.
3. When Vessel ID type = `100` (aviation 24-bit address), for the purposes of 23-Hex ID computation only, message bits 118–137 are treated as all 0 regardless of actual content.

### Appendix B.2 worked example

Same inputs as the BCH example:
- Country 201 → `0011001001`
- TAC 230 → `0000000011100110`
- Serial 573 → `00001000111101`
- Test flag = 0, Vessel type = 000, Vessel ID = all 0

Concatenation: `1 0011001001 1 0 1 0000000011100110 00001000111101 0 000 000…0`

Result: **`9934039823D000000000000`** (23 hex chars).

Corresponding 15 Hex ID: `9934039823D0000`.

---

## 7. GNSS encoded location protocol (Appendix C)

### Bit assignments

```
Latitude (bits 44–66, 23 bits):
  bit 44:     N/S flag  (N=0, S=1)
  bits 45–51: degrees   (0..90 integer)
  bits 52–66: decimal   (15 bits)

Longitude (bits 67–90, 24 bits):
  bit 67:     E/W flag  (E=0, W=1)
  bits 68–75: degrees   (0..180 integer)
  bits 76–90: decimal   (15 bits)
```

### Degree weighting

Lat bits (45,46,47,48,49,50,51) → weights (64, 32, 16, 8, 4, 2, 1).
Lon bits (68,69,70,71,72,73,74,75) → weights (128, 64, 32, 16, 8, 4, 2, 1).

### Decimal-fraction weighting (per Appendix C Table)

| Lat bit | Lon bit | Fraction of degree | Equator resolution (m) |
|---|---|---|---|
| 52 | 76 | 0.5 | 55566.67 |
| 53 | 77 | 0.25 | 27783.33 |
| 54 | 78 | 0.125 | 13891.67 |
| 55 | 79 | 0.0625 | 6945.833 |
| 56 | 80 | 0.03125 | 3472.917 |
| 57 | 81 | 0.015625 | 1736.458 |
| 58 | 82 | 0.0078125 | 868.2292 |
| 59 | 83 | 0.00390625 | 434.1146 |
| 60 | 84 | 0.001953125 | 217.0573 |
| 61 | 85 | 0.000976563 | 108.5286 |
| 62 | 86 | 0.000488281 | 54.26432 |
| 63 | 87 | 0.000244141 | 27.13216 |
| 64 | 88 | 0.00012207 | 13.56608 |
| 65 | 89 | 6.10352 × 10⁻⁵ | 6.78304 |
| 66 | 90 | 3.05176 × 10⁻⁵ | 3.39152 |

Max equator resolution = **3.39 m** (longitude bit 90, latitude bit 66).

### Defaults (Appendix C.3)

No-fix pattern:
- Degrees = all 1
- N/S and E/W flags = 0
- Lat decimal = `000001111100000`
- Lon decimal = `111110000011111`

### Encoding algorithm (Appendix C.5) — Integral Number Conversion Method (preferred)

```
1. Convert lat/lon from degrees+minutes to pure decimal degrees: deg = D + M/60
2. Take the fractional part f ∈ [0, 1)
3. Compute n = round(f × 2^15)
4. Encode n as 15-bit binary
```

Example: 35° 46.295′ N → 35.77158° → 0.77158 × 32768 = 25283.13 → 25283 → `110001011000011`.

Rounding rule: standard round-half-up (0.5 → up).

---

## 8. Testing/T.021 scan

T.021 (Preliminary Issue A, June 2018) is a **type-approval process document**, not a source of bit-level test vectors. It covers:
- Type-approval process (Section 2)
- Test-facility requirements (Section 3)
- On-air test procedures, compliance matrix (Annex A)
- RF measurement methodology — sampling, TOA estimation, EVM (Annex B)
- Environmental/mechanical test suites

T.021 is useful as a cross-reference for the "what should a decoder confirm" side (e.g., EVM measurement methodology in Annex B.5) but contributes **no additional bit-level vectors** beyond the T.018 Appendix B example. The spec's own risk entry ("test vectors may be incomplete or require paid access") proves correct: Appendix B is the only published ground-truth vector. We'll compensate by generating self-round-trip tests on top of it.

---

## 9. Summary — what to hard-code in the codec

The following constants belong in `test_vectors/` and in the codec source:

### test_vectors/bch_vector.json

```json
{
  "main_bits_hex": "00E608F4C986196188A047C000000000000FFFC0100C1A00960",
  "main_bits_length": 202,
  "expected_bch_parity_bin": "010010010010101001001111110001010111101001001001",
  "expected_bch_parity_length": 48,
  "expected_23hex_id": "9934039823D000000000000",
  "expected_15hex_id": "9934039823D0000"
}
```

### test_vectors/bch_polynomial.json

```json
{
  "generator_bits": "1110001111110101110000101110111110011110010010111",
  "generator_degree": 48,
  "minimal_polynomials": {
    "m1":  "X^8 + X^4 + X^3 + X^2 + 1",
    "m3":  "X^8 + X^6 + X^5 + X^4 + X^2 + X + 1",
    "m5":  "X^8 + X^7 + X^6 + X^5 + X^4 + X + 1",
    "m7":  "X^8 + X^6 + X^5 + X^3 + 1",
    "m9":  "X^8 + X^7 + X^5 + X^4 + X^3 + X^2 + 1",
    "m11": "X^8 + X^7 + X^6 + X^5 + X^2 + X + 1"
  },
  "parent_code": "BCH(255, 207)",
  "shortened_code": "BCH(250, 202)",
  "error_correction_capability_bits": 6,
  "padding_zeros_for_ground_calc": 5
}
```

### test_vectors/prn_sequences.json

```json
{
  "lfsr_polynomial": "X^23 + X^18 + 1",
  "lfsr_taps": [18, 0],
  "register_width": 23,
  "segment_length_chips": 38400,
  "chips_per_bit_per_channel": 256,
  "initialization": {
    "normal_i":    { "bits": "00000000000000000000001", "first_64_chips_hex": "80000108421284A1" },
    "normal_q":    { "bits": "00110101100000111111100", "first_64_chips_hex": "3F8358BAD030F231" },
    "self_test_i": { "bits": "10100101100100111110000", "first_64_chips_hex": "0F934A4D4CF3028D" },
    "self_test_q": { "bits": "01111001110100100101000", "first_64_chips_hex": "14973DC716CDE124" }
  }
}
```

(Note: hex strings above have been stripped of the intra-word spaces used in Table 2.2; the bit-exact 64-chip validation can use either form.)

---

## 10. Discrepancies vs. project brief — final list

The project brief (`sgb_codec_spec.docx`) Section 3.2 table contains several errors that must be corrected before SKILL.md is written:

| Brief claim | Actual (T.018 Rev 7) |
|---|---|
| Bits 44–46: "Rotating field identifier (3 bits)" | Rotating field ID is **4 bits at 155–158**, inside the rotating field itself |
| Bits 47–66: "Beacon type code (20 bits)" | Beacon Type is **3 bits at 138–140** |
| Bits 67–89: "Encoded location 23-bit lat/lon (4m resolution)" | Location is **47 bits at 44–90, 3.39 m resolution** (lat 23 bits + lon 24 bits) |
| Bits 90–154: "Vessel/aircraft/activity data (65 bits)" | Vessel ID is **47 bits (3+44) at 91–137**; remainder = beacon type + spare |
| "Gray coding + symbol mapping" | Spec does **not** describe Gray coding. Odd bit → I, even bit → Q; bit=1 inverts PRN. |
| "RRC pulse shaping, rolloff per T.018" | RRC is only one of 4 acceptable filter types (filtered rect, half-sine, RRC, triangular). No mandated rolloff. |
| "BCH(250,202) corrects up to 6 bit errors" | ✓ Correct |
| "Bits 203–250: BCH parity" | ✓ Correct |

---

## Sources

- `/sessions/optimistic-tender-davinci/specs/T018-2021.pdf` (primary)
- `/sessions/optimistic-tender-davinci/specs/T021-2018.pdf` (type-approval cross-reference)
- [T.018 Rev 7 (March 2021) — Thailand MCC mirror](https://sar.mot.go.th/document/THMCC/T018-MAR-26-2021%20SPECIFICATION%20FOR%20SECOND-GENERATION%20COSPAS-SARSAT%20406-MHz%20DISTRESS%20BEACONS.pdf)
- [T.021 Prelim A (June 2018) — tcmayak.ru mirror](https://tcmayak.ru/images/docs/CS-T021-JUN-27-2018.pdf)
