"""
test_m8_eval.py — end-to-end evaluation of the full codec stack.

Exercises every beacon type through the full encode→modulate→demodulate→
decode chain, then adds AWGN and confirms the BCH decoder rescues modest
bit errors. This is the evaluation harness used during M8 hardening.

Run:  python3 test_m8_eval.py
"""

from __future__ import annotations

import os
import sys
import random

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "scripts")))

from sgb_common import (
    MAIN_FIELD_LENGTH,
    BEACON_TYPE_ELT, BEACON_TYPE_EPIRB, BEACON_TYPE_PLB, BEACON_TYPE_ELT_DT,
    VESSEL_ID_NONE, VESSEL_ID_MMSI, VESSEL_ID_CALLSIGN, VESSEL_ID_TAIL,
    VESSEL_ID_ICAO, VESSEL_ID_OPERATOR,
)
from sgb_message import (
    SGBMessage, parse_message, derive_23hex_id,
    build_rotating_g008, build_rotating_elt_dt, build_rotating_rls,
    build_rotating_national, build_rotating_cancellation,
)
from sgb_bch import bch_encode, bch_decode
from sgb_modulation import ModulationParams, modulate, demodulate


PASS = 0
FAIL = 0
def check(name, got, expected):
    global PASS, FAIL
    ok = got == expected
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"         expected: {expected!r}")
        print(f"         got     : {got!r}")
    if ok: PASS += 1
    else:  FAIL += 1


SCENARIOS = [
    dict(name="PLB distress w/ position",
         msg=SGBMessage(tac=100, serial=42, country=338, lat_deg=40.7128, lon_deg=-74.0060,
                        vessel_id_type=VESSEL_ID_NONE, beacon_type=BEACON_TYPE_PLB,
                        rotating=build_rotating_g008(elapsed_hours=2, altitude_m=10,
                                                     battery_code=6))),
    dict(name="EPIRB maritime w/ MMSI",
         msg=SGBMessage(tac=200, serial=1024, country=232, lat_deg=-33.87, lon_deg=151.21,
                        vessel_id_type=VESSEL_ID_MMSI,
                        vessel_id_params={"mmsi": 232987654},
                        beacon_type=BEACON_TYPE_EPIRB,
                        rotating=build_rotating_rls(capability_auto=True))),
    dict(name="ELT aviation w/ tail",
         msg=SGBMessage(tac=300, serial=77, country=366, lat_deg=37.774929, lon_deg=-122.419416,
                        vessel_id_type=VESSEL_ID_TAIL,
                        vessel_id_params={"tail": "N12345"},
                        beacon_type=BEACON_TYPE_ELT,
                        rotating=build_rotating_g008(altitude_m=11000))),
    dict(name="ELT(DT) w/ ICAO + operator",
         msg=SGBMessage(tac=512, serial=4321, country=366, lat_deg=38.8977, lon_deg=-77.0365,
                        vessel_id_type=VESSEL_ID_ICAO,
                        vessel_id_params={"icao": 0xABCDEF, "operator_code": "UAL"},
                        beacon_type=BEACON_TYPE_ELT_DT,
                        rotating=build_rotating_elt_dt(time_of_last_loc_s=60,
                                                       altitude_m=10000,
                                                       triggering_event=1))),
    dict(name="PLB self-test no-fix",
         msg=SGBMessage(tac=1, serial=1, country=366, lat_deg=None, lon_deg=None,
                        test_protocol=1, vessel_id_type=VESSEL_ID_NONE,
                        beacon_type=BEACON_TYPE_PLB,
                        rotating=build_rotating_g008())),
    dict(name="Operator-only aviation beacon",
         msg=SGBMessage(tac=9999, serial=1234, country=211, lat_deg=52.52, lon_deg=13.405,
                        vessel_id_type=VESSEL_ID_OPERATOR,
                        vessel_id_params={"operator_code": "DLH", "operator_serial": 321},
                        beacon_type=BEACON_TYPE_ELT_DT,
                        rotating=build_rotating_elt_dt(triggering_event=2))),
    dict(name="Callsign EPIRB w/ cancellation rotating",
         msg=SGBMessage(tac=555, serial=555, country=503, lat_deg=-35.28, lon_deg=149.13,
                        vessel_id_type=VESSEL_ID_CALLSIGN,
                        vessel_id_params={"callsign": "VKE1234"},
                        beacon_type=BEACON_TYPE_EPIRB,
                        rotating=build_rotating_cancellation(method=0b10))),
]


