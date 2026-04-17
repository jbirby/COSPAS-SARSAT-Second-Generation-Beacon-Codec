"""
sgb_bch.py — BCH(250, 202) encoder and decoder for the COSPAS-SARSAT
Second-Generation Beacon message.

The code is a shortened form of the BCH(255, 207) cyclic code over GF(2)
whose generator polynomial is the LCM of the minimal polynomials of
alpha^1, alpha^3, ..., alpha^11 with alpha a primitive element of GF(2^8).
The code corrects up to 6 bit errors in the 250-bit pattern.

This module provides:

- ``bch_generator_poly()``  — the 49-bit generator polynomial
- ``bch_encode(info_bits)`` — compute the 48-bit BCH parity
- ``bch_decode(codeword_bits)`` — attempt error correction via syndrome
  computation, Berlekamp-Massey, and Chien search.

All I/O uses MSB-first binary strings ("0"/"1").
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

from sgb_common import MAIN_FIELD_LENGTH, BCH_PARITY_LENGTH, TOTAL_MESSAGE_LENGTH


# ---------------------------------------------------------------------------
# Core polynomial constants
# ---------------------------------------------------------------------------

# Generator polynomial as a 49-bit integer (MSB = coefficient of X^48).
# Equivalent to the binary 1110001111110101110000101110111110011110010010111.
GENERATOR_POLY_INT = int(
    "1110001111110101110000101110111110011110010010111", 2
)
GENERATOR_POLY_DEGREE = 48

# Parent code is BCH(255, 207) over GF(2^8) with the primitive polynomial
# p(X) = X^8 + X^4 + X^3 + X^2 + 1 (0x11D). This is the standard
# Reed-Solomon / BCH field.
PRIMITIVE_POLY = 0x11D  # X^8 + X^4 + X^3 + X^2 + 1
FIELD_SIZE = 256        # GF(2^8)
PARENT_CODE_LENGTH = 255
PARENT_MESSAGE_LENGTH = 207
CODE_LENGTH = 250
MESSAGE_LENGTH = 202
PARITY_LENGTH = 48
ERROR_CORRECTION_T = 6  # corrects up to 6 bit errors


# ---------------------------------------------------------------------------
# GF(2^8) arithmetic helpers
# ---------------------------------------------------------------------------

def _build_gf_tables() -> Tuple[List[int], List[int]]:
    """Build log and antilog tables for GF(2^8) using the primitive poly."""
    exp = [0] * 512
    log = [0] * 256
    x = 1
    for i in range(255):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & 0x100:
            x ^= PRIMITIVE_POLY
    # Duplicate for convenient index wrap-around.
    for i in range(255, 512):
        exp[i] = exp[i - 255]
    return exp, log


GF_EXP, GF_LOG = _build_gf_tables()


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return GF_EXP[(GF_LOG[a] + GF_LOG[b]) % 255]


def gf_div(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("divide by 0 in GF(2^8)")
    if a == 0:
        return 0
    return GF_EXP[(GF_LOG[a] - GF_LOG[b]) % 255]


def gf_pow(a: int, n: int) -> int:
    if a == 0:
        return 0
    return GF_EXP[(GF_LOG[a] * n) % 255]


def gf_inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("invert 0 in GF(2^8)")
    return GF_EXP[(255 - GF_LOG[a]) % 255]


# ---------------------------------------------------------------------------
# Encoder
# ---------------------------------------------------------------------------

def bch_generator_poly() -> int:
    """Return the 49-bit integer representation of g(X)."""
    return GENERATOR_POLY_INT


def bch_encode(info_bits: str) -> str:
    """Compute the 48-bit BCH parity for a 202-bit message.

    The BCH parity is the polynomial remainder of (info * X^48) mod g(X)
    over GF(2). The returned bit string has length PARITY_LENGTH (48) and
    is MSB-first (coefficient of X^47 first).
    """
    if len(info_bits) != MESSAGE_LENGTH:
        raise ValueError(
            f"bch_encode expects {MESSAGE_LENGTH} info bits, got {len(info_bits)}"
        )

    # Work with big integers: info * 2^48 mod g.
    info_int = int(info_bits, 2)
    dividend = info_int << PARITY_LENGTH  # append 48 zero LSBs
    g = GENERATOR_POLY_INT
    g_deg = GENERATOR_POLY_DEGREE
    g_bit_len = g_deg + 1  # 49 bits

    # Polynomial long division over GF(2): subtract = XOR.
    total_bits = MESSAGE_LENGTH + PARITY_LENGTH  # 250
    for i in range(MESSAGE_LENGTH):
        bit_pos = total_bits - 1 - i  # MSB downward
        if (dividend >> bit_pos) & 1:
            dividend ^= g << (bit_pos - g_deg)

    remainder = dividend & ((1 << PARITY_LENGTH) - 1)
    return format(remainder, f"0{PARITY_LENGTH}b")


def bch_encode_codeword(info_bits: str) -> str:
    """Return the full 250-bit codeword = info (202) + parity (48)."""
    parity = bch_encode(info_bits)
    return info_bits + parity


# ---------------------------------------------------------------------------
# Syndrome computation
# ---------------------------------------------------------------------------

def _shorten_offset() -> int:
    """Return the zero-bit offset used to evaluate the shortened codeword
    in the full BCH(255, 207) polynomial frame.

    The BCH(250, 202) codeword is the BCH(255, 207) codeword with the top
    5 information bits forced to 0. Equivalently, the 250-bit pattern
    corresponds to a 255-bit polynomial whose coefficients of X^254 ...
    X^250 are zero. So we can compute syndromes by evaluating the 250-bit
    polynomial directly — no padding is needed when we use alpha^i as the
    evaluation point, because the contribution of those 5 zero bits is 0.
    """
    return PARENT_CODE_LENGTH - CODE_LENGTH  # 5


def _eval_poly_at_alpha(bits: str, alpha_power: int) -> int:
    """Evaluate a binary polynomial at alpha^alpha_power.

    ``bits`` is MSB-first: bits[0] is the coefficient of X^(len-1), bits[-1]
    is the coefficient of X^0. The evaluation is done in GF(2^8).
    """
    n = len(bits)
    # Higher-degree bits correspond to higher offsets in the parent-code
    # frame. Because we treat the 250-bit codeword as the bottom 250
    # coefficients of a 255-bit parent polynomial, X^0 stays at X^0 and
    # bit i from the right (0-indexed) contributes alpha^(alpha_power * i).
    result = 0
    for idx, ch in enumerate(bits):
        if ch == "1":
            exponent = (n - 1 - idx) * alpha_power % 255
            result ^= GF_EXP[exponent]
    return result


def bch_syndromes(codeword_bits: str) -> List[int]:
    """Compute syndromes S_1, S_3, S_5, S_7, S_9, S_11 (used for 6-error
    correction).

    Returns a list of 2t = 12 values S_1..S_{12}; in GF(2) the even-indexed
    syndromes are redundant (S_{2i} = S_i^2), but we populate them for
    Berlekamp-Massey convenience.
    """
    if len(codeword_bits) != CODE_LENGTH:
        raise ValueError(
            f"bch_syndromes expects {CODE_LENGTH} bits, got {len(codeword_bits)}"
        )
    syndromes = []
    for i in range(1, 2 * ERROR_CORRECTION_T + 1):
        syndromes.append(_eval_poly_at_alpha(codeword_bits, i))
    return syndromes


# ---------------------------------------------------------------------------
# Berlekamp-Massey and Chien search
# ---------------------------------------------------------------------------

def _berlekamp_massey(syndromes: List[int]) -> List[int]:
    """Find the error-locator polynomial Lambda(X) from the syndromes.

    ``syndromes`` has length 2t = 12 with 1-indexed convention (index 0 is
    S_1). Returns Lambda as a list of GF(2^8) coefficients, lambda[0] = 1,
    lambda[1], ... lambda[L] where L is the number of errors.
    """
    t2 = len(syndromes)
    lam = [1]
    B = [1]
    L = 0
    m = 1
    b = 1

    for n in range(t2):
        # Compute discrepancy Delta.
        delta = syndromes[n]
        for i in range(1, L + 1):
            delta ^= gf_mul(lam[i], syndromes[n - i])
        if delta == 0:
            m += 1
        elif 2 * L <= n:
            T = list(lam)
            # lam(X) -= delta / b * X^m * B(X)
            coef = gf_div(delta, b)
            scaled_B = [gf_mul(coef, x) for x in B]
            shifted = [0] * m + scaled_B
            # Extend lam if necessary.
            new_len = max(len(lam), len(shifted))
            lam += [0] * (new_len - len(lam))
            shifted += [0] * (new_len - len(shifted))
            lam = [a ^ b for a, b in zip(lam, shifted)]
            L = n + 1 - L
            B = T
            b = delta
            m = 1
        else:
            coef = gf_div(delta, b)
            scaled_B = [gf_mul(coef, x) for x in B]
            shifted = [0] * m + scaled_B
            new_len = max(len(lam), len(shifted))
            lam += [0] * (new_len - len(lam))
            shifted += [0] * (new_len - len(shifted))
            lam = [a ^ b for a, b in zip(lam, shifted)]
            m += 1

    # Trim trailing zero coefficients (shouldn't happen for well-formed
    # outputs but makes downstream logic simpler).
    while len(lam) > 1 and lam[-1] == 0:
        lam.pop()
    return lam


def _chien_search(lam: List[int], code_length: int) -> List[int]:
    """Find the positions where Lambda(alpha^-i) = 0.

    Returns a list of 0-based error positions within a codeword of length
    code_length, where position 0 is the most-significant bit (X^(n-1)).
    """
    errors = []
    for i in range(code_length):
        # Evaluate Lambda at alpha^-i = alpha^(255 - i).
        exp_base = (255 - i) % 255
        total = 0
        for j, coeff in enumerate(lam):
            if coeff == 0:
                continue
            total ^= gf_mul(coeff, GF_EXP[(exp_base * j) % 255])
        if total == 0:
            # Convert 0-indexed power-of-X to 0-indexed MSB-first position.
            # In the 255-bit parent code, a root alpha^-i means an error at
            # position X^i. MSB-first position = (n-1) - i.
            pos_msb = (code_length - 1) - i
            if 0 <= pos_msb < code_length:
                errors.append(pos_msb)
    return sorted(errors)


def bch_decode(codeword_bits: str) -> Tuple[str, int, bool]:
    """Attempt to decode a 250-bit codeword.

    Returns a tuple ``(corrected_codeword, errors_corrected, ok)``:
    - corrected_codeword: the (possibly corrected) 250-bit codeword.
    - errors_corrected: number of bit errors the decoder corrected (>=0).
    - ok: True if the final syndromes are all zero; False if the decoder
      could not correct the received pattern.
    """
    if len(codeword_bits) != CODE_LENGTH:
        raise ValueError(
            f"bch_decode expects {CODE_LENGTH} bits, got {len(codeword_bits)}"
        )

    syndromes = bch_syndromes(codeword_bits)
    if all(s == 0 for s in syndromes):
        return codeword_bits, 0, True

    lam = _berlekamp_massey(syndromes)
    L = len(lam) - 1
    if L == 0:
        return codeword_bits, 0, False
    if L > ERROR_CORRECTION_T:
        return codeword_bits, 0, False

    positions = _chien_search(lam, CODE_LENGTH)
    if len(positions) != L:
        return codeword_bits, 0, False

    # Flip bits at the identified positions.
    corrected = list(codeword_bits)
    for pos in positions:
        corrected[pos] = "0" if corrected[pos] == "1" else "1"
    corrected_str = "".join(corrected)

    # Re-check syndromes after correction.
    new_syndromes = bch_syndromes(corrected_str)
    if all(s == 0 for s in new_syndromes):
        return corrected_str, L, True
    return codeword_bits, 0, False


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------

def verify_codeword(codeword_bits: str) -> bool:
    """Return True iff all syndromes of ``codeword_bits`` are zero."""
    if len(codeword_bits) != CODE_LENGTH:
        return False
    return all(s == 0 for s in bch_syndromes(codeword_bits))


def describe_poly() -> str:
    """Return a human-readable description of the generator polynomial."""
    g = GENERATOR_POLY_INT
    terms = []
    for i in range(GENERATOR_POLY_DEGREE + 1):
        if (g >> i) & 1:
            if i == 0:
                terms.append("1")
            elif i == 1:
                terms.append("X")
            else:
                terms.append(f"X^{i}")
    terms.reverse()
    return " + ".join(terms)


__all__ = [name for name in globals() if not name.startswith("_")]
