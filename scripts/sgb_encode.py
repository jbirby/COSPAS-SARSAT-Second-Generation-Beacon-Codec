#!/usr/bin/env python3
"""
sgb_encode.py — command-line SGB encoder.

Given beacon parameters on the command line or in a JSON file, build a
valid 250-bit SGB message (202-bit main field + 48-bit BCH parity),
print the hex representation and the 23-hex Beacon ID, and optionally
write a 1-second DSSS-OQPSK WAV file.

Examples
--------
Minimal distress PLB in US waters, writing audio:

    python3 sgb_encode.py --country 366 --tac 230 --serial 573 \\
            --beacon-type PLB --lat 48.79315 --lon 2.24127 \\
            --out beacon.wav

Encode without audio (just print the hex/ID):

    python3 sgb_encode.py --country 366 --tac 230 --serial 573 \\
            --beacon-type ELT

Load from JSON:

    python3 sgb_encode.py --json beacon.json --out beacon.wav
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
    BEACON_TYPE_ELT, BEACON_TYPE_EPIRB, BEACON_TYPE_PLB,
    BEACON_TYPE_ELT_DT, BEACON_TYPE_SYSTEM, BEACON_TYPE_NAMES,
    VESSEL_ID_NONE, VESSEL_ID_MMSI, VESSEL_ID_CALLSIGN, VESSEL_ID_TAIL,
    VESSEL_ID_ICAO, VESSEL_ID_OPERATOR,
    bits_to_hex, country_name,
)
from sgb_message import (
    SGBMessage, build_rotating_g008, build_rotating_elt_dt,
    build_rotating_rls, build_rotating_national, build_rotating_spare,
    build_rotating_cancellation, derive_23hex_id,
)
from sgb_bch import bch_encode
from sgb_modulation import ModulationParams, modulate, CHIP_RATE


BEACON_TYPE_LOOKUP = {
    "ELT": BEACON_TYPE_ELT,
    "EPIRB": BEACON_TYPE_EPIRB,
    "PLB": BEACON_TYPE_PLB,
    "ELT_DT": BEACON_TYPE_ELT_DT,
    "ELT(DT)": BEACON_TYPE_ELT_DT,
    "SYSTEM": BEACON_TYPE_SYSTEM,
}

VESSEL_ID_LOOKUP = {
    "NONE": VESSEL_ID_NONE,
    "MMSI": VESSEL_ID_MMSI,
    "CALLSIGN": VESSEL_ID_CALLSIGN,
    "TAIL": VESSEL_ID_TAIL,
    "ICAO": VESSEL_ID_ICAO,
    "OPERATOR": VESSEL_ID_OPERATOR,
}


def build_message_from_config(cfg: Dict[str, Any]) -> SGBMessage:
    """Construct an SGBMessage from a dict of beacon parameters."""
    vessel_id_type_name = str(cfg.get("vessel_id_type", "NONE")).upper()
    vessel_id_type = VESSEL_ID_LOOKUP.get(vessel_id_type_name, VESSEL_ID_NONE)

    beacon_type_name = str(cfg.get("beacon_type", "ELT")).upper()
    beacon_type = BEACON_TYPE_LOOKUP.get(beacon_type_name, BEACON_TYPE_ELT)

    rot_kind = str(cfg.get("rotating", "G008")).upper()
    if rot_kind in ("G008", "G.008"):
        rot = build_rotating_g008()
    elif rot_kind in ("ELT_DT", "ELTDT"):
        rot = build_rotating_elt_dt(**cfg.get("rotating_params", {}))
    elif rot_kind == "RLS":
        rot = build_rotating_rls(**cfg.get("rotating_params", {}))
    elif rot_kind == "NATIONAL":
        rot = build_rotating_national(
            payload_bits=cfg.get("rotating_params", {}).get("payload_bits", "0" * 44)
        )
    elif rot_kind == "SPARE":
        rot = build_rotating_spare(
            identifier=int(cfg.get("rotating_params", {}).get("identifier", 4))
        )
    elif rot_kind == "CANCELLATION":
        rot = build_rotating_cancellation(
            method=int(cfg.get("rotating_params", {}).get("method", 2))
        )
    else:
        rot = build_rotating_g008()

    return SGBMessage(
        tac=int(cfg.get("tac", 0)),
        serial=int(cfg.get("serial", 0)),
        country=int(cfg.get("country", 0)),
        homing=int(cfg.get("homing", 0)),
        rls_function=int(cfg.get("rls_function", 0)),
        test_protocol=int(cfg.get("test", 0)),
        lat_deg=cfg.get("lat"),
        lon_deg=cfg.get("lon"),
        vessel_id_type=vessel_id_type,
        vessel_id_params=cfg.get("vessel_id_params", {}),
        beacon_type=beacon_type,
        spare_bits=cfg.get("spare_bits", "1" * 14),
        rotating=rot,
    )


def write_wav(filename: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write a real-valued audio buffer to a 16-bit PCM WAV file.

    If ``audio`` is complex, writes a 2-channel (stereo) file with I on
    the left channel and Q on the right.
    """
    if np.iscomplexobj(audio):
        i = audio.real.astype(np.float32)
        q = audio.imag.astype(np.float32)
        peak = float(np.max(np.abs(np.concatenate([i, q])))) or 1.0
        i16 = np.clip(i / peak * 32767.0, -32768, 32767).astype(np.int16)
        q16 = np.clip(q / peak * 32767.0, -32768, 32767).astype(np.int16)
        stereo = np.empty(i.size * 2, dtype=np.int16)
        stereo[0::2] = i16
        stereo[1::2] = q16
        nchan = 2
        data = stereo.tobytes()
    else:
        peak = float(np.max(np.abs(audio))) or 1.0
        i16 = np.clip(audio / peak * 32767.0, -32768, 32767).astype(np.int16)
        nchan = 1
        data = i16.tobytes()

    with wave.open(filename, "wb") as wf:
        wf.setnchannels(nchan)
        wf.setsampwidth(2)  # int16
        wf.setframerate(int(sample_rate))
        wf.writeframes(data)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Encode a COSPAS-SARSAT SGB message to hex and/or WAV.",
    )
    p.add_argument("--json", help="Load beacon parameters from JSON file")
    p.add_argument("--country", type=int, help="ITU MID country code (10 bits)")
    p.add_argument("--tac", type=int, help="Type Approval Certificate (16 bits)")
    p.add_argument("--serial", type=int, help="Serial number (14 bits)")
    p.add_argument("--beacon-type",
                   choices=sorted(BEACON_TYPE_LOOKUP.keys()),
                   help="Beacon type (ELT, EPIRB, PLB, ELT_DT, SYSTEM); "
                        "default ELT if not in JSON")
    p.add_argument("--lat", type=float, help="Latitude in decimal degrees")
    p.add_argument("--lon", type=float, help="Longitude in decimal degrees")
    p.add_argument("--homing", type=int,
                   help="Homing-device status bit (0 or 1)")
    p.add_argument("--rls-flag", type=int,
                   help="RLS function flag (0 or 1)")
    p.add_argument("--test", type=int,
                   help="Test protocol flag (0 or 1)")
    p.add_argument("--vessel-id-type",
                   choices=sorted(VESSEL_ID_LOOKUP.keys()),
                   help="Vessel ID type; default NONE if not in JSON")
    p.add_argument("--mmsi", type=int, help="MMSI (for vessel ID MMSI)")
    p.add_argument("--callsign", help="Radio callsign (for vessel ID CALLSIGN)")
    p.add_argument("--tail", help="Aircraft tail number (for vessel ID TAIL)")
    p.add_argument("--icao", type=lambda s: int(s, 0),
                   help="24-bit ICAO address (hex or decimal; for vessel ID ICAO)")
    p.add_argument("--operator-code", help="3-letter operator code")
    p.add_argument("--operator-serial", type=int,
                   help="Operator serial number (for vessel ID OPERATOR)")
    p.add_argument("--out", help="Output WAV file path (optional)")
    p.add_argument("--sample-rate", type=int, default=192_000,
                   help="WAV sample rate (Hz), must be >= 2*chip rate")
    p.add_argument("--carrier-hz", type=float, default=0.0,
                   help="Carrier frequency for real-passband output "
                        "(0 = complex baseband I/Q stereo)")
    p.add_argument("--pulse", choices=["rect", "half_sine"], default="rect",
                   help="Pulse shape (default: rect)")
    p.add_argument("--mode", choices=["normal", "self_test"], default="normal",
                   help="PRN mode (default: normal)")
    args = p.parse_args()

    # Build configuration dict
    if args.json:
        with open(args.json, "r") as fh:
            cfg = json.load(fh)
    else:
        cfg = {}

    # Apply CLI overrides
    def setif(key, val):
        if val is not None:
            cfg[key] = val

    setif("country", args.country)
    setif("tac", args.tac)
    setif("serial", args.serial)
    setif("beacon_type", args.beacon_type)
    setif("lat", args.lat)
    setif("lon", args.lon)
    setif("homing", args.homing)
    if args.rls_flag is not None:
        cfg["rls_function"] = args.rls_flag
    setif("test", args.test)
    setif("vessel_id_type", args.vessel_id_type)

    vip: Dict[str, Any] = dict(cfg.get("vessel_id_params", {}))
    if args.mmsi is not None:
        vip["mmsi"] = args.mmsi
    if args.callsign is not None:
        vip["callsign"] = args.callsign
    if args.tail is not None:
        vip["tail"] = args.tail
    if args.icao is not None:
        vip["icao"] = args.icao
    if args.operator_code is not None:
        vip["operator_code"] = args.operator_code
    if args.operator_serial is not None:
        vip["operator_serial"] = args.operator_serial
    if vip:
        cfg["vessel_id_params"] = vip

    msg = build_message_from_config(cfg)
    main_bits = msg.build()
    parity_bits = bch_encode(main_bits)
    full_bits = main_bits + parity_bits
    main_hex = bits_to_hex(main_bits)
    full_hex = bits_to_hex(full_bits)
    parity_hex = bits_to_hex(parity_bits)
    beacon_id = derive_23hex_id(main_bits)

    print(f"[Encoder] TAC         = {msg.tac}")
    print(f"[Encoder] Serial      = {msg.serial}")
    print(f"[Encoder] Country     = {msg.country} ({country_name(msg.country)})")
    print(f"[Encoder] Beacon type = {BEACON_TYPE_NAMES.get(msg.beacon_type)}")
    if msg.lat_deg is not None or msg.lon_deg is not None:
        print(f"[Encoder] Position    = {msg.lat_deg}, {msg.lon_deg}")
    else:
        print("[Encoder] Position    = (no-fix default)")
    print(f"[Encoder] Main hex    = {main_hex}")
    print(f"[Encoder] BCH parity  = {parity_hex}")
    print(f"[Encoder] Full 250b   = {full_hex}")
    print(f"[Encoder] 23-hex ID   = {beacon_id}")

    if args.out:
        params = ModulationParams(
            sample_rate=float(args.sample_rate),
            pulse=args.pulse,
            carrier_hz=float(args.carrier_hz),
            mode=args.mode,
        )
        signal = modulate(full_bits, params)
        write_wav(args.out, signal, args.sample_rate)
        n_ch = 2 if np.iscomplexobj(signal) else 1
        print(f"[Encoder] Wrote WAV   = {args.out} "
              f"({n_ch}-channel, {args.sample_rate} Hz, "
              f"{signal.size / args.sample_rate:.3f} s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