def _scenario_round_trip(name, msg, carrier_hz, pulse="rect"):
    main = msg.build()
    parity = bch_encode(main)
    codeword = main + parity
    expected_id = derive_23hex_id(main)

    params = ModulationParams(sample_rate=192_000.0, pulse=pulse,
                              carrier_hz=carrier_hz, mode="normal")
    sig = modulate(codeword, params)
    recovered, _ = demodulate(sig, sample_rate=params.sample_rate,
                              mode="normal", carrier_hz=carrier_hz)
    corrected, n_err, ok = bch_decode(recovered)
    recovered_main = corrected[:MAIN_FIELD_LENGTH]
    recovered_id = derive_23hex_id(recovered_main)
    recovered_parsed = parse_message(recovered_main)
    original_parsed = parse_message(main)

    check(f"{name}: codeword round-trip", recovered, codeword)
    check(f"{name}: BCH ok", ok, True)
    check(f"{name}: BCH errors == 0", n_err, 0)
    check(f"{name}: 23-hex ID preserved", recovered_id, expected_id)
    for key in ("tac", "serial", "country", "homing", "rls_function",
                "test_protocol", "beacon_type"):
        check(f"{name}: field {key}", recovered_parsed[key], original_parsed[key])


# ----------------------------------------------------------------------
print("[1] Clean round-trips (complex baseband, rectangular pulse)")
for sc in SCENARIOS:
    _scenario_round_trip(sc["name"], sc["msg"], carrier_hz=0.0, pulse="rect")

# ----------------------------------------------------------------------
print("\n[2] Clean round-trips (real passband, half-sine pulse, carrier 48 kHz)")
for sc in SCENARIOS:
    _scenario_round_trip(sc["name"] + " [RF+HS]", sc["msg"],
                         carrier_hz=48_000.0, pulse="half_sine")


# ----------------------------------------------------------------------
print("\n[3] AWGN robustness — BCH corrects 1..6 injected bit errors")
# Simulate the scenario where the channel introduces up to t=6 bit errors
# in the codeword. The BCH decoder must correct them, recovering the
# message cleanly. This does not test modem noise tolerance end-to-end but
# verifies the protection layer the modem is wrapped in.
rng = random.Random(202604)
for sc in SCENARIOS:
    main = sc["msg"].build()
    parity = bch_encode(main)
    codeword = main + parity
    for t in range(1, 7):
        flipped = list(codeword)
        for p in rng.sample(range(250), t):
            flipped[p] = "1" if flipped[p] == "0" else "0"
        received = "".join(flipped)
        corrected, n_err, ok = bch_decode(received)
        check(f"{sc['name']} + {t} flipped bits", (ok, n_err, corrected), (True, t, codeword))


# ----------------------------------------------------------------------
print("\n[4] Sanity: burst sample count at 192 kHz")
for sc in SCENARIOS[:2]:
    main = sc["msg"].build()
    codeword = main + bch_encode(main)
    sig = modulate(codeword, ModulationParams(sample_rate=192_000.0,
                                              carrier_hz=0.0, pulse="rect"))
    # 1 s + a few samples half-chip padding
    check(f"{sc['name']}: sample count >= 192000",
          sig.size >= 192_000, True)


print(f"\n==== M8 RESULTS: {PASS} passed, {FAIL} failed ====")
sys.exit(0 if FAIL == 0 else 1)
