"""
sgb_prn.py — 23-bit PRN LFSR for the COSPAS-SARSAT SGB DSSS spreader.

Specification reference: C/S T.018 Rev 7, Section 2.2.3, Table 2.2, Appendix D.

Generator polynomial: G(x) = X^23 + X^18 + 1.

The register has 23 cells labelled 22..0. On each clock:

  - output = reg[0]
  - feedback = reg[0] XOR reg[18]
  - shift all cells one place towards index 0 (reg[0] is discarded
    after output, reg[i-1] <- reg[i] for i in 1..22, and reg[22] <- feedback)

Period = 2^23 - 1 = 8,388,607 chips.

Four initialization states are defined by Table 2.2:

                         register (22..0)
  Normal mode     I:  0000 0000 0000 0000 0000 001
  Normal mode     Q:  0011 0101 1000 0011 1111 100
  Self-test mode  I:  1010 0101 1001 0011 1110 000
  Self-test mode  Q:  0111 1001 1101 0010 0101 000

The first 64 chips for each initial state are listed in Appendix D (and
summarised in ``test_vectors/prn_sequences.json``); they are the primary
unit tests for this module.
"""

from __future__ import annotations

from typing import List


REGISTER_WIDTH = 23
TAP_OUTPUT = 0     # output position
TAP_FEEDBACK = 18  # second feedback tap
REGISTER_MASK = (1 << REGISTER_WIDTH) - 1
MSB = 1 << (REGISTER_WIDTH - 1)


# Initial state integers; format(state, '023b') recovers the bit string
# published in the spec.
INIT_NORMAL_I = int("00000000000000000000001", 2)
INIT_NORMAL_Q = int("00110101100000111111100", 2)
INIT_SELF_TEST_I = int("10100101100100111110000", 2)
INIT_SELF_TEST_Q = int("01111001110100100101000", 2)


def _bits_from_state(state: int) -> str:
    return format(state & REGISTER_MASK, f"0{REGISTER_WIDTH}b")


class PRNGenerator:
    """23-bit Fibonacci LFSR matching T.018 Table 2.2."""

    def __init__(self, initial_state: int):
        if not 0 <= initial_state <= REGISTER_MASK:
            raise ValueError(
                f"initial state {initial_state:X} does not fit in "
                f"{REGISTER_WIDTH} bits"
            )
        if initial_state == 0:
            raise ValueError(
                "initial state must be non-zero (an all-zero LFSR is a "
                "fixed point of G(x))"
            )
        self._state = initial_state

    @property
    def state(self) -> int:
        return self._state

    def reset(self, state: int) -> None:
        self.__init__(state)

    def next_chip(self) -> int:
        """Return the current LSB (the chip to be transmitted this tick)
        and then advance the register by one clock."""
        out = self._state & 1
        fb = out ^ ((self._state >> TAP_FEEDBACK) & 1)
        self._state = (self._state >> 1) | (fb << (REGISTER_WIDTH - 1))
        return out

    def next_chips(self, n: int) -> List[int]:
        return [self.next_chip() for _ in range(n)]

    def generate_segment(self, length: int = 38400) -> List[int]:
        """Produce a full burst-length PRN segment (default 38400 chips)."""
        return self.next_chips(length)


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def prn_generator(mode: str, channel: str) -> PRNGenerator:
    """Return a PRN generator initialised for the given (mode, channel).

    mode: "normal" or "self_test"
    channel: "i" or "q"
    """
    mode_n = mode.lower().replace("-", "_").replace(" ", "_")
    channel_n = channel.lower()
    table = {
        ("normal", "i"): INIT_NORMAL_I,
        ("normal", "q"): INIT_NORMAL_Q,
        ("self_test", "i"): INIT_SELF_TEST_I,
        ("self_test", "q"): INIT_SELF_TEST_Q,
    }
    key = (mode_n, channel_n)
    if key not in table:
        raise ValueError(
            f"unknown PRN selector ({mode!r}, {channel!r}); expected "
            f"mode in ('normal', 'self_test') and channel in ('i', 'q')"
        )
    return PRNGenerator(table[key])


# ---------------------------------------------------------------------------
# Chip-to-hex packing (used by the test suite and for debug dumps)
# ---------------------------------------------------------------------------

def chips_to_hex(chips: List[int]) -> str:
    """Pack a chip list (each 0 or 1) into an upper-case hex string,
    MSB-first within each nibble, leftmost chip first."""
    if not chips:
        return ""
    pad = (-len(chips)) % 4
    padded = chips + [0] * pad
    n = len(padded) // 4
    out = []
    for i in range(n):
        nibble = (padded[4*i] << 3) | (padded[4*i+1] << 2) | \
                 (padded[4*i+2] << 1) |  padded[4*i+3]
        out.append(format(nibble, "X"))
    return "".join(out)


def hex_to_chips(hex_string: str) -> List[int]:
    """Inverse of chips_to_hex."""
    chips: List[int] = []
    for ch in "".join(hex_string.split()):
        v = int(ch, 16)
        chips.extend([(v >> 3) & 1, (v >> 2) & 1, (v >> 1) & 1, v & 1])
    return chips


__all__ = [
    "PRNGenerator", "prn_generator",
    "INIT_NORMAL_I", "INIT_NORMAL_Q",
    "INIT_SELF_TEST_I", "INIT_SELF_TEST_Q",
    "REGISTER_WIDTH", "TAP_OUTPUT", "TAP_FEEDBACK",
    "chips_to_hex", "hex_to_chips",
]
