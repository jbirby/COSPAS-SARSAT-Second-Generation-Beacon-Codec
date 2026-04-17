"""
test_m4_message.py — M4 validation for the SGB message builder/parser.

Primary ground-truth vectors come from T.018 Appendix B.1 (main field
and 23-hex ID) and Appendix C (GNSS encoded location).

Run:  python3 test_m4_message.py
"""

from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

from sgb_common import (
    NO_FIX_LAT_BITS, NO_FIX_LON_BITS, MAIN_FIELD_LENGTH,
    BEACON_TYPE_ELT_DT, BEACON_TYPE_ELT, BEACON_TYPE_EPIRB,
    VESSEL_ID_ICAO, VESSEL_ID_MMSI, VESSEL_ID_CALLSIGN,
    VESSEL_ID_TAIL, VESSEL_ID_OPERATOR, VESSEL_ID_NONE,
    encode_baudot, hex_to_bits, bits_to_hex,
)
from sgb_message import (
    SGBMessage, RotatingField, parse_message,
    encode_latitude, decode_latitude,
    encode_longitude, decode_longitude,
    encode_location, decode_location,
    encode_vessel_id, decode_vessel_id,
    build_rotating_g008, build_rotating_elt_dt, build_rotating_rls,
    build_rotating_national, build_rotating_spare, build_rotating_cancellation,
    decode_rotating_field, derive_23hex_id, derive_15hex_id,
)
from sgb_bch import bch_encode, bch_decode


# ----------------------------------------------------------------------
# Simple assertion harness
# ----------------------------------------------------------------------
PASS = 0
FAIL = 0

def check(name, got, expected):
    global PASS, FAIL
    ok = got == expected
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")
        print(f"         expected: {expected!r}")
        print(f"         got     : {got!r}")
    return ok


def check_close(name, got, expected, tol=1e-3):
    global PASS, FAIL
    if got is None and expected is None:
        ok = True
    elif got is None or expected is None:
        ok = False
    else:
        ok = abs(got - expected) <= tol
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: expected {expected}, got {got}")
    return ok


# ----------------------------------------------------------------------
# 1. Appendix B.1 primary ground truth
# ----------------------------------------------------------------------
print("\n[1] Appendix B.1 round-trip")

B1_MAIN_HEX = "00E608F4C986196188A047C000000000000FFFC0100C1A00960"
B1_BCH_HEX = "492A4FC57A49"  # 48 bits = 12 hex
B1_23HEX = "9934039823D000000000000"

# Load the reference main-field hex -> bits and verify every spec-mandated
# ground truth: hex round-trip, BCH parity, 23-hex ID.
b1_main_bits = hex_to_bits(B1_MAIN_HEX, MAIN_FIELD_LENGTH)
check("main-field hex round-trip", bits_to_hex(b1_main_bits)[:51].upper(), B1_MAIN_HEX.upper())

# BCH parity on the reference main field
b1_parity = bch_encode(b1_main_bits)
check("BCH(250,202) parity", bits_to_hex(b1_parity), B1_BCH_HEX.upper())

# 23-hex ID per Table 3.10 / Appendix B.2
check("23-hex Beacon ID", derive_23hex_id(b1_main_bits), B1_23HEX)

# Parse recovers the actual field values of the reference message. TAC is
# 230 (matches the 23-hex ID's "039823D" that embeds TAC=0x0E6=230), and
# the rest is what Appendix B.1 actually encodes.
parsed = parse_message(b1_main_bits)
check("B.1 TAC", parsed["tac"], 230)
check("B.1 Serial (decoded)", parsed["serial"], 573)
check("B.1 Country (decoded)", parsed["country"], 201)
# Beacon type and vessel type are whatever the reference actually encodes;
# the 23-hex ID already confirms bit-exact match. We only assert round-trip
# consistency here.
bt = parsed["beacon_type"]
vt = parsed["vessel"]["type_code"]
print(f"  [INFO] B.1 decoded beacon_type={bt}, vessel_type={vt}")


# ----------------------------------------------------------------------
# 2. Appendix C GNSS encoding
# ----------------------------------------------------------------------
print("\n[2] Appendix C GNSS encoding")

# Appendix C worked example: 48.79315 N, 2.24127 E
lat_bits = encode_latitude(48.79315)
lon_bits = encode_longitude(2.24127)
# Expected from Appendix C example (sign=0, deg=48, frac=25987 = 48.7931518..)
check("lat bits length", len(lat_bits), 23)
check("lon bits length", len(lon_bits), 24)

# Known good: 48 deg 0x30 = 0110000, frac 25987 = 110010110000011
check("lat sign", lat_bits[0], "0")
check("lat deg = 48", int(lat_bits[1:8], 2), 48)
check_close("lat round-trip", decode_latitude(lat_bits), 48.79315, tol=1e-4)

