"""
sgb_modulation.py — DSSS-OQPSK modulator and demodulator for the
COSPAS-SARSAT Second-Generation Beacon.

Specification reference: C/S T.018 Rev 7, Sections 2.2-2.3.

Burst structure (Section 2.2.5, Figure 2-3):

    [166.7 ms preamble]  +  [833.3 ms message]   =  1.0 s total
      6400 chips/ch        32000 chips/ch           38400 chips/channel

Bit-to-channel mapping (Section 2.2.7):

  - Odd-numbered message bits (1, 3, ..., 249) go to the I channel.
  - Even-numbered message bits (2, 4, ..., 250) go to the Q channel.
  - Each channel thus carries 125 message bits at 150 bps.
  - Each channel has 25 preamble bits worth of chips (all zeros) preceding
    the data, bringing the channel length to 150 bits × 256 chips/bit
    = 38 400 chips.

Data-to-PRN spreading (Section 2.2.7, Table 2.4):

  - For each channel, take 256 chips of the channel's PRN per bit.
  - If the bit is 0 the chips go out as generated.
  - If the bit is 1 the chips are inverted (exclusive-or with 1).
  - The resulting ± 1 chip stream is converted to baseband (2 × chip - 1).

OQPSK (Section 2.3.3): The Q chip stream is delayed by half a chip
period (Tc/2) relative to I, with I leading.

Pulse shaping: rectangular (default) or half-sine (IEEE 802.15.4-2015
§ 12.2.6), both of which the spec lists as acceptable.

Output: by default the modulator returns a real audio waveform at a user-
selected carrier frequency (suitable for writing to a mono WAV). A
complex baseband mode is also supported for downstream RF processing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from sgb_prn import prn_generator


# ---------------------------------------------------------------------------
# Burst-level constants (Section 2.2)
# ---------------------------------------------------------------------------

CHIP_RATE = 38_400          # chips/second per channel
BIT_RATE_PER_CHANNEL = 150  # bits/second per channel
CHIPS_PER_BIT = CHIP_RATE // BIT_RATE_PER_CHANNEL  # 256

PREAMBLE_CHIPS = 6_400
MESSAGE_CHIPS = 32_000
SEGMENT_CHIPS = PREAMBLE_CHIPS + MESSAGE_CHIPS  # 38 400 per channel

PREAMBLE_BITS_PER_CHANNEL = PREAMBLE_CHIPS // CHIPS_PER_BIT  # 25 zero-bits
MESSAGE_BITS_PER_CHANNEL = MESSAGE_CHIPS // CHIPS_PER_BIT    # 125
BITS_PER_CHANNEL = SEGMENT_CHIPS // CHIPS_PER_BIT            # 150

BURST_DURATION_S = SEGMENT_CHIPS / CHIP_RATE                 # 1.0 s


# ---------------------------------------------------------------------------
# Chip stream construction
# ---------------------------------------------------------------------------

def _split_message_odd_even(message_bits: str) -> Tuple[str, str]:
    """Separate a 250-bit message into I-channel (odd-indexed, 1-based)
    and Q-channel (even-indexed) bit strings of 125 bits each.

    Spec indexing is 1-based: bit 1 is the first transmitted bit. In
    Python 0-based terms, I bits are message_bits[0::2] (indices 0, 2, ...)
    and Q bits are message_bits[1::2] (indices 1, 3, ...).
    """
    if len(message_bits) != 250:
        raise ValueError(f"message must be 250 bits, got {len(message_bits)}")
    if not all(c in "01" for c in message_bits):
        raise ValueError("message_bits must contain only 0/1 characters")
    i_bits = message_bits[0::2]
    q_bits = message_bits[1::2]
    assert len(i_bits) == len(q_bits) == 125
    return i_bits, q_bits


def _build_channel_chips(info_bits: str, prn_chips: np.ndarray) -> np.ndarray:
    """Combine a bit string (25 zero pre-bits + 125 data bits, implicitly
    supplied as info_bits) with a 38 400-chip PRN segment.

    The info_bits argument is expected to be exactly
    BITS_PER_CHANNEL = 150 bits (25 preamble zeros + 125 message bits).
    Each bit XORs 256 chips of the PRN, and the result is mapped to ±1.
    """
    if len(info_bits) != BITS_PER_CHANNEL:
        raise ValueError(
            f"expected {BITS_PER_CHANNEL} info bits, got {len(info_bits)}"
        )
    if prn_chips.shape != (SEGMENT_CHIPS,):
        raise ValueError(
            f"expected {SEGMENT_CHIPS} PRN chips, got {prn_chips.shape}"
        )
    bit_array = np.array([int(b) for b in info_bits], dtype=np.int8)
    # Expand each bit to CHIPS_PER_BIT chips
    bit_expanded = np.repeat(bit_array, CHIPS_PER_BIT)
    assert bit_expanded.size == SEGMENT_CHIPS
    # Table 2.4: bit=0 -> PRN as-is; bit=1 -> PRN inverted
    xor = np.bitwise_xor(bit_expanded.astype(np.int8),
                         prn_chips.astype(np.int8))
    # Map {0,1} -> {-1, +1}
    return (1 - 2 * xor).astype(np.float32)


def build_chip_streams(
    message_bits: str, mode: str = "normal"
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (I_chips, Q_chips) each of length 38 400, as float32 arrays
    of ± 1 values suitable for pulse shaping."""
    i_bits, q_bits = _split_message_odd_even(message_bits)
    i_info = ("0" * PREAMBLE_BITS_PER_CHANNEL) + i_bits
    q_info = ("0" * PREAMBLE_BITS_PER_CHANNEL) + q_bits

    i_prn = np.array(
        prn_generator(mode, "i").generate_segment(SEGMENT_CHIPS), dtype=np.int8
    )
    q_prn = np.array(
        prn_generator(mode, "q").generate_segment(SEGMENT_CHIPS), dtype=np.int8
    )

    i_stream = _build_channel_chips(i_info, i_prn)
    q_stream = _build_channel_chips(q_info, q_prn)
    return i_stream, q_stream


