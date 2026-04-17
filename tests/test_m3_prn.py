"""
test_m3_prn.py — M3 validation for the 23-bit DSSS PRN LFSR.

Ground truth: the first 64 chips of each of the four T.018 Table 2.2
initial states (Normal I/Q, Self-Test I/Q), captured in
test_vectors/prn_sequences.json.

Additional checks:
 - LFSR period is exactly 2^23 - 1.
 - A full 38 400-chip burst segment is produced without error.
 - Re-initialising the generator reproduces the same sequence.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "scripts")))
VEC_DIR = os.path.abspath(os.path.join(HERE, "..", "test_vectors"))

from sgb_prn import (
    prn_generator, PRNGenerator,
    INIT_NORMAL_I, INIT_NORMAL_Q, INIT_SELF_TEST_I, INIT_SELF_TEST_Q,
    chips_to_hex, REGISTER_WIDTH,
)


PASS = 0
FAIL = 0

def check(name, got, expected):
    global PASS, FAIL
    if got == expected:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}: expected {expected!r}, got {got!r}")


# ----------------------------------------------------------------------
print("[1] First-64-chip match for all four initial states")
with open(os.path.join(VEC_DIR, "prn_sequences.json")) as fh:
    vec = json.load(fh)

for key, init_state in (
    ("normal_i",    INIT_NORMAL_I),
    ("normal_q",    INIT_NORMAL_Q),
    ("self_test_i", INIT_SELF_TEST_I),
    ("self_test_q", INIT_SELF_TEST_Q),
):
    expected_hex = vec["initialization"][key]["first_64_chips_hex_clean"]
    gen = PRNGenerator(init_state)
    chips = gen.next_chips(64)
    got_hex = chips_to_hex(chips)
    check(f"first 64 chips: {key}", got_hex, expected_hex)


# ----------------------------------------------------------------------
print("\n[2] Factory prn_generator() maps mode/channel correctly")
for mode, ch, init in [
    ("normal",    "i", INIT_NORMAL_I),
    ("normal",    "q", INIT_NORMAL_Q),
    ("self_test", "i", INIT_SELF_TEST_I),
    ("self_test", "q", INIT_SELF_TEST_Q),
]:
    g = prn_generator(mode, ch)
    check(f"initial state ({mode}, {ch})", g.state, init)


# ----------------------------------------------------------------------
print("\n[3] Segment length 38400 chips produced cleanly")
for mode in ("normal", "self_test"):
    for ch in ("i", "q"):
        seg = prn_generator(mode, ch).generate_segment(38400)
        check(f"segment length {mode}/{ch}", len(seg), 38400)
        check(f"segment values are 0/1 only {mode}/{ch}",
              all(x in (0, 1) for x in seg), True)


# ----------------------------------------------------------------------
print("\n[4] Period = 2^23 - 1")
# Rather than run 2^23 chips (slow), verify by advancing 2^23 - 1 chips
# and confirming the internal state returns to the start.
g = PRNGenerator(INIT_NORMAL_I)
start = g.state
_ = g.next_chips((1 << 23) - 1)
check("Normal-I register returns to start after 2^23 - 1 chips", g.state, start)


# ----------------------------------------------------------------------
print("\n[5] Reset reproduces the same sequence")
g = prn_generator("normal", "i")
a = g.next_chips(500)
g.reset(INIT_NORMAL_I)
b = g.next_chips(500)
check("reset + regenerate matches", a, b)


# ----------------------------------------------------------------------
print("\n[6] Register width is 23")
check("register width", REGISTER_WIDTH, 23)


# ----------------------------------------------------------------------
print(f"\n==== M3 RESULTS: {PASS} passed, {FAIL} failed ====")
sys.exit(0 if FAIL == 0 else 1)
