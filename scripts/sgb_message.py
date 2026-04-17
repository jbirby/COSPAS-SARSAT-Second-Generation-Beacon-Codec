"""
sgb_message.py — COSPAS-SARSAT SGB message builder, parser, and 23-hex
beacon ID derivation.

Specification reference: C/S T.018 Rev 7, Section 3 (Message Structure),
Tables 3.1-3.10, Appendix C (GNSS encoded location), Appendix B.2 (23-hex
ID worked example).

The message layout (Table 3.1) is:

    Bits 1-16     TAC Number (16 bits)
    Bits 17-30    Serial Number (14 bits)
    Bits 31-40    Country code (10 bits, ITU MID)
    Bit  41       Status of homing device (1 bit)
    Bit  42       RLS function flag (1 bit)
    Bit  43       Test protocol flag (1 bit)
    Bits 44-90    Encoded GNSS location (47 bits: 23 lat + 24 lon)
    Bits 91-93    Vessel ID type selector (3 bits)
    Bits 94-137   Vessel ID (44 bits)
    Bits 138-140  Beacon Type (3 bits)
    Bits 141-154  Spare (14 bits)
    Bits 155-158  Rotating field identifier (4 bits)
    Bits 159-202  Rotating field payload (44 bits)
    Bits 203-250  BCH(250,202) parity (48 bits)

This module handles bits 1-202 plus the 23-hex ID derivation; BCH parity
is appended by sgb_bch.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sgb_common import (
    MAIN_FIELD_LENGTH,
    BEACON_TYPE_ELT, BEACON_TYPE_EPIRB, BEACON_TYPE_PLB,
    BEACON_TYPE_ELT_DT, BEACON_TYPE_SYSTEM, BEACON_TYPE_NAMES,
    VESSEL_ID_NONE, VESSEL_ID_MMSI, VESSEL_ID_CALLSIGN, VESSEL_ID_TAIL,
    VESSEL_ID_ICAO, VESSEL_ID_OPERATOR, VESSEL_ID_NAMES,
    ROT_G008, ROT_ELT_DT, ROT_RLS, ROT_NATIONAL, ROT_CANCELLATION,
    ROT_NAMES,
    NO_FIX_LAT_BITS, NO_FIX_LON_BITS,
    encode_baudot, decode_baudot,
    int_to_bits, bits_to_int, hex_to_bits, bits_to_hex,
    assemble_bits, country_name,
)


# ---------------------------------------------------------------------------
# GNSS Encoded Location (Appendix C)
# ---------------------------------------------------------------------------

LAT_FRAC_WIDTH = 15
LON_FRAC_WIDTH = 15
LAT_DEG_WIDTH = 7    # 0..90
LON_DEG_WIDTH = 8    # 0..180


def encode_latitude(lat_deg: Optional[float]) -> str:
    """Encode a decimal latitude into 23 bits (bits 44-66).

    Returns the no-fix default pattern if lat_deg is None or NaN.
    """
    if lat_deg is None or (isinstance(lat_deg, float) and math.isnan(lat_deg)):
        return NO_FIX_LAT_BITS
    if not -90.0 <= lat_deg <= 90.0:
        raise ValueError(f"latitude {lat_deg} out of range [-90, 90]")
    sign = "1" if lat_deg < 0 else "0"
    mag = abs(lat_deg)
    deg = int(mag)
    frac = mag - deg
    frac_n = int(round(frac * (1 << LAT_FRAC_WIDTH)))
    # Handle the pathological case where rounding pushes to the next degree
    if frac_n == (1 << LAT_FRAC_WIDTH):
        frac_n = 0
        deg += 1
    if deg > 90:
        deg = 90
        frac_n = 0
    return assemble_bits([
        sign,
        int_to_bits(deg, LAT_DEG_WIDTH),
        int_to_bits(frac_n, LAT_FRAC_WIDTH),
    ])


def encode_longitude(lon_deg: Optional[float]) -> str:
    """Encode a decimal longitude into 24 bits (bits 67-90)."""
    if lon_deg is None or (isinstance(lon_deg, float) and math.isnan(lon_deg)):
        return NO_FIX_LON_BITS
    if not -180.0 <= lon_deg <= 180.0:
        raise ValueError(f"longitude {lon_deg} out of range [-180, 180]")
    sign = "1" if lon_deg < 0 else "0"
    mag = abs(lon_deg)
    deg = int(mag)
    frac = mag - deg
    frac_n = int(round(frac * (1 << LON_FRAC_WIDTH)))
    if frac_n == (1 << LON_FRAC_WIDTH):
        frac_n = 0
        deg += 1
    if deg > 180:
        deg = 180
        frac_n = 0
    return assemble_bits([
        sign,
        int_to_bits(deg, LON_DEG_WIDTH),
        int_to_bits(frac_n, LON_FRAC_WIDTH),
    ])


def decode_latitude(bits: str) -> Optional[float]:
    """Decode 23 bits into decimal degrees, or None if no-fix default."""
    if len(bits) != 23:
        raise ValueError(f"latitude expects 23 bits, got {len(bits)}")
    if bits == NO_FIX_LAT_BITS:
        return None
    sign_bit = bits[0]
    deg = bits_to_int(bits[1:1 + LAT_DEG_WIDTH])
    frac_n = bits_to_int(bits[1 + LAT_DEG_WIDTH:])
    mag = deg + frac_n / (1 << LAT_FRAC_WIDTH)
    return -mag if sign_bit == "1" else mag


def decode_longitude(bits: str) -> Optional[float]:
    if len(bits) != 24:
        raise ValueError(f"longitude expects 24 bits, got {len(bits)}")
    if bits == NO_FIX_LON_BITS:
        return None
    sign_bit = bits[0]
    deg = bits_to_int(bits[1:1 + LON_DEG_WIDTH])
    frac_n = bits_to_int(bits[1 + LON_DEG_WIDTH:])
    mag = deg + frac_n / (1 << LON_FRAC_WIDTH)
    return -mag if sign_bit == "1" else mag


def encode_location(lat_deg: Optional[float], lon_deg: Optional[float]) -> str:
    return encode_latitude(lat_deg) + encode_longitude(lon_deg)


def decode_location(bits: str) -> Tuple[Optional[float], Optional[float]]:
    if len(bits) != 47:
        raise ValueError(f"location expects 47 bits, got {len(bits)}")
    return decode_latitude(bits[:23]), decode_longitude(bits[23:])


# ---------------------------------------------------------------------------
# Vessel ID encoding (bits 91-137; 3-bit type selector + 44-bit body)
# ---------------------------------------------------------------------------

VESSEL_NO_AIS_DEFAULT_14 = "10101010101010"  # supplementary, used when MMSI not AIS


def encode_vessel_id(type_code: int, params: Dict[str, Any]) -> str:
    """Return 47 bits: 3-bit type selector + 44-bit ID body."""
    if not 0 <= type_code <= 0b111:
        raise ValueError(f"vessel ID type {type_code} out of range")
    type_bits = int_to_bits(type_code, 3)
    if type_code == VESSEL_ID_NONE:
        body = "0" * 44
    elif type_code == VESSEL_ID_MMSI:
        mmsi = int(params.get("mmsi", 0))
        if not 0 <= mmsi < (1 << 30):
            raise ValueError(f"MMSI {mmsi} does not fit in 30 bits")
        supp = params.get("ais_supplementary")
        if supp is None:
            supp_bits = VESSEL_NO_AIS_DEFAULT_14
        else:
            supp_bits = int_to_bits(int(supp), 14)
        body = int_to_bits(mmsi, 30) + supp_bits
    elif type_code == VESSEL_ID_CALLSIGN:
        callsign = str(params.get("callsign", "")).upper()
        # 7 characters * 6 bits = 42 bits; pad to 44 with two spare 0s
        body = encode_baudot(callsign, 7, left_justify=True) + "00"
    elif type_code == VESSEL_ID_TAIL:
        tail = str(params.get("tail", "")).upper()
        body = encode_baudot(tail, 7, left_justify=False) + "00"
    elif type_code == VESSEL_ID_ICAO:
        icao = int(params.get("icao", 0))
        if not 0 <= icao < (1 << 24):
            raise ValueError(f"ICAO address {icao} does not fit in 24 bits")
        operator = params.get("operator_code")
        if operator is None:
            # 24-bit ICAO + 20 spare zeros
            body = int_to_bits(icao, 24) + "0" * 20
        else:
            op = str(operator).upper()[:3].ljust(3, " ")
            # 3 ICAO-letter operator code uses 5 bits per letter (A=0..Z=25,
            # space=26, hyphen=27). Unspecified chars -> 27 (hyphen).
            operator_bits = _encode_operator(op)
            body = int_to_bits(icao, 24) + operator_bits + "0" * 5
    elif type_code == VESSEL_ID_OPERATOR:
        op = str(params.get("operator_code", "")).upper()[:3].ljust(3, " ")
        serial = int(params.get("operator_serial", 0))
        if not 0 <= serial < (1 << 12):
            raise ValueError(f"operator serial {serial} does not fit in 12 bits")
        body = _encode_operator(op) + int_to_bits(serial, 12) + "1" * 17
    else:
        body = "0" * 44
    if len(body) != 44:
        raise AssertionError(
            f"internal: vessel ID body length = {len(body)} (should be 44) for "
            f"type {type_code}"
        )
    return type_bits + body


def _baudot_strip_pad(bits: str, from_left: bool = True) -> str:
    """Strip leading or trailing '100100' (Baudot pad) 6-bit chunks.

    Modified Baudot 100100 is the padding / space code, ambiguous with the
    digit '9'. For padded fields (callsign, tail) we strip the pad chunks
    from the padding side before decoding so that spurious '9' characters
    do not appear in the recovered identifier.
    """
    chunks = [bits[i:i + 6] for i in range(0, len(bits), 6)]
    if from_left:
        while chunks and chunks[0] == "100100":
            chunks.pop(0)
    else:
        while chunks and chunks[-1] == "100100":
            chunks.pop()
    return "".join(chunks)


def _encode_operator(text: str) -> str:
    """Encode a 3-letter aircraft operator code into 15 bits (5 per char).

    Alphabet: A-Z (0-25), space (26), hyphen (27), then reserved/space.
    """
    mapping: Dict[str, int] = {}
    for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
        mapping[ch] = i
    mapping[" "] = 26
    mapping["-"] = 27
    bits = []
    for ch in text[:3]:
        v = mapping.get(ch, 26)  # unknown -> space
        bits.append(int_to_bits(v, 5))
    return "".join(bits)


def _decode_operator(bits: str) -> str:
    if len(bits) != 15:
        return ""
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = []
    for i in range(3):
        v = bits_to_int(bits[5*i:5*(i+1)])
        if v < 26:
            out.append(alphabet[v])
        elif v == 26:
            out.append(" ")
        elif v == 27:
            out.append("-")
        else:
            out.append("?")
    return "".join(out).rstrip()


def decode_vessel_id(bits: str) -> Dict[str, Any]:
    """Decode the 47-bit vessel-ID block (type + body)."""
    if len(bits) != 47:
        raise ValueError(f"vessel ID expects 47 bits, got {len(bits)}")
    type_code = bits_to_int(bits[:3])
    body = bits[3:]
    result: Dict[str, Any] = {
        "type_code": type_code,
        "type_name": VESSEL_ID_NAMES.get(type_code, f"Unknown {type_code}"),
    }
    if type_code == VESSEL_ID_NONE:
        result["identity"] = None
    elif type_code == VESSEL_ID_MMSI:
        result["mmsi"] = bits_to_int(body[:30])
        result["ais_supplementary_bits"] = body[30:]
        result["ais_supplementary"] = bits_to_int(body[30:])
        if body[30:] == VESSEL_NO_AIS_DEFAULT_14:
            result["ais_supplementary_note"] = "no-AIS default"
    elif type_code == VESSEL_ID_CALLSIGN:
        # Callsign is left-justified; pad chunks live on the right.
        result["callsign"] = decode_baudot(_baudot_strip_pad(body[:42], from_left=False))
        result["spare"] = body[42:]
    elif type_code == VESSEL_ID_TAIL:
        # Tail is right-justified; pad chunks live on the left.
        result["tail"] = decode_baudot(_baudot_strip_pad(body[:42], from_left=True))
        result["spare"] = body[42:]
    elif type_code == VESSEL_ID_ICAO:
        result["icao_address"] = bits_to_int(body[:24])
        op_bits = body[24:24+15]
        spare = body[24+15:]
        if spare == "00000" and op_bits != "0" * 15:
            result["operator_code"] = _decode_operator(op_bits)
        result["spare"] = spare
    elif type_code == VESSEL_ID_OPERATOR:
        result["operator_code"] = _decode_operator(body[:15])
        result["operator_serial"] = bits_to_int(body[15:15+12])
        result["spare"] = body[15+12:]
    else:
        result["raw_body"] = body
    return result


# ---------------------------------------------------------------------------
# Rotating fields (Tables 3.3-3.8)
# ---------------------------------------------------------------------------

@dataclass
class RotatingField:
    identifier: int
    name: str
    bits: str  # 48 bits total, including identifier


def build_rotating_g008(
    elapsed_hours: int = 0,
    time_last_loc_min: int = 2047,
    altitude_m: Optional[float] = None,
    hdop_code: int = 0,
    vdop_code: int = 0,
    activation: int = 0,
    battery_code: int = 0b111,
    gnss_status: int = 0,
) -> RotatingField:
    """Table 3.3 — G.008 Objective Requirements."""
    elapsed = min(max(int(elapsed_hours), 0), 63)
    tll = min(max(int(time_last_loc_min), 0), 2047)
    if altitude_m is None:
        alt_code = int("1" * 10, 2)
    elif altitude_m <= -400:
        alt_code = 0
    else:
        # 16 m steps, offset so code 0 = -400 m, code 1 = -384 m, ...
        alt_code = min(int(round((altitude_m + 400) / 16.0)), 1022)
    hdop = min(max(int(hdop_code), 0), 15)
    vdop = min(max(int(vdop_code), 0), 15)
    act = min(max(int(activation), 0), 3)
    bat = min(max(int(battery_code), 0), 7)
    gnss = min(max(int(gnss_status), 0), 3)
    bits = assemble_bits([
        int_to_bits(ROT_G008, 4),         # 155-158
        int_to_bits(elapsed, 6),          # 159-164
        int_to_bits(tll, 11),             # 165-175
        int_to_bits(alt_code, 10),        # 176-185
        int_to_bits(hdop, 4),             # 186-189
        int_to_bits(vdop, 4),             # 190-193
        int_to_bits(act, 2),              # 194-195
        int_to_bits(bat, 3),              # 196-198
        int_to_bits(gnss, 2),             # 199-200
        "00",                             # 201-202 spare
    ])
    return RotatingField(ROT_G008, ROT_NAMES[ROT_G008], bits)


def build_rotating_elt_dt(
    time_of_last_loc_s: int = (1 << 17) - 1,
    altitude_m: Optional[float] = None,
    triggering_event: int = 0b0001,
    gnss_status: int = 0,
    battery_code: int = 0b11,
) -> RotatingField:
    """Table 3.4 — ELT(DT) In-Flight Emergency."""
    t = min(max(int(time_of_last_loc_s), 0), (1 << 17) - 1)
    if altitude_m is None:
        alt_code = int("1" * 10, 2)
    elif altitude_m <= -400:
        alt_code = 0
    else:
        alt_code = min(int(round((altitude_m + 400) / 16.0)), 1022)
    bits = assemble_bits([
        int_to_bits(ROT_ELT_DT, 4),           # 155-158
        int_to_bits(t, 17),                   # 159-175
        int_to_bits(alt_code, 10),            # 176-185
        int_to_bits(int(triggering_event), 4),# 186-189
        int_to_bits(int(gnss_status), 2),     # 190-191
        int_to_bits(int(battery_code), 2),    # 192-193
        "0" * 9,                              # 194-202 spare
    ])
    return RotatingField(ROT_ELT_DT, ROT_NAMES[ROT_ELT_DT], bits)


def build_rotating_rls(
    capability_auto: bool = True,
    capability_manual: bool = False,
    provider: int = 0b001,
    feedback_type1_received: bool = False,
    feedback_type2_received: bool = False,
    rlm_bits61_80: str = "0" * 20,
) -> RotatingField:
    """Table 3.5 — RLS. ``rlm_bits61_80`` must be a 20-bit string."""
    if len(rlm_bits61_80) != 20 or not all(c in "01" for c in rlm_bits61_80):
        raise ValueError("rlm_bits61_80 must be a 20-character bit string")
    cap_bits = (
        ("1" if capability_auto else "0")
        + ("1" if capability_manual else "0")
        + "0000"
    )
    feedback = (
        ("1" if feedback_type1_received else "0")
        + ("1" if feedback_type2_received else "0")
        + rlm_bits61_80
    )
    bits = assemble_bits([
        int_to_bits(ROT_RLS, 4),              # 155-158
        "00",                                 # 159-160 unassigned
        cap_bits,                             # 161-166 capability
        int_to_bits(int(provider), 3),        # 167-169
        feedback,                             # 170-191
        "0" * 11,                             # 192-202 unassigned
    ])
    return RotatingField(ROT_RLS, ROT_NAMES[ROT_RLS], bits)


def build_rotating_national(payload_bits: str = "0" * 44) -> RotatingField:
    """Table 3.6 — National Use; 44 arbitrary payload bits."""
    if len(payload_bits) != 44 or not all(c in "01" for c in payload_bits):
        raise ValueError("national payload must be 44 bits")
    bits = int_to_bits(ROT_NATIONAL, 4) + payload_bits
    return RotatingField(ROT_NATIONAL, ROT_NAMES[ROT_NATIONAL], bits)


def build_rotating_spare(identifier: int = 4) -> RotatingField:
    """Table 3.7 — spare identifiers 4-14."""
    if not 4 <= identifier <= 14:
        raise ValueError("spare rotating field identifier must be in 4..14")
    bits = int_to_bits(identifier, 4) + "0" * 44
    return RotatingField(identifier, ROT_NAMES[identifier], bits)


def build_rotating_cancellation(method: int = 0b10) -> RotatingField:
    """Table 3.8 — Cancellation. ``method``: 00 spare, 01 auto-external,
    10 manual, 11 spare."""
    bits = assemble_bits([
        int_to_bits(ROT_CANCELLATION, 4),  # 155-158
        "1" * 42,                          # 159-200 fixed all-ones
        int_to_bits(int(method) & 0b11, 2),  # 201-202
    ])
    return RotatingField(ROT_CANCELLATION, ROT_NAMES[ROT_CANCELLATION], bits)


def decode_rotating_field(bits: str) -> Dict[str, Any]:
    """Decode a 48-bit rotating field block into a structured dict."""
    if len(bits) != 48:
        raise ValueError(f"rotating field expects 48 bits, got {len(bits)}")
    identifier = bits_to_int(bits[:4])
    out: Dict[str, Any] = {
        "identifier": identifier,
        "name": ROT_NAMES.get(identifier, f"Unknown {identifier}"),
        "raw_bits": bits,
    }
    body = bits[4:]
    if identifier == ROT_G008:
        out["elapsed_hours"] = bits_to_int(body[0:6])
        out["time_last_loc_min"] = bits_to_int(body[6:17])
        alt_code = bits_to_int(body[17:27])
        if alt_code == (1 << 10) - 1:
            out["altitude_m"] = None
        elif alt_code == 0:
            out["altitude_m"] = -400
        else:
            out["altitude_m"] = -400 + alt_code * 16
        out["hdop_code"] = bits_to_int(body[27:31])
        out["vdop_code"] = bits_to_int(body[31:35])
        out["activation"] = bits_to_int(body[35:37])
        out["battery_code"] = bits_to_int(body[37:40])
        out["gnss_status"] = bits_to_int(body[40:42])
        out["spare"] = body[42:44]
    elif identifier == ROT_ELT_DT:
        out["time_of_last_loc_s"] = bits_to_int(body[0:17])
        alt_code = bits_to_int(body[17:27])
        out["altitude_m"] = None if alt_code == (1 << 10) - 1 else (
            -400 if alt_code == 0 else -400 + alt_code * 16
        )
        out["triggering_event"] = bits_to_int(body[27:31])
        out["gnss_status"] = bits_to_int(body[31:33])
        out["battery_code"] = bits_to_int(body[33:35])
        out["spare"] = body[35:]
    elif identifier == ROT_RLS:
        out["unassigned_159_160"] = body[0:2]
        cap = body[2:8]
        out["capability_auto"] = cap[0] == "1"
        out["capability_manual"] = cap[1] == "1"
        out["capability_reserved"] = cap[2:]
        out["provider"] = bits_to_int(body[8:11])
        out["feedback_type1_received"] = body[11] == "1"
        out["feedback_type2_received"] = body[12] == "1"
        out["rlm_bits61_80"] = body[13:33]
        out["unassigned_192_202"] = body[33:]
    elif identifier == ROT_NATIONAL:
        out["national_payload"] = body
    elif identifier == ROT_CANCELLATION:
        out["fixed_all_ones"] = body[:42]
        out["method"] = bits_to_int(body[42:])
    else:
        out["raw_payload"] = body
    return out


# ---------------------------------------------------------------------------
# Main-field builder and parser
# ---------------------------------------------------------------------------

@dataclass
class SGBMessage:
    """Structured 202-bit SGB main field + rotating field view."""
    tac: int = 0
    serial: int = 0
    country: int = 0
    homing: int = 0
    rls_function: int = 0
    test_protocol: int = 0
    lat_deg: Optional[float] = None
    lon_deg: Optional[float] = None
    vessel_id_type: int = VESSEL_ID_NONE
    vessel_id_params: Dict[str, Any] = field(default_factory=dict)
    beacon_type: int = BEACON_TYPE_ELT
    spare_bits: str = "1" * 14
    rotating: Optional[RotatingField] = None

    def build(self) -> str:
        """Return the 202-bit message string (main field + rotating field)."""
        if not 0 <= self.tac < (1 << 16):
            raise ValueError(f"TAC {self.tac} does not fit in 16 bits")
        if not 0 <= self.serial < (1 << 14):
            raise ValueError(f"serial {self.serial} does not fit in 14 bits")
        if not 0 <= self.country < (1 << 10):
            raise ValueError(f"country {self.country} does not fit in 10 bits")
        if self.rotating is None:
            rot = build_rotating_g008()
        else:
            rot = self.rotating
        if len(self.spare_bits) != 14 or not all(c in "01" for c in self.spare_bits):
            raise ValueError("spare_bits must be a 14-bit string")
        vessel_bits = encode_vessel_id(self.vessel_id_type, self.vessel_id_params)
        location_bits = encode_location(self.lat_deg, self.lon_deg)
        parts = [
            int_to_bits(self.tac, 16),
            int_to_bits(self.serial, 14),
            int_to_bits(self.country, 10),
            int_to_bits(self.homing & 1, 1),
            int_to_bits(self.rls_function & 1, 1),
            int_to_bits(self.test_protocol & 1, 1),
            location_bits,               # 47 bits
            vessel_bits,                 # 47 bits (3 type + 44 body)
            int_to_bits(self.beacon_type & 0b111, 3),
            self.spare_bits,             # 14 bits
            rot.bits,                    # 48 bits
        ]
        bits = assemble_bits(parts)
        if len(bits) != MAIN_FIELD_LENGTH:
            raise AssertionError(
                f"internal: message length = {len(bits)} (expected {MAIN_FIELD_LENGTH})"
            )
        return bits


def parse_message(bits: str) -> Dict[str, Any]:
    """Parse a 202-bit SGB main field + rotating field into a dict."""
    if len(bits) != MAIN_FIELD_LENGTH:
        raise ValueError(
            f"parse_message expects {MAIN_FIELD_LENGTH} bits, got {len(bits)}"
        )
    tac = bits_to_int(bits[0:16])
    serial = bits_to_int(bits[16:30])
    country = bits_to_int(bits[30:40])
    homing = bits_to_int(bits[40:41])
    rls_flag = bits_to_int(bits[41:42])
    test_flag = bits_to_int(bits[42:43])
    location_bits = bits[43:90]  # 47 bits
    lat, lon = decode_location(location_bits)
    vessel_bits = bits[90:137]
    vessel = decode_vessel_id(vessel_bits)
    beacon_type = bits_to_int(bits[137:140])
    spare = bits[140:154]
    rotating_bits = bits[154:202]
    rotating = decode_rotating_field(rotating_bits)
    return {
        "tac": tac,
        "serial": serial,
        "country": country,
        "country_name": country_name(country),
        "homing": homing,
        "rls_function": rls_flag,
        "test_protocol": test_flag,
        "lat_deg": lat,
        "lon_deg": lon,
        "location_bits": location_bits,
        "vessel": vessel,
        "beacon_type": beacon_type,
        "beacon_type_name": BEACON_TYPE_NAMES.get(beacon_type, f"Unknown {beacon_type}"),
        "spare": spare,
        "rotating": rotating,
    }


# ---------------------------------------------------------------------------
# 23-hex Beacon ID (Table 3.10, Appendix B.2)
# ---------------------------------------------------------------------------

def derive_23hex_id(main_bits: str) -> str:
    """Derive the 23-hex Beacon ID (never transmitted) from the 202-bit
    main field. Returns a 23-character upper-case hex string.
    """
    if len(main_bits) != MAIN_FIELD_LENGTH:
        raise ValueError(
            f"derive_23hex_id expects {MAIN_FIELD_LENGTH} bits, got {len(main_bits)}"
        )
    tac = main_bits[0:16]
    serial = main_bits[16:30]
    country = main_bits[30:40]
    test_flag = main_bits[42:43]
    vessel_type = main_bits[90:93]
    vessel_body = main_bits[93:137]
    # When vessel type = 100 (ICAO), bits 118-137 are treated as 0 for ID
    # computation (message bits 118-137 == vessel_body[24:44]).
    if vessel_type == "100":
        vessel_body = vessel_body[:24] + "0" * 20
    id_bits = assemble_bits([
        "1",           # fixed
        country,       # 10 bits
        "101",         # fixed bits 12-14
        tac,           # 16 bits
        serial,        # 14 bits
        test_flag,     # 1 bit
        vessel_type,   # 3 bits
        vessel_body,   # 44 bits
    ])
    if len(id_bits) != 92:
        raise AssertionError(
            f"internal: 23-hex ID length = {len(id_bits)} (expected 92)"
        )
    return bits_to_hex(id_bits)


def derive_15hex_id(main_bits: str) -> str:
    """Return the first 15 hex characters of the 23-hex ID."""
    return derive_23hex_id(main_bits)[:15]


__all__ = [name for name in globals() if not name.startswith("_")]