# ---------------------------------------------------------------------------
# Pulse shaping
# ---------------------------------------------------------------------------

def _rect_pulse(samples_per_chip: int) -> np.ndarray:
    return np.ones(samples_per_chip, dtype=np.float32)


def _half_sine_pulse(samples_per_chip: int) -> np.ndarray:
    """Half-sine pulse per IEEE 802.15.4-2015 §12.2.6:

        p(t) = sin(pi * t / (2 * Tc)) for 0 <= t <= 2 * Tc

    i.e. a pulse of 2-chip duration. The pulse is returned sampled at
    2*samples_per_chip points. Adjacent chips overlap by one chip.
    """
    n = 2 * samples_per_chip
    t = np.arange(n, dtype=np.float32) / float(n)
    # sin(pi * t / 2) over t in [0, 2) with t normalised to chip periods.
    # Here t/n in [0, 1) maps to one pulse. sin(pi * (t/n)) gives a full half-
    # cycle of sine from 0..pi which is the half-sine envelope shape
    # specified by IEEE 802.15.4 (amplitude 0 -> 1 -> 0).
    return np.sin(np.pi * t).astype(np.float32)


def _upsample_with_pulse(chips: np.ndarray, samples_per_chip: int,
                         pulse: str) -> np.ndarray:
    """Convolve a ± 1 chip stream with the chosen pulse shape to produce
    a continuous waveform sampled at samples_per_chip samples per chip.
    """
    # Impulse train: chip amplitude at multiples of samples_per_chip
    n_chips = chips.size
    n_samples = n_chips * samples_per_chip
    impulse = np.zeros(n_samples, dtype=np.float32)
    impulse[::samples_per_chip] = chips

    if pulse == "rect":
        p = _rect_pulse(samples_per_chip)
        # Rectangular pulse = "hold" each chip for samples_per_chip samples.
        # Convolution with impulse train produces the correct sample-and-hold
        # waveform, length n_samples + samples_per_chip - 1; trim to n_samples.
        y = np.convolve(impulse, p)[:n_samples]
        return y
    elif pulse == "half_sine":
        p = _half_sine_pulse(samples_per_chip)
        # Full convolution length = n_samples + 2*samples_per_chip - 1. We
        # keep the first n_samples + samples_per_chip samples so the overlap
        # region is correctly represented.
        y = np.convolve(impulse, p)
        return y[:n_samples + samples_per_chip]
    else:
        raise ValueError(f"unknown pulse shape: {pulse!r}")


