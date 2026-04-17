"""
test_m2_bch.py — M2 validation for the shortened BCH(250,202) codec.

Ground truth:
 - Generator polynomial from T.018 Appendix D (Section 4 of the reference
   vectors) — degree 48, stored in test_vectors/bch_polynomial.json.
 - Appendix B.1 worked example — main field hex + expected 48-bit parity,
   stored in test_vectors/bch_vector.json.

Additional fuzz tests:
 - Zero-error decoding of 200 random messages.
 - Single-bit to six-bit random error patterns: decoder must correctly
   identify and flip exactly the introduced errors.
 - Seven-bit error patterns exceed t=6 so the decoder must refuse to
   claim success (ok == False).

Run:  python3 test_m2_bch.py
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "scripts")))
VEC_DIR = os.path.abspath(os.path.join(HERE, "..", "test_vectors"))

from sgb_common import hex_to_bits, bits_to_hex, MAIN_FIELD_LENGTH
from sgb_bch import bch_encode, bch_decode, GENERATOR_POLY_INT


PASS = 0
FAIL = 0

def check(name, got, expected):
    global PASS, FAIL
    if got == expected:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")
        print(f"         expected: {expected!r}")
        print(f"         got     : {got!r}")


# ----------------------------------------------------------------------
print("[1] Generator polynomial")
with open(os.path.join(VEC_DIR, "bch_polynomial.json")) as fh:
    poly_vec = json.load(fh)
expected_poly_bits = poly_vec["generator_bits"]
expected_poly_int = int(expected_poly_bits, 2)
check("generator polynomial integer match", GENERATOR_POLY_INT, expected_poly_int)


# ----------------------------------------------------------------------
print("\n[2] Appendix B.1 BCH parity")
with open(os.path.join(VEC_DIR, "bch_vector.json")) as fh:
    bv = json.load(fh)
main_bits = hex_to_bits(bv["main_bits_hex"], MAIN_FIELD_LENGTH)
parity = bch_encode(main_bits)
check("Appendix B.1 parity bits", parity, bv["expected_bch_parity_bin"])
check("Appendix B.1 parity hex", bits_to_hex(parity), "492A4FC57A49")


# ----------------------------------------------------------------------
print("\n[3] Zero-error decode round-trips (200 trials)")
rng = random.Random(20260417)
all_ok = True
for _ in range(200):
    info = "".join(rng.choice("01") for _ in range(MAIN_FIELD_LENGTH))
    cw = info + bch_encode(info)
    decoded, err, ok = bch_decode(cw)
    if not (ok and err == 0 and decoded == cw):
        all_ok = False
        break
check("zero-error decode 200x", all_ok, True)


# ----------------------------------------------------------------------
print("\n[4] Random 1..6 bit error correction (300 trials per level)")
for t in range(1, 7):
    all_ok = True
    for _ in range(300):
        info = "".join(rng.choice("01") for _ in range(MAIN_FIELD_LENGTH))
        cw = info + bch_encode(info)
        positions = rng.sample(range(250), t)
        flipped = list(cw)
        for p in positions:
            flipped[p] = "1" if flipped[p] == "0" else "0"
        received = "".join(flipped)
        decoded, err, ok = bch_decode(received)
        if not (ok and err == t and decoded == cw):
            all_ok = False
            break
    check(f"decode with {t}-bit errors", all_ok, True)


# ----------------------------------------------------------------------
print("\n[5] Over-capacity (7-bit) error patterns rejected (100 trials)")
refused = 0
for _ in range(100):
    info = "".join(rng.choice("01") for _ in range(MAIN_FIELD_LENGTH))
    cw = info + bch_encode(info)
    positions = rng.sample(range(250), 7)
    flipped = list(cw)
    for p in positions:
        flipped[p] = "1" if flipped[p] == "0" else "0"
    received = "".join(flipped)
    _decoded, _err, ok = bch_decode(received)
    if not ok:
        refused += 1
# A few might miscorrect by chance (t+1 pattern can alias to a distance-t
# codeword). We expect the vast majority to be rejected.
print(f"         refused {refused}/100 7-bit patterns (>=70 required)")
check("7-bit patterns mostly rejected", refused >= 70, True)


# ----------------------------------------------------------------------
print(f"\n==== M2 RESULTS: {PASS} passed, {FAIL} failed ====")
sys.exit(0 if FAIL == 0 else 1)
