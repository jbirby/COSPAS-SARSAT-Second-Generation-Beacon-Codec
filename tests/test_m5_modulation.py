"""
test_m5_modulation.py — M5 validation for the SGB DSSS-OQPSK modem.

Checks:
 1. Chip-stream construction obeys Table 2.4 (bit=0 -> PRN as-is,
    bit=1 -> PRN inverted), with 6400-chip all-zero preamble per channel.
 2. Round-trip modulate->demodulate recovers the full 250-bit message
    exactly (complex baseband, rect pulse).
 3. Round-trip with half-sine pulse shaping also recovers the message.
 4. Round-trip with real passband at a modest carrier (e.g. 24 kHz) and
    192 kHz sample rate recovers the message.
 5. Burst length matches spec: 38 400 chips/channel, 1.0 s at chip rate.

Run:  python3 test_m5_modulation.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.abspath(os.path.join(HERE, "..", "scripts"))
sys.path.insert(0, SCRIPTS)

from sgb_prn import prn_generator
from sgb_modulation import (
    CHIP_RATE, CHIPS_PER_BIT, SEGMENT_CHIPS,
    PREAMBLE_CHIPS, MESSAGE_CHIPS, BITS_PER_CHANNEL,
    PREAMBLE_BITS_PER_CHANNEL, BURST_DURATION_S,
    ModulationParams, modulate, demodulate, build_chip_streams,
)

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


# A fixed 250-bit test message (alternating nibbles to exercise both 0s
# and 1s on both channels, plus a recognisable fingerprint in each half).
_base = "1010010110100101" * 16  # 256 chars, will truncate
MSG = _base[:250]
assert len(MSG) == 250


# ----------------------------------------------------------------------
print("[1] Burst constants")
check("chip rate", CHIP_RATE, 38_400)
check("chips per bit", CHIPS_PER_BIT, 256)
check("segment chips per channel", SEGMENT_CHIPS, 38_400)
check("preamble chips", PREAMBLE_CHIPS, 6_400)
check("message chips", MESSAGE_CHIPS, 32_000)
check("bits per channel", BITS_PER_CHANNEL, 150)
check("preamble bits per channel", PREAMBLE_BITS_PER_CHANNEL, 25)
check("burst duration", BURST_DURATION_S, 1.0)


# ----------------------------------------------------------------------
print("\n[2] Chip-stream construction")
i_chips, q_chips = build_chip_streams(MSG, mode="normal")
check("I chip stream length", i_chips.size, SEGMENT_CHIPS)
check("Q chip stream length", q_chips.size, SEGMENT_CHIPS)
check("I chip stream dtype", i_chips.dtype, np.float32)

# Preamble bits are all zeros -> XOR with PRN leaves PRN unchanged ->
# mapped to 1 - 2*PRN. Verify first 6400 chips match -(2*PRN - 1).
i_prn = np.array(prn_generator("normal", "i").generate_segment(SEGMENT_CHIPS),
                 dtype=np.int8)
q_prn = np.array(prn_generator("normal", "q").generate_segment(SEGMENT_CHIPS),
                 dtype=np.int8)
i_preamble_expected = (1 - 2 * i_prn[:PREAMBLE_CHIPS]).astype(np.float32)
q_preamble_expected = (1 - 2 * q_prn[:PREAMBLE_CHIPS]).astype(np.float32)
check("I preamble matches PRN",
      bool(np.array_equal(i_chips[:PREAMBLE_CHIPS], i_preamble_expected)), True)
check("Q preamble matches PRN",
      bool(np.array_equal(q_chips[:PREAMBLE_CHIPS], q_preamble_expected)), True)

# Verify Table 2.4 on the FIRST data bit of each channel:
# I data bit 0 = MSG[0] = '1' -> chips are inverted PRN -> 1 - 2*(1-prn) = -1 + 2*prn
i_bit0 = MSG[0]  # first odd-indexed bit (1-based bit 1)
q_bit0 = MSG[1]  # first even-indexed bit (1-based bit 2)
i_data_start = PREAMBLE_CHIPS
i_data_slice = i_chips[i_data_start:i_data_start + CHIPS_PER_BIT]
if i_bit0 == "0":
    i_expected = (1 - 2 * i_prn[i_data_start:i_data_start + CHIPS_PER_BIT]).astype(np.float32)
else:
    i_expected = (-(1 - 2 * i_prn[i_data_start:i_data_start + CHIPS_PER_BIT])).astype(np.float32)
check("I first data bit follows Table 2.4",
      bool(np.array_equal(i_data_slice, i_expected)), True)

q_data_slice = q_chips[i_data_start:i_data_start + CHIPS_PER_BIT]
if q_bit0 == "0":
    q_expected = (1 - 2 * q_prn[i_data_start:i_data_start + CHIPS_PER_BIT]).astype(np.float32)
else:
    q_expected = (-(1 - 2 * q_prn[i_data_start:i_data_start + CHIPS_PER_BIT])).astype(np.float32)
check("Q first data bit follows Table 2.4",
      bool(np.array_equal(q_data_slice, q_expected)), True)


# ----------------------------------------------------------------------
print("\n[3] Round-trip complex baseband, rectangular pulse")
params = ModulationParams(sample_rate=192_000.0, pulse="rect",
                          carrier_hz=0.0, mode="normal")
sig = modulate(MSG, params)
check("output is complex", bool(np.iscomplexobj(sig)), True)
# Approx 1 s @ 192 kHz, with half-chip padding = ~192000 + 2 samples
expected_samples = SEGMENT_CHIPS * (int(params.sample_rate // CHIP_RATE)) + (int(params.sample_rate // CHIP_RATE) // 2)
check("sample count (approx)", sig.size >= expected_samples - 1, True)

recovered, info = demodulate(sig, sample_rate=params.sample_rate,
                             mode="normal", carrier_hz=0.0)
check("recovered message length", len(recovered), 250)
check("round-trip complex baseband + rect", recovered, MSG)


# ----------------------------------------------------------------------
print("\n[4] Round-trip complex baseband, half-sine pulse")
params = ModulationParams(sample_rate=192_000.0, pulse="half_sine",
                          carrier_hz=0.0, mode="normal")
sig = modulate(MSG, params)
recovered, _ = demodulate(sig, sample_rate=params.sample_rate,
                          mode="normal", carrier_hz=0.0)
check("round-trip complex baseband + half-sine", recovered, MSG)


# ----------------------------------------------------------------------
print("\n[5] Round-trip real passband, rectangular pulse, carrier 48 kHz")
# Need sample_rate high enough for carrier + chip rate sidebands.
# 192 kHz / carrier 48 kHz: images at 96 kHz, still within Nyquist.
params = ModulationParams(sample_rate=192_000.0, pulse="rect",
                          carrier_hz=48_000.0, mode="normal")
sig = modulate(MSG, params)
check("output is real (passband mode)", sig.dtype in (np.float32, np.float64), True)
recovered, _ = demodulate(sig, sample_rate=params.sample_rate,
                          mode="normal", carrier_hz=48_000.0)
check("round-trip real passband + rect", recovered, MSG)


# ----------------------------------------------------------------------
print("\n[6] Self-test mode round-trip")
params = ModulationParams(sample_rate=192_000.0, pulse="rect",
                          carrier_hz=0.0, mode="self_test")
sig = modulate(MSG, params)
recovered, _ = demodulate(sig, sample_rate=params.sample_rate,
                          mode="self_test", carrier_hz=0.0)
check("round-trip self-test mode", recovered, MSG)


# ----------------------------------------------------------------------
print(f"\n==== M5 RESULTS: {PASS} passed, {FAIL} failed ====")
sys.exit(0 if FAIL == 0 else 1)
