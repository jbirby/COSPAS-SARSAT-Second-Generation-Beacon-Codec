"""
sgb_common.py — shared constants and bit-manipulation utilities for the
COSPAS-SARSAT Second-Generation Beacon (SGB) codec.

All references to section/table numbers are to specification C/S T.018,
Issue 1, Revision 7 (March 2021).
"""

from __future__ import annotations

from typing import Iterable, List, Sequence


# ---------------------------------------------------------------------------
# Message layout constants (Section 3.2, Table 3.1)
# ---------------------------------------------------------------------------

# 1-based inclusive bit ranges.
BIT_RANGE_TAC = (1, 16)            # 16 bits
BIT_RANGE_SERIAL = (17, 30)        # 14 bits
BIT_RANGE_COUNTRY = (31, 40)       # 10 bits
BIT_RANGE_HOMING = (41, 41)
BIT_RANGE_RLS = (42, 42)
BIT_RANGE_TEST = (43, 43)
BIT_RANGE_LAT = (44, 66)           # 23 bits: 1 sign + 7 deg + 15 frac
BIT_RANGE_LON = (67, 90)           # 24 bits: 1 sign + 8 deg + 15 frac
BIT_RANGE_LAT_SIGN = (44, 44)
BIT_RANGE_LAT_DEG = (45, 51)
BIT_RANGE_LAT_FRAC = (52, 66)
BIT_RANGE_LON_SIGN = (67, 67)
BIT_RANGE_LON_DEG = (68, 75)
BIT_RANGE_LON_FRAC = (76, 90)
BIT_RANGE_VESSEL_TYPE = (91, 93)   # 3 bits
BIT_RANGE_VESSEL_ID = (94, 137)    # 44 bits
BIT_RANGE_BEACON_TYPE = (138, 140) # 3 bits
BIT_RANGE_SPARE = (141, 154)       # 14 bits
BIT_RANGE_ROTATING = (155, 202)    # 48 bits (includes 4-bit identifier 155..158)
BIT_RANGE_ROT_ID = (155, 158)
BIT_RANGE_ROT_BODY = (159, 202)
BIT_RANGE_BCH = (203, 250)         # 48 bits

MAIN_FIELD_LENGTH = 202
BCH_PARITY_LENGTH = 48
TOTAL_MESSAGE_LENGTH = MAIN_FIELD_LENGTH + BCH_PARITY_LENGTH  # 250


# ---------------------------------------------------------------------------
# Beacon type codes (bits 138-140)
# ---------------------------------------------------------------------------

BEACON_TYPE_ELT = 0b000
BEACON_TYPE_EPIRB = 0b001
BEACON_TYPE_PLB = 0b010
BEACON_TYPE_ELT_DT = 0b011
BEACON_TYPE_SYSTEM = 0b111

BEACON_TYPE_NAMES = {
    BEACON_TYPE_ELT: "ELT",
    BEACON_TYPE_EPIRB: "EPIRB",
    BEACON_TYPE_PLB: "PLB",
    BEACON_TYPE_ELT_DT: "ELT(DT)",
    BEACON_TYPE_SYSTEM: "System",
}


# ---------------------------------------------------------------------------
# Vessel ID type codes (bits 91-93)
# ---------------------------------------------------------------------------

VESSEL_ID_NONE = 0b000
VESSEL_ID_MMSI = 0b001
VESSEL_ID_CALLSIGN = 0b010
VESSEL_ID_TAIL = 0b011
VESSEL_ID_ICAO = 0b100
VESSEL_ID_OPERATOR = 0b101

VESSEL_ID_NAMES = {
    VESSEL_ID_NONE: "None",
    VESSEL_ID_MMSI: "Maritime MMSI",
    VESSEL_ID_CALLSIGN: "Radio call sign",
    VESSEL_ID_TAIL: "Aircraft registration (tail number)",
    VESSEL_ID_ICAO: "Aviation 24-bit ICAO address",
    VESSEL_ID_OPERATOR: "Aircraft operator + serial number",
}