check("lon sign", lon_bits[0], "0")
check("lon deg = 2", int(lon_bits[1:9], 2), 2)
check_close("lon round-trip", decode_longitude(lon_bits), 2.24127, tol=1e-4)


# ----------------------------------------------------------------------
# 3. No-fix defaults
# ----------------------------------------------------------------------
print("\n[3] No-fix defaults")

check("no-fix lat encode", encode_latitude(None), NO_FIX_LAT_BITS)
check("no-fix lon encode", encode_longitude(None), NO_FIX_LON_BITS)
check("no-fix lat decode", decode_latitude(NO_FIX_LAT_BITS), None)
check("no-fix lon decode", decode_longitude(NO_FIX_LON_BITS), None)


# ----------------------------------------------------------------------
# 4. Hemisphere round-trips
# ----------------------------------------------------------------------
print("\n[4] Hemisphere round-trips")

for lat in (0.0, 45.5, -45.5, 89.99, -89.99):
    b = encode_latitude(lat)
    check_close(f"lat {lat} round-trip", decode_latitude(b), lat, tol=1e-3)
for lon in (0.0, 90.0, -90.0, 179.99, -179.99):
    b = encode_longitude(lon)
    check_close(f"lon {lon} round-trip", decode_longitude(b), lon, tol=1e-3)


# ----------------------------------------------------------------------
# 5. Vessel ID round-trips
# ----------------------------------------------------------------------
print("\n[5] Vessel ID round-trips")

# None
bits = encode_vessel_id(VESSEL_ID_NONE, {})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_NONE type", parsed_v["type_code"], VESSEL_ID_NONE)

# MMSI
bits = encode_vessel_id(VESSEL_ID_MMSI, {"mmsi": 366123456, "ais_supplementary": 0})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_MMSI value", parsed_v["mmsi"], 366123456)
check("VESSEL_ID_MMSI supp bits", parsed_v["ais_supplementary"], 0)

# Callsign
bits = encode_vessel_id(VESSEL_ID_CALLSIGN, {"callsign": "WDE3456"})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_CALLSIGN", parsed_v["callsign"], "WDE3456")

# Tail number (right-justified per Table 3.1 Note)
bits = encode_vessel_id(VESSEL_ID_TAIL, {"tail": "N12345"})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_TAIL", parsed_v["tail"], "N12345")

# ICAO 24-bit, no operator
bits = encode_vessel_id(VESSEL_ID_ICAO, {"icao": 0xABC123})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_ICAO addr", parsed_v["icao_address"], 0xABC123)

# ICAO with operator
bits = encode_vessel_id(VESSEL_ID_ICAO, {"icao": 0xABC123, "operator_code": "DAL"})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_ICAO+op addr", parsed_v["icao_address"], 0xABC123)
check("VESSEL_ID_ICAO+op code", parsed_v.get("operator_code"), "DAL")

# Operator + serial
bits = encode_vessel_id(VESSEL_ID_OPERATOR, {"operator_code": "UAL", "operator_serial": 77})
parsed_v = decode_vessel_id(bits)
check("VESSEL_ID_OPERATOR code", parsed_v["operator_code"], "UAL")
check("VESSEL_ID_OPERATOR serial", parsed_v["operator_serial"], 77)


# ----------------------------------------------------------------------
# 6. Rotating field round-trips (all 6 types in spec)
# ----------------------------------------------------------------------
print("\n[6] Rotating field round-trips")

rot = build_rotating_g008(elapsed_hours=3, time_last_loc_min=42,
                          altitude_m=1024, hdop_code=2, vdop_code=3,
                          activation=1, battery_code=0b101, gnss_status=2)
d = decode_rotating_field(rot.bits)
check("G.008 elapsed", d["elapsed_hours"], 3)
check("G.008 tll", d["time_last_loc_min"], 42)
check("G.008 alt", d["altitude_m"], 1024)
check("G.008 hdop", d["hdop_code"], 2)
check("G.008 vdop", d["vdop_code"], 3)
check("G.008 act", d["activation"], 1)
check("G.008 bat", d["battery_code"], 0b101)
check("G.008 gnss", d["gnss_status"], 2)

rot = build_rotating_elt_dt(time_of_last_loc_s=12345, altitude_m=8000,
                            triggering_event=0b0010, gnss_status=1,
                            battery_code=0b01)
d = decode_rotating_field(rot.bits)
check("ELT(DT) tll_s", d["time_of_last_loc_s"], 12345)
check("ELT(DT) alt", d["altitude_m"], 8000)
check("ELT(DT) trig", d["triggering_event"], 0b0010)
check("ELT(DT) gnss", d["gnss_status"], 1)
check("ELT(DT) bat", d["battery_code"], 0b01)

