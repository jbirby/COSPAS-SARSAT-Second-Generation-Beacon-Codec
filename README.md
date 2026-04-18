# sgb-codec

A Python codec for **COSPAS-SARSAT Second-Generation Beacons (SGB)**, the modern 406 MHz emergency distress beacon format specified in C/S T.018 Rev 7 (March 2021). SGBs are the current-design replacement for the legacy 406 MHz beacon family, adding DSSS-OQPSK modulation, a 250-bit BCH-protected message, GNSS position encoding, a rotating dynamic-data field, and a 23-hex Beacon ID.

This library implements the full protocol stack end-to-end: message construction, BCH(250,202) encoding and decoding, PRN spreading, DSSS-OQPSK modulation and demodulation, and WAV file round-trips. It is also distributed as a Claude skill (`sgb-codec.skill`) that can be imported into Cowork or Claude Code.

Distinct from (https://github.com/jbirby/COSPAS-SARSAT-406-MHz-Beacon-Codec), which handles the legacy 112/144-bit BPSK beacons. The two systems share a name and a radio band but have completely different message formats, modulation, and error-correction schemes.

## Quick start

```bash
pip install numpy
cd sgb-codec/scripts
```

### Encode

Generate a maritime EPIRB burst with MMSI vessel identity, writing a stereo
I/Q WAV at 192 kHz:

```bash
python3 sgb_encode.py --json ../examples/epirb_uk_mmsi.json --out epirb.wav
```

Or build one from command-line flags:

```bash
python3 sgb_encode.py \
    --country 338 --tac 230 --serial 573 \
    --beacon-type PLB \
    --lat 48.79315 --lon 2.24127 \
    --out plb.wav
```

### Decode

From an encoded WAV:

```bash
python3 sgb_decode.py --wav plb.wav
```

From a 63-hex message (full 250-bit codeword):

```bash
python3 sgb_decode.py --hex FFFED000166A0...
```

From a 51-hex main field only (BCH parity recomputed automatically):

```bash
python3 sgb_decode.py --main-hex FFFED000166A0...
```

### Run the tests

```bash
python3 tests/run_all.py
```

This exercises the BCH codec, PRN generators, message builder/parser,
DSSS-OQPSK modem, and the full end-to-end evaluation harness. Expect
around 400 passing checks across the suites.

## Signal summary

| Parameter | Value |
|---|---|
| RF carrier (operational beacon) | 406.05 MHz |
| Modulation | DSSS-OQPSK |
| Chip rate | 38,400 chips/s per channel |
| Chips per bit per channel | 256 |
| Information bit rate | 300 bit/s (150 on I, 150 on Q) |
| I/Q offset | ½ chip, I leads Q |
| Message length | 250 bits (202 data + 48 BCH parity) |
| Error correction | BCH(250,202), corrects up to 6 bit errors |
| Burst duration | 1.0 s (166.7 ms preamble + 833.3 ms data) |
| PRN spreading codes | 4 (I/Q × normal/self-test), LFSR from G(x) = X²³ + X¹⁸ + 1 |

## What's implemented

- BCH(250,202) encode + bounded-distance decode (6-error-correcting, 7-error detection)
- All four PRN generators (normal-I, normal-Q, self-test-I, self-test-Q) matching the spec's first-64-chip reference
- Full main-field assembly including Appendix C GNSS position encoding (no-fix default, both hemispheres, polar extremes)
- All six vessel-ID types: NONE, MMSI, Callsign (Modified Baudot), Tail number, 24-bit ICAO address, Operator-code + serial
- All six rotating-field types: G.008 (elapsed time / altitude / DOP / battery), ELT(DT) in-flight tracking, RLS (Return Link Service), National-use, Spare, and Cancellation
- 23-hex Beacon ID derivation per Table 3.10 including the Appendix B.2 ICAO special rule
- DSSS-OQPSK modulator with rectangular and half-sine (IEEE 802.15.4-2015 § 12.2.6) pulse shaping
- Complex-baseband I/Q output (stereo WAV) and real-passband output at a user-specified carrier
- Chip-aligned demodulator with correlation-based despreading
- CLI encoder and decoder, plus JSON config support for reproducible beacon definitions
- Spec-traced test suite with 200+ checks including BCH error-injection robustness

## What's not implemented

This is a **protocol-layer codec**, not a radio receiver. The following layers would sit between an SDR capture and our decoder and are out of scope:

- **Burst detection** — finding where in a long recording the 1-second burst actually begins (the demodulator assumes the burst starts at sample 0).
- **Carrier frequency recovery** — pulling any residual frequency offset from the SDR's oscillator drift down to DC. A few ppm at 406 MHz is several kHz of residual carrier, which will destroy coherent despreading if uncorrected.
- **Phase/polarity disambiguation** — resolving the 90° / 180° IQ ambiguity introduced by an arbitrary SDR phase reference.
- **Soft-decision BCH decoding** — the included decoder is hard-decision bounded-distance; a soft-input decoder would extract more performance at low SNR.

These are the standard functions of a field receiver and are typically built as a GNU Radio flowgraph that hands an aligned, frequency-locked IQ burst to a protocol back end. This library is designed to be that back end.

## SDR pipeline context

A complete SGB receive chain looks like this:

```
   406.05 MHz RF
        │
        ▼
   SDR front end          ── antenna, LNA, tuner, ADC (RTL-SDR, Airspy, HackRF, USRP, ...)
        │
        ▼  (complex IQ at ~2 MSPS, centred on 406.05 MHz)
        │
   DSP preprocessing      ── channelize, burst-detect, freq sync, timing recovery,
        │                    phase recovery  (GNU Radio, scipy, or similar)
        │
        ▼  (aligned IQ burst at 192 kHz, stereo WAV)
        │
   sgb-codec              ── despread, BCH decode, parse 202 data bits
        │                    → structured beacon data + 23-hex ID
        ▼
   Application layer      ── registry lookup, SAR dispatch, visualization
```

Only the middle box is in this repository. For test-signal generation the flow runs in reverse and the codec generates a WAV that a receiver under test can process.

## Examples

Three ready-made beacon configurations are in [`examples/`](examples/):

- [`plb_test.json`](examples/plb_test.json) — PLB self-test with no position fix, G.008 rotating field
- [`epirb_uk_mmsi.json`](examples/epirb_uk_mmsi.json) — UK maritime EPIRB with MMSI vessel identity and RLS rotating field
- [`elt_dt_usa.json`](examples/elt_dt_usa.json) — USA ELT(DT) aviation beacon with ICAO address, operator code, and ELT(DT) rotating field

Each encodes to a valid WAV and decodes cleanly through the full chain.

## Repository layout

```
sgb-codec/
├── README.md                  # This file
├── SKILL.md                   # Full protocol documentation and
│                              # Claude-skill manifest (detailed reference)
├── scripts/
│   ├── sgb_common.py          # Bit helpers, constants, country codes
│   ├── sgb_bch.py             # BCH(250,202) encode/decode
│   ├── sgb_prn.py             # PRN LFSR generators
│   ├── sgb_message.py         # Main-field builder/parser + rotating fields
│   ├── sgb_modulation.py      # DSSS-OQPSK modem
│   ├── sgb_encode.py          # CLI encoder
│   └── sgb_decode.py          # CLI decoder
├── tests/
│   ├── run_all.py             # Master test runner
│   ├── test_m2_bch.py         # BCH round-trip + error correction
│   ├── test_m3_prn.py         # PRN sequence validation
│   ├── test_m4_message.py     # Message builder/parser + spec vectors
│   ├── test_m5_modulation.py  # Modem round-trip
│   └── test_m8_eval.py        # End-to-end evaluation harness
├── test_vectors/              # Spec-extracted reference vectors
│   ├── bch_polynomial.json    # Generator polynomial + Appendix B.1 parity
│   ├── bch_vector.json        # Appendix B.1 worked example
│   ├── gnss_examples.json     # Appendix C position-encoding vectors
│   └── prn_sequences.json     # Expected first-64-chip PRN sequences
├── examples/                  # Ready-made beacon configurations (JSON)
└── sgb-codec.skill            # Packaged Claude skill (zip of the above)
```

See [`SKILL.md`](SKILL.md) for the full protocol reference — bit-field
layouts, rotating-field formats, the 23-hex ID algorithm, and detailed
worked examples.

## Safety — avoiding false alerts

406 MHz is a live distress band monitored by the international COSPAS-SARSAT system. Encoded WAV files in this repository are audio-rate baseband or passband signals; they cannot by themselves trigger a satellite alert. Transmitting them as an actual RF signal on 406 MHz requires deliberate upconversion, amplification, and an unlicensed beacon — which is illegal in every jurisdiction.

When producing example signals for public distribution or for sharing on GitHub, stack the following "clearly synthetic" markers so the content itself is unambiguously not a real beacon even if its audio is inspected:

- `--test 1` sets the spec-defined Test Protocol flag, which ground segment treats as a non-dispatch test burst.
- `--mode self_test` selects the self-test PRN, which operational MEOSAR receivers do not correlate against.
- `--country 0` is the unassigned MID (no Mission Control Centre is mapped to it).
- `--tac 0 --serial 0` are not valid beacon type-approval or serial numbers.
- For vessel IDs, use unassigned synthetic values: ICAO operator code `ZZZ`/`XXX`/`TST`, 24-bit ICAO address `0x000000` or `0xFFFFFF`, MMSI `0` or `999999999`, tail number `TEST123`.

The bundled `examples/plb_test.json` is a good template for a "junk" beacon.

## References

- COSPAS-SARSAT specification **C/S T.018** (Rev 7, March 2021) — *Specification for Second-Generation Beacons*. Authoritative protocol document.
- COSPAS-SARSAT **C/S T.021** — Type approval standard for second-generation beacons.
- COSPAS-SARSAT portal: <https://www.cospas-sarsat.int/>
- IEEE 802.15.4-2015 § 12.2.6 — half-sine pulse shaping reference.
- ICAO Doc 8585 — airline operator codes.
- ITU-R M.585 — Maritime Identification Digit (MID) assignments.
- Parent project: (https://github.com/jbirby/COSPAS-SARSAT-406-MHz-Beacon-Codec). — legacy 406 MHz beacon codec for first-generation hardware.

## Disclaimer

This codec is provided for research, education, test-signal generation, and receiver-development use. Never transmit the generated signals on 406 MHz.

## License

Released for educational and hobbyist use. Respect 406 MHz frequency allocations and beacon regulations in your jurisdiction.