# ---------------------------------------------------------------------------
# Rotating field identifiers (Table 3.3-3.8)
# ---------------------------------------------------------------------------

ROT_G008 = 0
ROT_ELT_DT = 1
ROT_RLS = 2
ROT_NATIONAL = 3
ROT_CANCELLATION = 15

ROT_NAMES = {
    0: "G.008 Objective Requirements",
    1: "ELT(DT) In-Flight Emergency",
    2: "RLS (Return Link Service)",
    3: "National Use",
    4: "Spare 4", 5: "Spare 5", 6: "Spare 6", 7: "Spare 7",
    8: "Spare 8", 9: "Spare 9", 10: "Spare 10", 11: "Spare 11",
    12: "Spare 12", 13: "Spare 13", 14: "Spare 14",
    15: "Cancellation Message",
}


# ---------------------------------------------------------------------------
# Default / no-fix location bit patterns (Appendix C.3)
# ---------------------------------------------------------------------------

NO_FIX_LAT_BITS = "1" + "1111111" + "000001111100000"
NO_FIX_LON_BITS = "1" + "11111111" + "111110000011111"


# ---------------------------------------------------------------------------
# Modified Baudot 6-bit code (Table 3.2). The spec lists 26 letters, digits
# 0-9, space, hyphen and slash. Unspecified characters are encoded as the
# spare code 100100 (same as space).
# ---------------------------------------------------------------------------

MODIFIED_BAUDOT = {
    "A": "000001", "B": "000010", "C": "000011", "D": "000100",
    "E": "000101", "F": "000110", "G": "000111", "H": "001000",
    "I": "001001", "J": "001010", "K": "001011", "L": "001100",
    "M": "001101", "N": "001110", "O": "001111", "P": "010000",
    "Q": "010001", "R": "010010", "S": "010011", "T": "010100",
    "U": "010101", "V": "010110", "W": "010111", "X": "011000",
    "Y": "011001", "Z": "011010",
    "0": "011011", "1": "011100", "2": "011101", "3": "011110",
    "4": "011111", "5": "100000", "6": "100001", "7": "100010",
    "8": "100011", "9": "100100",
    " ": "100100", "-": "011000", "/": "010111",
}

# Inverse mapping: we resolve ambiguities (9 and space share 100100, hyphen
# and X share 011000, slash and W share 010111) in favour of the common
# alphanumeric interpretation during decode.
MODIFIED_BAUDOT_INVERSE = {v: k for k, v in reversed(list(MODIFIED_BAUDOT.items()))}


def encode_baudot(text: str, length_chars: int, left_justify: bool = True) -> str:
    """Encode text to a 6*length_chars-bit modified-Baudot string.

    Args:
        text: Input text (ASCII letters, digits, space, hyphen, slash).
        length_chars: Number of Baudot characters in the output (typically 7).
        left_justify: If True, pad with spares on the right; if False,
            pad with spares on the left (right-justified).

    Returns:
        Bit string of length 6*length_chars.
    """
    text = text.upper()
    encoded = [MODIFIED_BAUDOT.get(ch, "100100") for ch in text][:length_chars]
    pad = length_chars - len(encoded)
    if left_justify:
        encoded = encoded + ["100100"] * pad
    else:
        encoded = ["100100"] * pad + encoded
    return "".join(encoded)


def decode_baudot(bits: str) -> str:
    """Decode a modified-Baudot bit string into text. Spare codes become ' '."""
    out: List[str] = []
    for i in range(0, len(bits), 6):
        sym = bits[i:i+6]
        if len(sym) < 6:
            break
        out.append(MODIFIED_BAUDOT_INVERSE.get(sym, "?"))
    return "".join(out)


# ---------------------------------------------------------------------------
# Bit-manipulation helpers. All bit strings are MSB-first; bit position
# indices are 1-based as in the specification.
# ---------------------------------------------------------------------------

