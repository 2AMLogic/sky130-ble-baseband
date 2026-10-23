#!/usr/bin/env python3
"""Fixed-point LE 1M TX reference model (pure integer arithmetic).

PDU octets in, ``tx_dev`` words at 8 Msps out (decisions 0005 and 0007).
Core Specification references are Vol 6 Part B; every width, rounding and
saturation rule is written down in README.md.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traces  # noqa: E402

SPS = 8                       # samples per symbol (8 Msps / 1 Msym/s)
DEFAULT_ACCESS_ADDRESS = 0x8E89BED6   # advertising channels, Vol 6 Part B 2.1.2
DEFAULT_CRC_INIT = 0x555555           # advertising channels, Vol 6 Part B 3.1.1
CRC_POLY = 0x00065B           # x^24+x^10+x^9+x^6+x^4+x^3+x+1 without the x^24 term
MAX_PDU_OCTETS = 257          # 2 header + 255 payload (largest LE PDU)

# Gaussian pulse shaping, BT = 0.5, 4 symbols span = 33 taps at 8 Msps.
# Unsigned 15-bit taps, symmetric, sum exactly 2**15 = 32 * 2**10, so a
# settled run of one bit gives exactly +/-32 LSB after the >> TAP_SHIFT.
GAUSS_TAPS = (
    0, 0, 0, 0, 0, 0, 0, 1, 5, 26, 112, 382, 1040, 2266, 3952, 5517,
    6166, 5517, 3952, 2266, 1040, 382, 112, 26, 5, 1, 0, 0, 0, 0, 0, 0, 0,
)
TAP_SHIFT = 10
DEV_MIN, DEV_MAX = -128, 127  # int8 tx_dev


def bytes_to_bits(data):
    """Octets to bits, least significant bit of each octet first."""
    return [(b >> i) & 1 for b in data for i in range(8)]


def whiten(bits, channel):
    """Data whitening, x^7+x^4+1 (Vol 6 Part B 3.2).

    Register bit 6 is spec position 0 (preset to 1) and bits 5..0 are the
    channel index, MSB at spec position 1; the output is spec position 6.
    """
    if not 0 <= channel <= 39:
        raise ValueError("channel index must be 0..39")
    state = 0x40 | channel
    out = []
    for b in bits:
        lsb = state & 1
        out.append(b ^ lsb)
        state >>= 1
        if lsb:
            state ^= 0x44
    return out


def crc24(pdu, init=DEFAULT_CRC_INIT):
    """CRC-24 over the PDU octets (Vol 6 Part B 3.1.1).

    Returns the 24-bit register; spec position 23 is bit 23 and is sent first.
    """
    state = init & 0xFFFFFF
    for bit in bytes_to_bits(pdu):
        fb = ((state >> 23) & 1) ^ bit
        state = (state << 1) & 0xFFFFFF
        if fb:
            state ^= CRC_POLY
    return state


def crc_bits(crc):
    return [(crc >> i) & 1 for i in range(23, -1, -1)]


def frame(pdu, channel, access_address=DEFAULT_ACCESS_ADDRESS, crc_init=DEFAULT_CRC_INIT):
    """On-air LE 1M bit sequence: preamble, access address, whitened PDU + CRC."""
    if len(pdu) > MAX_PDU_OCTETS:
        raise ValueError(f"PDU longer than {MAX_PDU_OCTETS} octets")
    preamble = 0x55 if access_address & 1 else 0xAA
    pdu_bits = bytes_to_bits(pdu) + crc_bits(crc24(pdu, crc_init))
    aa = bytes_to_bits(access_address.to_bytes(4, "little"))
    return bytes_to_bits(bytes([preamble])) + aa + whiten(pdu_bits, channel)


def gaussian_shape(bits):
    """Shape a bit sequence into tx_dev words, integer arithmetic only.

    Bits map to NRZ +1/-1 held for SPS samples and are filtered by
    GAUSS_TAPS from a zero state. The word count is SPS * len(bits) +
    len(GAUSS_TAPS) - 1, so the filter drains back to zero.
    """
    nrz = [1 if b else -1 for b in bits for _ in range(SPS)]
    ntaps = len(GAUSS_TAPS)
    half = 1 << (TAP_SHIFT - 1)
    words = []
    for n in range(len(nrz) + ntaps - 1):
        acc = 0
        for k, h in enumerate(GAUSS_TAPS):
            if 0 <= n - k < len(nrz):
                acc += h * nrz[n - k]
        w = (acc + half) >> TAP_SHIFT
        words.append(max(DEV_MIN, min(DEV_MAX, w)))
    return words


def tx_dev_words(pdu, channel, access_address=DEFAULT_ACCESS_ADDRESS, crc_init=DEFAULT_CRC_INIT):
    return gaussian_shape(frame(pdu, channel, access_address, crc_init))


def trace_records(words):
    """txact rises at index 0 and falls one sample after the last word."""
    yield (0, "txact", 1)
    for i, w in enumerate(words):
        yield (i, "txdev", traces.to_unsigned(w, 8))
    yield (len(words) + 1, "txact", 0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pdu", required=True, help="PDU octets (header + payload) as hex")
    p.add_argument("--channel", type=int, required=True, help="channel index 0..39")
    p.add_argument("--access-address", type=lambda s: int(s, 16), default=DEFAULT_ACCESS_ADDRESS)
    p.add_argument("--crc-init", type=lambda s: int(s, 16), default=DEFAULT_CRC_INIT)
    p.add_argument("--out", required=True, help="trace file to write")
    a = p.parse_args(argv)
    words = tx_dev_words(bytes.fromhex(a.pdu), a.channel, a.access_address, a.crc_init)
    traces.write_trace(a.out, trace_records(words))
    print(f"wrote {len(words)} tx_dev words to {a.out}")


if __name__ == "__main__":
    main()
