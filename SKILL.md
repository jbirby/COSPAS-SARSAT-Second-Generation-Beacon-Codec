---
name: sgb-codec
description: >
  Encode and decode COSPAS-SARSAT Second-Generation Beacon (SGB) messages per
  specification C/S T.018 (Rev 7, March 2021). SGBs are the 406 MHz emergency
  distress beacons that succeeded the original first-generation beacons — they
  use DSSS-OQPSK modulation, a 250-bit BCH(250,202)-protected message, 300 bit/s
  information rate, and carry richer beacon identity and position data than the
  legacy format. Use this skill whenever the user mentions SGB, second-generation
  beacon, T.018, DSSS-OQPSK beacon, ELT(DT), RLS (Return Link Service) beacon,
  23-hex ID, rotating field, or wants to build or analyse WAV files containing
  SGB bursts. Handles EPIRB, ELT, ELT(DT), PLB, and system beacons; encodes
  registration, position (GNSS-encoded per Appendix C), rotating field data, and
  PRN-spread OQPSK chips; decodes WAV recordings back to structured beacon data.
  This skill is distinct from `cospas-sarsat-codec`, which handles the legacy
  first-generation 112/144-bit BPSK beacons.
---

## COSPAS-SARSAT Second-Generation Beacon (SGB) Codec

End-to-end codec for emergency beacons built to specification C/S T.018, the modern replacement for first-generation 406 MHz distress beacons. Covers message construction, BCH(250,202) encoding/decoding, PRN spreading, DSSS-OQPSK modulation, and WAV file round-trips.

### What is an SGB?

Second-generation beacons are the current-design 406 MHz distress beacons mandated by the COSPAS-SARSAT system. Compared to first-generation beacons they provide:

- A larger 202-bit payload (plus 48-bit BCH parity) instead of the legacy 112/144-bit format.
- DSSS-OQPSK modulation with PRN spreading, which gives better multi-beacon resolution in the MEOSAR environment.
- A rotating field that delivers dynamic information (elapsed time since activation, altitude, DOP, battery, activation source, RLS feedback, cancellation) across successive bursts.
- A 23-hex Beacon ID (a 92-bit identifier derived from the message but never transmitted) that replaces the 15-hex ID for ground-segment use.
- Explicit support for ELT(DT) in-flight emergency reporting and Return Link Service (RLS) acknowledgements.

Four beacon classes are defined:

- **EPIRB** — maritime, vessels
- **ELT** — aviation, crash-survivable
- **ELT(DT)** — aviation, distress tracking, activated pre-crash
- **PLB** — personal locator beacon

### Signal summary

| Parameter | Value |
|---|---|
| RF carrier (real beacon) | 406.05 MHz |
| Modulation | DSSS-OQPSK |
| Chip rate | 38,400 chips/s ±0.6 |
| Chips per bit per channel (I, Q) | 256 |
| Information bit rate | 300 bit/s (150 on each of I and Q) |
| I/Q offset | ½-chip, I leads Q |
| Message length | 250 bits (202 data + 48 BCH parity) |
| Burst duration | 1000 ms ±1 ms |
| Preamble | 166.7 ms = 6400 chips (data bits all 0, PRN uninverted) |
| Repetition | random 28–30 s in normal mode |
| PRN LFSR | 23-bit, `G(x) = X^23 + X^18 + 1`, period 2^23−1 |

**Baseband audio representation** (what this skill produces): the codec emits WAV files either as stereo complex baseband (I on the left channel, Q on the right — default, `--carrier-hz 0`) or as a mono real-passband waveform centred on a chosen carrier (`--carrier-hz 48000`, for example). 16-bit signed, default sample rate 192 000 Hz (because the chip rate is 38.4 kHz, anything below 80 kHz cannot carry the full signal). Files produced by this codec are NOT suitable for RF transmission — they are a lab/teaching aid.

### Message structure (Table 3.1)

The transmitted 250-bit pattern is:

| Bits | Width | Field |
|---|---|---|
| 1–16 | 16 | TAC Number (Type Approval Certificate; system beacons use 65,521–65,535) |
| 17–30 | 14 | Serial Number within TAC |
| 31–40 | 10 | Country code (ITU MID) |
| 41 | 1 | Status of homing device |
| 42 | 1 | RLS function flag |
| 43 | 1 | Test protocol flag |
| 44–90 | 47 | GNSS-encoded location (see Appendix C) |
| 91–93 | 3 | Vessel ID type selector |
| 94–137 | 44 | Vessel ID (schema determined by 91–93) |
| 138–140 | 3 | Beacon Type (000 ELT / 001 EPIRB / 010 PLB / 011 ELT(DT) / 111 System) |
| 141–154 | 14 | Spare (all 1s normal, all 0s cancellation) |
| 155–158 | 4 | Rotating field identifier |
| 159–202 | 44 | Rotating field payload |
| 203–250 | 48 | BCH(250,202) parity |