def int_to_bits(value: int, width: int) -> str:
    """Unsigned integer -> MSB-first bit string of the given width."""
    if value < 0:
        raise ValueError(f"int_to_bits expects non-negative, got {value}")
    if value >= (1 << width):
        raise ValueError(f"value {value} does not fit in {width} bits")
    return format(value, f"0{width}b")


def bits_to_int(bits: str) -> int:
    """MSB-first bit string -> unsigned integer."""
    if not bits:
        return 0
    return int(bits, 2)


def hex_to_bits(hex_string: str, bit_length: int) -> str:
    """Convert a hex string to a bit string of exactly bit_length bits.

    T.018 hex representations use MSB-first packing into 4-bit nibbles
    with zero-pad bits AT THE END (least-significant side) when the bit
    length is not a multiple of 4. This matches the Appendix B.1 example
    where the 202-bit message is presented as 51 hex chars (204 bits)
    with 2 trailing padding bits.
    """
    hex_clean = "".join(hex_string.split())
    total_hex_bits = len(hex_clean) * 4
    n = int(hex_clean, 16)
    full = format(n, f"0{total_hex_bits}b")
    if bit_length <= total_hex_bits:
        return full[:bit_length]
    # Zero-extend on the right (MSB-aligned with trailing padding).
    return full + "0" * (bit_length - total_hex_bits)


def bits_to_hex(bits: str) -> str:
    """Convert an MSB-first bit string into an upper-case hex string.

    Zero-pads the bit string on the right to a 4-bit boundary (T.018
    convention) so that the first hex char represents the high nibble
    of the first 4 bits.
    """
    if not bits:
        return ""
    pad = (-len(bits)) % 4
    padded = bits + "0" * pad
    width = len(padded) // 4
    n = int(padded, 2)
    return format(n, f"0{width}X")


def slice_bits(bits: str, start: int, end: int) -> str:
    """Return bits[start..end] using 1-based inclusive indexing."""
    return bits[start - 1:end]


def assemble_bits(pieces: Iterable[str]) -> str:
    """Concatenate bit strings, checking each contains only 0/1."""
    parts: List[str] = []
    for p in pieces:
        if not all(ch in "01" for ch in p):
            raise ValueError(f"non-binary bit string piece: {p!r}")
        parts.append(p)
    return "".join(parts)


def bits_equal(a: str, b: str) -> bool:
    return a == b


def xor_bits(a: str, b: str) -> str:
    """Bit-wise XOR of two equal-length bit strings."""
    if len(a) != len(b):
        raise ValueError(f"xor_bits length mismatch: {len(a)} vs {len(b)}")
    return "".join("0" if x == y else "1" for x, y in zip(a, b))


def bits_to_bytes(bits: str) -> bytes:
    """MSB-first bit string -> bytes, zero-padded on the right if needed."""
    pad = (-len(bits)) % 8
    padded = bits + "0" * pad
    return int(padded, 2).to_bytes(len(padded) // 8, "big")


def bytes_to_bits(data: bytes, bit_length: int) -> str:
    """Bytes -> MSB-first bit string of the given bit length."""
    n = int.from_bytes(data, "big")
    bits = format(n, f"0{len(data) * 8}b")
    return bits[:bit_length]


# ---------------------------------------------------------------------------
# Country code lookup (ITU MID subset matching the parent skill)
# ---------------------------------------------------------------------------

COUNTRY_NAMES = {
    201: "Albania", 211: "Germany", 226: "France", 230: "Finland",
    232: "UK", 235: "UK", 244: "Netherlands", 247: "Italy", 255: "Portugal",
    263: "Portugal", 303: "Canada", 316: "Canada", 338: "USA", 366: "USA",
    412: "China", 431: "Japan", 440: "South Korea", 445: "DPRK",
    501: "Antarctica", 503: "Australia", 512: "New Zealand",
    636: "Liberia", 701: "Argentina", 710: "Brazil",
}


def country_name(code: int) -> str:
    return COUNTRY_NAMES.get(code, f"Country {code}")


__all__ = [name for name in globals() if not name.startswith("_")]