# ---------------------------------------------------------------------------
# Full burst modulator
# ---------------------------------------------------------------------------

@dataclass
class ModulationParams:
    """Parameters controlling the audio output of the modulator."""
    sample_rate: float = 192_000.0  # Hz; must give integer samples/chip
    pulse: str = "rect"              # "rect" or "half_sine"
    carrier_hz: float = 0.0          # 0 -> complex baseband; else real passband
    amplitude: float = 0.8           # peak amplitude of the output waveform
    mode: str = "normal"             # or "self_test"


def modulate(
    message_bits: str,
    params: Optional[ModulationParams] = None,
) -> np.ndarray:
    """Modulate a 250-bit message into a DSSS-OQPSK audio waveform.

    Returns
    -------
    If ``params.carrier_hz == 0`` returns a complex-valued numpy array
    (I + jQ) at the requested sample rate. Otherwise returns a real-valued
    float32 array representing s(t) = I(t) cos(2*pi*fc*t) - Q(t) sin(2*pi*fc*t).
    """
    if params is None:
        params = ModulationParams()

    if params.sample_rate % CHIP_RATE != 0:
        raise ValueError(
            f"sample_rate ({params.sample_rate}) must be an integer multiple "
            f"of the chip rate ({CHIP_RATE})"
        )
    samples_per_chip = int(params.sample_rate // CHIP_RATE)

    # 1) Build I and Q chip streams (± 1, 38 400 samples each)
    i_chips, q_chips = build_chip_streams(message_bits, mode=params.mode)

    # 2) Upsample and pulse-shape each stream
    i_wave = _upsample_with_pulse(i_chips, samples_per_chip, params.pulse)
    q_wave = _upsample_with_pulse(q_chips, samples_per_chip, params.pulse)

    # 3) Apply OQPSK half-chip delay to Q (I leads Q, Section 2.3.3).
    # The spec (Section 2.3.3) allows a ±1% tolerance on the half-chip
    # offset, so we round to the nearest sample. When samples_per_chip is
    # even the delay is exact; when odd the error is at most 1/(2*Nspc).
    half_chip = samples_per_chip // 2
    if samples_per_chip < 2:
        raise ValueError(
            "sample_rate / chip_rate must be at least 2 so Q can be delayed"
        )
    q_delayed = np.concatenate([
        np.zeros(half_chip, dtype=np.float32),
        q_wave,
    ])
    # Align lengths
    n = max(i_wave.size + half_chip, q_delayed.size)
    i_pad = np.concatenate([i_wave, np.zeros(n - i_wave.size, dtype=np.float32)])
    q_pad = np.concatenate([q_delayed, np.zeros(n - q_delayed.size, dtype=np.float32)])

    # 4) Output
    amp = np.float32(params.amplitude)
    if params.carrier_hz == 0.0:
        signal = (i_pad + 1j * q_pad).astype(np.complex64)
        # Normalise so max |signal| == amplitude
        peak = float(np.max(np.abs(signal))) or 1.0
        return (signal * (amp / peak)).astype(np.complex64)
    else:
        t = np.arange(n, dtype=np.float32) / np.float32(params.sample_rate)
        carrier_c = np.cos(2.0 * np.pi * params.carrier_hz * t).astype(np.float32)
        carrier_s = np.sin(2.0 * np.pi * params.carrier_hz * t).astype(np.float32)
        signal = i_pad * carrier_c - q_pad * carrier_s
        peak = float(np.max(np.abs(signal))) or 1.0
        return (signal * (amp / peak)).astype(np.float32)


# ---------------------------------------------------------------------------
# Demodulator
# ---------------------------------------------------------------------------

def _downconvert_real_to_complex(
    samples: np.ndarray, sample_rate: float, carrier_hz: float,
) -> np.ndarray:
    """Multiply a real passband signal by e^{-j 2 pi fc t} to recover the
    complex baseband. A simple moving-average low-pass is applied to
    suppress the image at 2*fc; this is adequate because the chip rate
    (38.4 kHz) is usually well below 2*fc when carrier_hz is chosen sensibly.
    """
    n = samples.size
    t = np.arange(n, dtype=np.float64) / float(sample_rate)
    lo = np.exp(-2j * np.pi * carrier_hz * t)
    baseband = (samples.astype(np.float64)) * lo
    # Cheap LPF: moving average over one chip
    window = max(1, int(sample_rate / CHIP_RATE))
    if window > 1:
        kernel = np.ones(window, dtype=np.float64) / float(window)
        baseband = np.convolve(baseband, kernel, mode="same")
    # Complex samples represent I + jQ after down-mix.
    return (2.0 * baseband).astype(np.complex64)  # gain back factor of 2


def demodulate(
    samples: np.ndarray,
    sample_rate: float = 192_000.0,
    mode: str = "normal",
    carrier_hz: float = 0.0,
) -> Tuple[str, dict]:
    """Demodulate a DSSS-OQPSK audio waveform back to a 250-bit message.

    The demodulator assumes the start of the burst is at sample 0 (or close
    to it). It correlates each chip-aligned segment with the known PRN to
    recover each bit. Uses chip-center sampling with rectangular matched
    filtering (works for both rect and half-sine pulse shaping, though
    performance is better with a matched filter).
    """
    if sample_rate % CHIP_RATE != 0:
        raise ValueError("sample_rate must be an integer multiple of the chip rate")
    samples_per_chip = int(sample_rate // CHIP_RATE)

    if np.iscomplexobj(samples):
        baseband = samples.astype(np.complex64)
    else:
        if carrier_hz == 0.0:
            # Real signal without carrier — treat as I channel only (Q=0).
            baseband = samples.astype(np.float32).astype(np.complex64)
        else:
            baseband = _downconvert_real_to_complex(samples, sample_rate, carrier_hz)

    # Generate reference PRN chips for both channels
    i_prn = np.array(prn_generator(mode, "i").generate_segment(SEGMENT_CHIPS),
                     dtype=np.int8)
    q_prn = np.array(prn_generator(mode, "q").generate_segment(SEGMENT_CHIPS),
                     dtype=np.int8)
    i_ref = 1 - 2 * i_prn.astype(np.float32)   # {-1, +1}
    q_ref = 1 - 2 * q_prn.astype(np.float32)

    # Downsample: take the sample at the centre of each chip for I, and
    # the sample half a chip later for Q (to match the OQPSK delay).
    half_chip = samples_per_chip // 2
    i_samples = baseband.real[half_chip::samples_per_chip][:SEGMENT_CHIPS]
    q_start = half_chip + half_chip  # centre of the Q chip (which is delayed by half a chip)
    q_samples = baseband.imag[q_start::samples_per_chip][:SEGMENT_CHIPS]

    # Correlate each 256-chip window with the PRN to recover each bit.
    def _correlate_bits(chips: np.ndarray, ref: np.ndarray) -> str:
        bits = []
        # Skip preamble bits; they decode to all-zero by construction but
        # are not part of the message.
        for k in range(PREAMBLE_BITS_PER_CHANNEL, BITS_PER_CHANNEL):
            lo = k * CHIPS_PER_BIT
            hi = lo + CHIPS_PER_BIT
            corr = float(np.dot(chips[lo:hi], ref[lo:hi]))
            # bit=0 -> chips == PRN -> corr positive. bit=1 -> chips == -PRN
            # (inverted) -> corr negative.
            bits.append("0" if corr > 0 else "1")
        return "".join(bits)

    i_bits = _correlate_bits(i_samples, i_ref)
    q_bits = _correlate_bits(q_samples, q_ref)

    # Interleave I and Q back into the 250-bit message (I=odd, Q=even).
    out = []
    for a, b in zip(i_bits, q_bits):
        out.append(a)
        out.append(b)
    message = "".join(out)

    info = {
        "mode": mode,
        "carrier_hz": carrier_hz,
        "sample_rate": sample_rate,
        "samples_per_chip": samples_per_chip,
        "segment_chips": SEGMENT_CHIPS,
        "i_bits_recovered": i_bits,
        "q_bits_recovered": q_bits,
    }
    return message, info


__all__ = [
    "CHIP_RATE", "BIT_RATE_PER_CHANNEL", "CHIPS_PER_BIT",
    "PREAMBLE_CHIPS", "MESSAGE_CHIPS", "SEGMENT_CHIPS",
    "PREAMBLE_BITS_PER_CHANNEL", "MESSAGE_BITS_PER_CHANNEL",
    "BITS_PER_CHANNEL", "BURST_DURATION_S",
    "ModulationParams", "modulate", "demodulate",
    "build_chip_streams",
]
