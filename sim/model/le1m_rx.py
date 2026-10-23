#!/usr/bin/env python3
"""Fixed-point non-coherent LE 1M receiver (decisions 0003 and 0007).

Integer arithmetic only in the data path (numpy int64 carrying values of the
documented widths). Input is the RX stimulus of decision 0007: int8 I/Q at
8 Msps plus the flags and gain columns. Every width, rounding and saturation
rule is in README.md; the constants below are the model's registers.

Chain: channel FIR -> delay-and-multiply phase-difference discriminator
(CORDIC angle) -> 8-sample symbol integrator -> access-address correlator with
a preamble-derived frequency-offset estimate -> data-directed offset tracker and
early-late timing loop -> hard decision, length parse, CRC-24.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import traces  # noqa: E402

SPS = 8
DEFAULT_ACCESS_ADDRESS = 0x8E89BED6
DEFAULT_CRC_INIT = 0x555555
CRC_POLY = 0x00065B

# --- registers / constants (README.md "Width table") ---
FIR_TAPS = (1, 4, 9, 16, 22, 24, 22, 16, 9, 4, 1)   # symmetric, sum = 2**FIR_SHIFT
FIR_SHIFT = 7
FIR_OUT_BITS = 9                                    # saturating
ANGLE_BITS = 16                                     # full turn = 2**16
CORDIC_ITERATIONS = 12
SYNC_BITS = 40                                      # preamble 8 + access address 32
SYNC_NUM, SYNC_DEN_SHIFT = 7, 3                     # accept when C >= 7/8 * sum|v - D|
SYNC_MIN_AMPLITUDE = 4096                           # mean |s - D| floor, 1/4 of the nominal 16384
D_SHIFT = 6                                         # offset tracker gain 2**-6
TIMING_THRESHOLD = 48                               # in A/16 units
TIMING_SPAN = 2                                     # early/late tap spacing, samples
CFO_UPDATE_SYMBOLS = 32                             # cfo tap: sync and every 32 symbols
TBOUND_EDGE_SYMBOLS = 16
RSSI_WINDOW = 320                                   # samples averaged for rssi
CFO_TRACE_BITS = 24
MAX_PDU_BITS = (2 + 255) * 8 + 24

_ATAN_TABLE = tuple(
    int(round(np.arctan(2.0 ** -i) / (2.0 * np.pi) * (1 << ANGLE_BITS)))
    for i in range(CORDIC_ITERATIONS)
)


def _bits_of(octets):
    return [(b >> i) & 1 for b in octets for i in range(8)]


def sync_pattern(access_address=DEFAULT_ACCESS_ADDRESS):
    """Preamble + access address, on-air order, as +1/-1 (bit 1 = +frequency)."""
    preamble = 0x55 if access_address & 1 else 0xAA
    bits = _bits_of([preamble]) + _bits_of(access_address.to_bytes(4, "little"))
    return np.array([1 if b else -1 for b in bits], dtype=np.int64)


def crc24(bits, init=DEFAULT_CRC_INIT):
    """Bit-serial CRC-24 register over ``bits`` (Vol 6 Part B 3.1.1)."""
    state = init & 0xFFFFFF
    for bit in bits:
        fb = ((state >> 23) & 1) ^ bit
        state = (state << 1) & 0xFFFFFF
        if fb:
            state ^= CRC_POLY
    return state


def saturate(x, bits):
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return np.clip(x, lo, hi)


def channel_filter(x):
    """Causal FIR, round-half-up, saturate to FIR_OUT_BITS."""
    y = np.convolve(x.astype(np.int64), np.array(FIR_TAPS, dtype=np.int64))[: len(x)]
    return saturate((y + (1 << (FIR_SHIFT - 1))) >> FIR_SHIFT, FIR_OUT_BITS)


def cordic_angle(x, y):
    """Vectoring-mode CORDIC: angle of (x, y) in turns / 2**ANGLE_BITS, wrapped
    to signed ANGLE_BITS. Arithmetic shifts, truncating; an all-zero input is
    forced to 0."""
    x = x.astype(np.int64).copy()
    y = y.astype(np.int64).copy()
    zero = (x == 0) & (y == 0)
    neg = x < 0
    x = np.where(neg, -x, x)
    y = np.where(neg, -y, y)
    acc = np.where(neg, 1 << (ANGLE_BITS - 1), 0).astype(np.int64)
    for i, a in enumerate(_ATAN_TABLE):
        up = y >= 0
        xs, ys = x >> i, y >> i
        x, y = np.where(up, x + ys, x - ys), np.where(up, y - xs, y + xs)
        acc = np.where(up, acc + a, acc - a)
    acc = np.where(zero, 0, acc)
    half = 1 << (ANGLE_BITS - 1)
    return ((acc + half) & ((1 << ANGLE_BITS) - 1)) - half


def discriminate(i, q):
    """Angle of z[n] * conj(z[n-1]); sample 0 is 0."""
    re = i[1:] * i[:-1] + q[1:] * q[:-1]
    im = q[1:] * i[:-1] - i[1:] * q[:-1]
    out = np.zeros(len(i), dtype=np.int64)
    out[1:] = cordic_angle(re, im)
    return out


def integrate(f):
    """8-sample moving sum, s[n] = f[n-7] + ... + f[n]."""
    c = np.cumsum(f)
    s = c.copy()
    s[SPS:] -= c[:-SPS]
    return s


def find_sync(s, pattern):
    """Streaming acquisition: first sample whose normalised correlation passes
    the threshold, then the best of the next SPS samples. Returns
    (n, amplitude A, offset D) or None."""
    nsym = len(pattern)
    span = SPS * (nsym - 1)
    ncorr = len(s) - span
    if ncorr <= 0:
        return None
    v = np.stack([s[SPS * j: SPS * j + ncorr] for j in range(nsym)])
    d = v[:SPS].sum(axis=0) >> 3
    w = v - d
    corr = (pattern[:, None] * w).sum(axis=0)
    mag = np.abs(w).sum(axis=0)
    ok = ((corr >= SYNC_MIN_AMPLITUDE * nsym)
          & ((corr << SYNC_DEN_SHIFT) >= SYNC_NUM * mag))
    hits = np.flatnonzero(ok)
    if hits.size == 0:
        return None
    k0 = int(hits[0])
    k = k0 + int(np.argmax(corr[k0: k0 + SPS]))
    a = (int(corr[k]) * 1639 + (1 << 15)) >> 16           # corr / 40
    psum = int(pattern.sum())
    dk = (int(v[:, k].sum()) - a * psum)
    dk = (dk * 1639 + (1 << 15)) >> 16 if dk >= 0 else -(((-dk) * 1639 + (1 << 15)) >> 16)
    return k + span, max(a, 1), dk


def demodulate(iq, flags=None, gain=None, access_address=DEFAULT_ACCESS_ADDRESS,
               crc_init=DEFAULT_CRC_INIT):
    """Receive one packet from an RX stimulus. Returns a dict: ``synced``,
    ``bits`` (PDU+CRC bits as demodulated, np.uint8), ``crc_ok``, ``sync_index``,
    ``pdu_bits`` (length claimed by the header), ``trace`` (0007 records)."""
    i = channel_filter(iq[:, 0])
    q = channel_filter(iq[:, 1])
    f = discriminate(i, q)
    s = integrate(f)

    records = []
    if flags is not None and gain is not None:
        for n in np.flatnonzero(np.asarray(flags) & 2):
            records.append((int(n), "gain", int(gain[n])))

    result = {"synced": False, "bits": np.zeros(0, dtype=np.uint8), "crc_ok": False,
              "sync_index": None, "pdu_bits": 0, "trace": records, "timing_steps": 0,
              "offset_hat": 0, "amplitude": 0}
    hit = find_sync(s, sync_pattern(access_address))
    if hit is None:
        return result
    t, amp, d = hit
    result.update(synced=True, sync_index=t, offset_hat=d, amplitude=amp)
    records.append((t, "sync", 1))
    records.append((t, "cfo", traces.to_unsigned(_clip_signed(d, CFO_TRACE_BITS), CFO_TRACE_BITS)))

    sl = s.tolist()
    n_total = len(sl)
    inv_a = (1 << 16) // amp
    bits = []
    boundaries = []                       # (sample index, symbol number, forced)
    tacc = 0
    want = 16                             # header first, then the claimed length
    sym = 0
    while sym < want:
        t += SPS
        if t + TIMING_SPAN >= n_total:
            break
        v = sl[t] - d
        b = 1 if v > 0 else 0
        bits.append(b)
        records.append((t, "bit", b))
        boundaries.append((t, sym))
        e = abs(sl[t + TIMING_SPAN] - d) - abs(sl[t - TIMING_SPAN] - d)
        tacc += (e * inv_a) >> 12
        step = 0
        if tacc >= TIMING_THRESHOLD:
            step, tacc = 1, tacc - TIMING_THRESHOLD
        elif tacc <= -TIMING_THRESHOLD:
            step, tacc = -1, tacc + TIMING_THRESHOLD
        if step:
            t += step
            result["timing_steps"] += 1
            records.append((t, "tbound", sym & 0xFFFFFF))
        d += (v - (amp if b else -amp)) >> D_SHIFT
        sym += 1
        if (sym % CFO_UPDATE_SYMBOLS) == 0:
            records.append((t, "cfo", traces.to_unsigned(_clip_signed(d, CFO_TRACE_BITS), CFO_TRACE_BITS)))
        if sym == 16:
            length = sum(bits[8 + k] << k for k in range(8))
            want = 16 + 8 * length + 24
            result["pdu_bits"] = 16 + 8 * length
    for (idx, k) in boundaries:
        if k < TBOUND_EDGE_SYMBOLS or k >= len(boundaries) - TBOUND_EDGE_SYMBOLS:
            records.append((idx, "tbound", k))
    result["bits"] = np.array(bits, dtype=np.uint8)
    if len(bits) == want and want >= 16 + 24:
        npdu = result["pdu_bits"]
        crc_rx = 0
        for b in bits[npdu: npdu + 24]:
            crc_rx = (crc_rx << 1) | b
        result["crc_ok"] = crc24(bits[:npdu], crc_init) == crc_rx
        last = boundaries[-1][0]
        records.append((last, "crc", 1 if result["crc_ok"] else 0))
        records.append((last, "rssi", _rssi(i, q, result["sync_index"])))
    records.sort(key=lambda r: r[0])
    return result


def _clip_signed(v, bits):
    return int(max(-(1 << (bits - 1)), min((1 << (bits - 1)) - 1, v)))


def _rssi(i, q, end):
    lo = max(0, end - RSSI_WINDOW + 1)
    ai, aq = np.abs(i[lo: end + 1]), np.abs(q[lo: end + 1])
    mag = np.maximum(ai, aq) + (np.minimum(ai, aq) >> 1)     # alpha-max-beta-min
    return (int(mag.sum()) * 205 + (1 << 15)) >> 16           # ~ / 320
