#!/usr/bin/env python3
"""Fixed-point IEEE 802.15.4 2.4 GHz O-QPSK TX reference model (integer only).

PSDU octets in, ``tx_dev`` words at 8 Msps out (decisions 0005 and 0007).
Chain: FCS (ITU-T CRC-16) -> SHR/PHR/PSDU octets -> 4-bit symbols -> 32-chip
spreading -> half-sine O-QPSK, emitted as the constant-envelope frequency
word (+/-64 LSB per chip interval). Clause numbers are carried in README.md
and are marked unverified there; every width and rule is written down in it.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traces  # noqa: E402

AMPLITUDE = 100               # int8 I/Q amplitude of the ideal-modulator stimulus
SPS_CHIP = 4                  # samples per chip: 8 Msps / 2 Mchip/s
CHIPS_PER_SYMBOL = 32
DEV_PEAK = 64                 # +/-64 LSB = +/-500 kHz at 7.8125 kHz/LSB (decision 0005)
PREAMBLE_OCTETS = 4           # 0x00 x4
DEFAULT_SFD = 0xA7
MAX_PSDU_OCTETS = 127

# Chip sequence of data symbol 0, first-transmitted chip (c0) first.
_SYMBOL0 = "11011001110000110101001000101110"


def _build_chip_table():
    base = [int(c) for c in _SYMBOL0]
    table = []
    for s in range(8):                       # symbols 1..7: right rotate by 4 chips per step
        r = (4 * s) % CHIPS_PER_SYMBOL
        table.append(base[-r:] + base[:-r] if r else list(base))
    for s in range(8):                       # symbols 8..15: odd-indexed chips inverted
        table.append([c ^ (k & 1) for k, c in enumerate(table[s])])
    return tuple(tuple(row) for row in table)


CHIP_TABLE = _build_chip_table()


def crc16_fcs(data):
    """ITU-T CRC-16 (x^16+x^12+x^5+1), init 0, bits LSB first (reflected form).
    The two FCS octets are this value little-endian."""
    state = 0
    for b in data:
        state ^= b
        for _ in range(8):
            state = (state >> 1) ^ (0x8408 if state & 1 else 0)
    return state


def with_fcs(mpdu):
    """Append the FCS to the PSDU payload (MPDU without FCS)."""
    return bytes(mpdu) + crc16_fcs(mpdu).to_bytes(2, "little")


def symbols_of(octets):
    """Octets to 4-bit symbols, least significant nibble of each octet first."""
    return [n for b in octets for n in (b & 0xF, b >> 4)]


def ppdu_octets(psdu, sfd=DEFAULT_SFD):
    """SHR (preamble + SFD), PHR (7-bit length, reserved bit 0), PSDU."""
    if len(psdu) > MAX_PSDU_OCTETS:
        raise ValueError(f"PSDU longer than {MAX_PSDU_OCTETS} octets")
    return bytes(PREAMBLE_OCTETS) + bytes([sfd, len(psdu)]) + bytes(psdu)


def spread(symbols):
    """Symbols to the chip stream (0/1), 32 chips each."""
    return [c for s in symbols for c in CHIP_TABLE[s]]


def chip_dev_signs(chips):
    """Sign of the frequency deviation in each chip interval of the half-sine
    O-QPSK signal (even chips on I, odd chips on Q delayed by one chip).

    With chip values c_k in {-1,+1}: interval k (k >= 1) turns the phase by
    -c_k c_{k-1} pi/2 for even k and +c_k c_{k-1} pi/2 for odd k. The first
    interval (only an I pulse rising from zero) and the interval after the last
    chip (only a Q pulse falling to zero) carry no phase change: sign 0.
    Returns len(chips) + 1 signs.
    """
    c = [1 if x else -1 for x in chips]
    signs = [0]
    for k in range(1, len(c)):
        p = c[k] * c[k - 1]
        signs.append(-p if k % 2 == 0 else p)
    signs.append(0)
    return signs


def tx_dev_words(psdu, sfd=DEFAULT_SFD):
    """tx_dev words (signed int8 range) for one PPDU."""
    signs = chip_dev_signs(spread(symbols_of(ppdu_octets(psdu, sfd))))
    return [DEV_PEAK * s for s in signs for _ in range(SPS_CHIP)]


def modulate(words, lead=37, tail=300, amplitude=AMPLITUDE):
    """Ideal frequency modulator standing in for the front end: phase += 64 *
    tx_dev per sample, turns/2**16; int8 I/Q at 8 Msps with a quiet lead-in and
    tail. The one stimulus definition shared by the model tests and the RTL
    replay (decision 0007)."""
    import numpy as np  # local: the rest of this model is integer-only, numpy-free

    dev = np.concatenate([np.zeros(lead, dtype=np.int64), np.array(words, dtype=np.int64),
                          np.zeros(tail, dtype=np.int64)])
    phase = np.cumsum(64 * dev)
    ang = 2.0 * np.pi * (phase % (1 << 16)) / (1 << 16)
    iq = np.stack([np.rint(amplitude * np.cos(ang)), np.rint(amplitude * np.sin(ang))], axis=1)
    iq = iq.astype(np.int8)
    iq[:lead] = 0
    return iq


def trace_records(words):
    """txact rises at index 0 and falls one sample after the last word."""
    yield (0, "txact", 1)
    for i, w in enumerate(words):
        yield (i, "txdev", traces.to_unsigned(w, 8))
    yield (len(words) + 1, "txact", 0)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--psdu", required=True, help="PSDU octets as hex")
    p.add_argument("--append-fcs", action="store_true", help="treat --psdu as the payload and append the FCS")
    p.add_argument("--out", required=True, help="trace file to write")
    a = p.parse_args(argv)
    psdu = bytes.fromhex(a.psdu)
    if a.append_fcs:
        psdu = with_fcs(psdu)
    words = tx_dev_words(psdu)
    traces.write_trace(a.out, trace_records(words))
    print(f"wrote {len(words)} tx_dev words to {a.out}")


if __name__ == "__main__":
    main()