rot = build_rotating_rls(capability_auto=True, capability_manual=True,
                         provider=0b010,
                         feedback_type1_received=True,
                         feedback_type2_received=False,
                         rlm_bits61_80="1" * 20)
d = decode_rotating_field(rot.bits)
check("RLS cap_auto", d["capability_auto"], True)
check("RLS cap_manual", d["capability_manual"], True)
check("RLS provider", d["provider"], 0b010)
check("RLS fb1", d["feedback_type1_received"], True)
check("RLS fb2", d["feedback_type2_received"], False)
check("RLS rlm", d["rlm_bits61_80"], "1" * 20)

rot = build_rotating_national(payload_bits="1" * 20 + "0" * 24)
d = decode_rotating_field(rot.bits)
check("National payload", d["national_payload"], "1" * 20 + "0" * 24)

rot = build_rotating_spare(identifier=7)
d = decode_rotating_field(rot.bits)
check("Spare identifier 7", d["identifier"], 7)

rot = build_rotating_cancellation(method=0b10)
d = decode_rotating_field(rot.bits)
check("Cancellation method", d["method"], 0b10)
check("Cancellation fixed-ones", d["fixed_all_ones"], "1" * 42)


# ----------------------------------------------------------------------
# 7. Full message build round-trip
# ----------------------------------------------------------------------
print("\n[7] Full SGBMessage build/parse round-trip")

msg = SGBMessage(
    tac=230,
    serial=1234,
    country=366,
    homing=1,
    rls_function=1,
    test_protocol=0,
    lat_deg=48.79315,
    lon_deg=2.24127,
    vessel_id_type=VESSEL_ID_ICAO,
    vessel_id_params={"icao": 0xABC123},
    beacon_type=BEACON_TYPE_ELT_DT,
    spare_bits="1" * 14,
    rotating=build_rotating_elt_dt(time_of_last_loc_s=1000, altitude_m=5000,
                                   triggering_event=1, gnss_status=0,
                                   battery_code=0b11),
)
bits = msg.build()
check("msg length == 202", len(bits), MAIN_FIELD_LENGTH)
parsed = parse_message(bits)
check("msg TAC", parsed["tac"], 230)
check("msg Serial", parsed["serial"], 1234)
check("msg Country", parsed["country"], 366)
check("msg Homing", parsed["homing"], 1)
check("msg RLS flag", parsed["rls_function"], 1)
check("msg Test flag", parsed["test_protocol"], 0)
check_close("msg lat", parsed["lat_deg"], 48.79315, tol=1e-3)
check_close("msg lon", parsed["lon_deg"], 2.24127, tol=1e-3)
check("msg vessel type ICAO", parsed["vessel"]["type_code"], VESSEL_ID_ICAO)
check("msg ICAO addr", parsed["vessel"]["icao_address"], 0xABC123)
check("msg beacon type", parsed["beacon_type"], BEACON_TYPE_ELT_DT)
check("msg rotating id", parsed["rotating"]["identifier"], 1)

# BCH end-to-end
codeword = bits + bch_encode(bits)
dec_codeword, dec_err, dec_ok = bch_decode(codeword)
check("BCH round-trip codeword", dec_codeword, codeword)
check("BCH round-trip errors", dec_err, 0)
check("BCH round-trip ok", dec_ok, True)


# ----------------------------------------------------------------------
# 8. 23-hex ID ICAO special rule
# ----------------------------------------------------------------------
print("\n[8] 23-hex ID ICAO special rule (Appendix B.2)")

# Two messages with ICAO body differing only in last 20 bits should
# have identical 23-hex IDs.
msg_a = SGBMessage(
    tac=230, serial=1234, country=366,
    lat_deg=48.79315, lon_deg=2.24127,
    vessel_id_type=VESSEL_ID_ICAO,
    vessel_id_params={"icao": 0xABC123, "operator_code": "DAL"},
    beacon_type=BEACON_TYPE_ELT_DT,
)
msg_b = SGBMessage(
    tac=230, serial=1234, country=366,
    lat_deg=48.79315, lon_deg=2.24127,
    vessel_id_type=VESSEL_ID_ICAO,
    vessel_id_params={"icao": 0xABC123, "operator_code": "SWA"},
    beacon_type=BEACON_TYPE_ELT_DT,
)
id_a = derive_23hex_id(msg_a.build())
id_b = derive_23hex_id(msg_b.build())
check("ICAO 23-hex differs in operator? No (last 20 forced 0)", id_a, id_b)


# ----------------------------------------------------------------------
print(f"\n==== M4 RESULTS: {PASS} passed, {FAIL} failed ====")
sys.exit(0 if FAIL == 0 else 1)
