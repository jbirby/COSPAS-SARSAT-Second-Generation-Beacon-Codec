#!/usr/bin/env python3
"""
sgb_decode.py — command-line SGB decoder.

Decodes a 250-bit SGB message supplied either as a hex string or as a
DSSS-OQPSK audio WAV file. Prints the structured contents of the message,
the BCH status, and the 23-hex Beacon ID.

Examples
--------
Decode a hex string:

    python3 sgb_decode.py --hex 00E608F4C986196188A047C000000000000FFFC0100C1A00960492A4FC57A49

Decode a WAV file (mono real passband at 48 kHz carrier):

    python3 sgb_decode.py --wav beacon.wav --carrier-hz 48000

Decode a WAV file (stereo complex baseband I/Q):

    python3 sgb_decode.py --wav beacon.wav
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from typing import Any, Dict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sgb_common import (
    MAIN_FIELD_LENGTH, BEACON_TYPE_NAMES, VESSEL_ID_NAMES,
    bits_to_hex, hex_to_bits, country_name,
)
from sgb_message import parse_message, derive_23hex_id
from sgb_bch import bch_decode
from sgb_modulation import demodulate, CHIP_RATE


def read_wav(filename: str):
    """Read a WAV file. Returns (samples, sample_rate). If the file is
    stereo, samples is returned as complex I + jQ. Otherwise real float32."""
    with wave.open(filename, "rb") as wf:
        nchan = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        fr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2_147_483_648.0
    elif sampwidth == 1:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width: {sampwidth}")
    if nchan == 1:
        return data, fr
    elif nchan == 2:
        i = data[0::2]
        q = data[1::2]
        return (i + 1j * q).astype(np.complex64), fr
    else:
        raise ValueError(f"unsupported channel count: {nchan}")


def format_report(parsed: Dict[str, Any], main_bits: str,
                  codeword_bits: str, bch_errors: int, bch_ok: bool) -> str:
    lines = []
    lines.append("===== SGB Decoded Message =====")
    lines.append(f"TAC           : {parsed['tac']}")
    lines.append(f"Serial        : {parsed['serial']}")
    lines.append(f"Country       : {parsed['country']} ({parsed['country_name']})")
    lines.append(f"Homing device : {parsed['homing']}")
    lines.append(f"RLS function  : {parsed['rls_function']}")
    lines.append(f"Test protocol : {parsed['test_protocol']}")
    if parsed["lat_deg"] is None and parsed["lon_deg"] is None:
        lines.append("Position      : (no-fix default)")
    else:
        lines.append(f"Position      : {parsed['lat_deg']}, {parsed['lon_deg']}")
    v = parsed["vessel"]
    lines.append(f"Vessel ID     : {v['type_name']} (type {v['type_code']})")
    for key in ("mmsi", "callsign", "tail", "icao_address",
                "operator_code", "operator_serial"):
        if key in v:
            val = v[key]
            if key == "icao_address" and isinstance(val, int):
                val = f"0x{val:06X}"
            lines.append(f"  {key:14s}: {val}")
    lines.append(f"Beacon type   : {parsed['beacon_type_name']} ({parsed['beacon_type']})")
    rot = parsed["rotating"]
    lines.append(f"Rotating fld  : #{rot['identifier']} {rot['name']}")
    for key, val in rot.items():
        if key in ("identifier", "name", "raw_bits"):
            continue
        lines.append(f"  {key:14s}: {val}")
    lines.append("")
    lines.append(f"Main hex (51c): {bits_to_hex(main_bits)}")
    lines.append(f"Full 250b hex : {bits_to_hex(codeword_bits)}")
    lines.append(f"23-hex ID     : {derive_23hex_id(main_bits)}")
    lines.append(f"BCH status    : {'OK' if bch_ok else 'UNCORRECTABLE'} "
                 f"({bch_errors} bit error(s) corrected)")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Decode a COSPAS-SARSAT SGB message from hex or WAV.",
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--hex", help="Full 250-bit codeword hex (63 hex chars "
                                   "with 2 trailing zero-pad bits, as emitted "
                                   "by sgb_encode.py 'Full 250b').")
    src.add_argument("--main-hex", help="51-hex main field only (bits 1-202 "
                                       "with 2 trailing zero-pad bits); the "
                                       "decoder recomputes BCH parity itself.")
    src.add_argument("--wav", help="DSSS-OQPSK audio WAV file to decode.")
    p.add_argument("--carrier-hz", type=float, default=0.0,
                   help="Carrier frequency of the WAV (0 = complex baseband stereo).")
    p.add_argument("--mode", choices=["normal", "self_test"], default="normal")
    p.add_argument("--json", action="store_true",
                   help="Emit decoded fields as JSON to stdout.")
    args = p.parse_args()

    if args.hex:
        bits = hex_to_bits(args.hex, 250)
    elif args.main_hex:
        from sgb_bch import bch_encode as _bch_encode
        main_bits_in = hex_to_bits(args.main_hex, MAIN_FIELD_LENGTH)
        bits = main_bits_in + _bch_encode(main_bits_in)
    else:
        samples, sr = read_wav(args.wav)
        if sr % CHIP_RATE != 0:
            print(f"[warn] WAV sample rate {sr} is not an integer multiple of "
                  f"the chip rate ({CHIP_RATE}); results may be degraded.",
                  file=sys.stderr)
        bits, _info = demodulate(samples, sample_rate=float(sr),
                                 mode=args.mode, carrier_hz=args.carrier_hz)

    if len(bits) != 250:
        print(f"error: expected 250 bits, got {len(bits)}", file=sys.stderr)
        return 2

    # BCH decode
    corrected, n_err, ok = bch_decode(bits)
    main_bits = corrected[:MAIN_FIELD_LENGTH]
    parsed = parse_message(main_bits)

    if args.json:
        out = {
            "main_bits_hex": bits_to_hex(main_bits),
            "parity_bits_hex": bits_to_hex(corrected[MAIN_FIELD_LENGTH:]),
            "full_bits_hex": bits_to_hex(corrected),
            "beacon_id_23hex": derive_23hex_id(main_bits),
            "bch_ok": ok,
            "bch_errors_corrected": n_err,
            "parsed": _json_safe(parsed),
        }
        print(json.dumps(out, indent=2, default=str))
    else:
        print(format_report(parsed, main_bits, corrected, n_err, ok))

    return 0 if ok else 1


def _json_safe(obj):
    """Recursively convert tuples/sets to lists for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_json_safe(v) for v in obj]
    return obj


if __name__ == "__main__":
    sys.exit(main())