Sixteen rotating-field types are defined (Tables 3.3–3.8). The codec understands: G.008 Objective Requirements (#0), ELT(DT) In-Flight Emergency (#1), RLS (#2), National Use (#3), Spares (#4–14), and Cancellation (#15). Scheduling per Table 3.9 is handled automatically when you encode multiple bursts.

### 23-hex Beacon ID

The 23-hex ID is never transmitted — the codec derives it from the message during encoding (for labelling) and during decoding (for display). Per Table 3.10 it is the concatenation of fixed bits `1`, country code, `1`, `0`, `1`, TAC, serial number, test flag, vessel ID type, and vessel ID (92 bits, 23 hex chars).

### How to use this codec

#### Encoding (beacon data → WAV file)

From CLI flags:

```bash
python3 scripts/sgb_encode.py \
    --country 366 --tac 230 --serial 573 \
    --beacon-type PLB \
    --lat 48.79315 --lon 2.24127 \
    --out beacon.wav --sample-rate 153600
```

From a JSON config file (see `examples/`):

```bash
python3 scripts/sgb_encode.py --json examples/elt_dt_usa.json \
    --out elt.wav --sample-rate 192000
```

Common options:

- `--beacon-type {ELT,EPIRB,PLB,ELT_DT,SYSTEM}` — 3-bit beacon type code.
- `--country NNN` — ITU MID country code (10 bits, 3 digits).
- `--tac NNNNN` — 16-bit Type Approval Certificate number.
- `--serial NNNNN` — 14-bit serial within TAC.
- `--vessel-id-type {NONE,MMSI,CALLSIGN,TAIL,ICAO,OPERATOR}` together with the relevant field: `--mmsi`, `--callsign`, `--tail`, `--icao` (decimal or `0x...`), `--operator-code` + `--operator-serial`.
- `--lat`, `--lon` — decimal degrees. Omit both for the no-fix default pattern.
- `--homing 0|1`, `--rls-flag 0|1`, `--test 0|1` — status bits.
- `--out PATH` — write a 1-second DSSS-OQPSK burst WAV.
- `--sample-rate HZ` — output WAV sample rate (default 192000; must be an integer multiple of 38400).
- `--carrier-hz HZ` — 0 (default) writes stereo complex baseband (I left, Q right); non-zero writes a mono real passband at that carrier.
- `--pulse {rect,half_sine}` — pulse shape (default `rect`; `half_sine` matches IEEE 802.15.4-2015 § 12.2.6).
- `--mode {normal,self_test}` — PRN initial-state set.
- `--json FILE` — load defaults from a JSON config file. CLI flags override matching JSON keys.

For rotating-field selection, use JSON. See `examples/elt_dt_usa.json`, `examples/epirb_uk_mmsi.json`, `examples/plb_test.json`.

#### Decoding (WAV file → beacon information)

```bash
# From a WAV
python3 scripts/sgb_decode.py --wav beacon.wav

# From a WAV recorded at a real carrier
python3 scripts/sgb_decode.py --wav beacon.wav --carrier-hz 48000

# From a 63-char hex full-codeword string (as emitted by the encoder)
python3 scripts/sgb_decode.py --hex 00E608F56E0619618047B88000000000002FFFC00FFFFF801C09CBB2CBD65F4

# From a 51-char main-field-only hex (decoder recomputes BCH)
python3 scripts/sgb_decode.py --main-hex 00E608F4C986196188A047C000000000000FFFC0100C1A00960

# JSON output instead of human report
python3 scripts/sgb_decode.py --wav beacon.wav --json
```

The decoder prints (or writes as JSON):

- Beacon type, country, TAC, serial.
- Homing-device / RLS / test flags.
- Decoded GNSS position (or "no-fix default").
- Vessel ID type and identity (MMSI, call sign, tail, ICAO address, operator code + serial).
- Rotating-field type and all sub-fields.
- Main-field hex, full-codeword hex, 23-hex ID.
- BCH status: `OK (n bit errors corrected)` or `UNCORRECTABLE`.

#### Testing

```bash
python3 tests/run_all.py   # runs every M2..M5 suite

# or run individual suites
python3 tests/test_m2_bch.py
python3 tests/test_m3_prn.py
python3 tests/test_m4_message.py
python3 tests/test_m5_modulation.py
```

The combined suite covers:

- **M2 (BCH):** generator-polynomial match, Appendix B.1 parity ground truth, 200 zero-error decodes, 300 random patterns each at 1..6 bit errors (all corrected), and rejection of 7-bit error patterns beyond the code's correction capacity.
- **M3 (PRN):** first-64-chip verification against Table 2.2 for all four initial states (Normal I, Normal Q, Self-Test I, Self-Test Q), 38 400-chip segment integrity, period = 2^23 − 1, and reset reproducibility.
- **M4 (Message):** Appendix B.1 main-field hex, BCH parity, and 23-hex ID ground truth; Appendix C GNSS round-trips including no-fix default and full hemisphere sweeps; round-trip of every vessel ID type and every rotating-field type; full `SGBMessage.build()` → `parse_message` round-trip with BCH; Appendix B.2 ICAO-special-rule verification.
- **M5 (Modem):** burst-constant sanity, chip-stream construction obeying Table 2.4, round-trip through complex baseband with rectangular and half-sine pulses, round-trip through real passband at a 48 kHz carrier, and self-test mode round-trip.

### File layout

```
sgb-codec/
├── SKILL.md                      # this file
├── scripts/
│   ├── sgb_common.py             # constants, Baudot, bit/hex helpers, ID parts
│   ├── sgb_bch.py                # BCH(250,202) encoder + decoder (BM + Chien)
│   ├── sgb_prn.py                # 23-bit LFSR PRN generator (all 4 states)
│   ├── sgb_message.py            # main-field + rotating-field builder/parser +
│   │                             #   23-hex ID derivation
│   ├── sgb_modulation.py         # DSSS spreading, OQPSK modulator/demodulator
│   ├── sgb_encode.py             # CLI: beacon params → hex / WAV
│   └── sgb_decode.py             # CLI: WAV or hex → structured report / JSON
├── test_vectors/
│   ├── bch_vector.json           # Appendix B.1 reference vector
│   ├── bch_polynomial.json       # generator + minimal polynomials
│   ├── prn_sequences.json        # all 4 initial states + first 64 chips
│   └── gnss_examples.json        # lat/lon round-trip expectations
├── examples/
│   ├── elt_dt_usa.json           # aviation ELT(DT), ICAO, ELT-DT rotating field
│   ├── epirb_uk_mmsi.json        # maritime EPIRB, MMSI, RLS rotating field
│   └── plb_test.json             # PLB in self-test mode, no-fix default
└── tests/
    ├── run_all.py                # run every M2..M5 suite
    ├── test_m2_bch.py            # BCH(250,202) ground truth + fuzz tests
    ├── test_m3_prn.py            # PRN Table 2.2 first-64-chip verification
    ├── test_m4_message.py        # Appendix B.1/B.2/C coverage
    └── test_m5_modulation.py     # chip streams + modem round-trips
```

### Important constraints

- **Do not transmit.** The WAV files this skill produces are baseband audio representations of real distress-beacon bursts. Up-converting one to 406.05 MHz and radiating it over-the-air would trigger live SAR resources, is a criminal offence in most jurisdictions, and risks substantial fines and prosecution. The codec exists for analysis, teaching, and decoder development, not for transmission.
- **Sync-word collisions.** An SGB message's preamble (6400 chips of zero-data with uninverted PRN) is specifically designed to autocorrelate against the Normal I/Q initial states. Self-test bursts correlate only against the Self-Test I/Q states. The decoder uses this to detect burst start and to distinguish live from self-test bursts — do not change the PRN initial states unless you know you are building a non-standard beacon.
- **BCH parity is computed over bits 1–202**, then appended as bits 203–250. The ground-segment algorithm prepends two zero bits (restoring the BCH(255,207) framing used during divisor computation), but the transmitted form has exactly 250 bits with no padding.
- **Rotating field scheduling** per Table 3.9 is the beacon's responsibility in the real world; this codec will automatically alternate the rotating field across bursts when `--bursts > 1` unless you pass `--rotating-field` explicitly (in which case every burst carries that field).

### References

- COSPAS-SARSAT specification C/S T.018, Issue 1, Revision 7 (March 2021).
- COSPAS-SARSAT specification C/S T.021, Preliminary Issue A (June 2018) — type-approval standard.
- IEEE 802.15.4-2015 § 12.2.6 — half-sine OQPSK pulse shape.
- Companion skill `cospas-sarsat-codec` for the legacy 112/144-bit BPSK first-generation format.
