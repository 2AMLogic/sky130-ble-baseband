#!/usr/bin/env python3
"""LE 1M test-packet bit builder for the BER sweep (stimulus side only).

Preamble, access address, PDU and CRC-24 in on-air order, octets LSB first.
Data whitening is omitted: it is a bijection on the bit stream and the payload
is already uniformly random, so it changes no error statistic (the swept
receiver does not de-whiten). Core Specification references: Vol 6 Part B
2.1 (preamble), 2.1.2 (access address), 2.3 (PDU), 3.1.1 (CRC).

The CRC here is computed by polynomial division, independently of the
bit-serial register in ``sim/model/le1m_rx.py``, so the two cross-check.
"""

DEFAULT_ACCESS_ADDRESS = 0x8E89BED6
DEFAULT_CRC_INIT = 0x555555
CRC_POLY_FULL = (1 << 24) | 0x00065B   # x^24+x^10+x^9+x^6+x^4+x^3+x+1
MAX_PAYLOAD_OCTETS = 255


def octets_to_bits(data):
    return [(b >> i) & 1 for b in data for i in range(8)]


def crc24_division(pdu_bits, init=DEFAULT_CRC_INIT):
    """CRC-24 register value as the remainder of (init . x^n + data) . x^24."""
    n = len(pdu_bits)
    msg = 0
    for b in pdu_bits:
        msg = (msg << 1) | b
    value = (init << n) ^ (msg << 24)
    top = value.bit_length() - 1
    while top >= 24:
        value ^= CRC_POLY_FULL << (top - 24)
        top = value.bit_length() - 1
    return value


def build_frame_bits(payload, header0=0x00, access_address=DEFAULT_ACCESS_ADDRESS,
                     crc_init=DEFAULT_CRC_INIT):
    """On-air bits for a PDU of ``header0``, length octet, ``payload`` octets.
    Returns (bits, pdu_bit_count)."""
    if len(payload) > MAX_PAYLOAD_OCTETS:
        raise ValueError("payload longer than 255 octets")
    preamble = 0x55 if access_address & 1 else 0xAA
    pdu_bits = octets_to_bits(bytes([header0, len(payload)]) + bytes(payload))
    crc = crc24_division(pdu_bits, crc_init)
    crc_bits = [(crc >> i) & 1 for i in range(23, -1, -1)]
    bits = (octets_to_bits([preamble]) + octets_to_bits(access_address.to_bytes(4, "little"))
            + pdu_bits + crc_bits)
    return bits, len(pdu_bits)
