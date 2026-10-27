#!/usr/bin/env python3
"""Fixed-point non-coherent IEEE 802.15.4 O-QPSK receiver (decisions 0003, 0007).

Integer arithmetic only in the data path (numpy int64 carrying values of the
documented widths). Input is the RX stimulus of decision 0007: int8 I/Q at
8 Msps plus the flags and gain columns. Every width, rounding and saturation
rule is in README.md; the constants below are the model's registers.

Chain: channel FIR -> delay-and-multiply discriminator (CORDIC angle, shared
with ``le1m_rx``) -> 4-sample chip integrator -> chip-rate differential
despreader (16 correlators over the 31 within-symbol chip transitions) ->
preamble run detect -> SFD match -> PHR length -> PSDU octets -> FCS check.

The despreader works on products of adjacent chips, which a frequency
discriminator observes directly, so no carrier phase is needed (non-coherent,
provisional per 0003). No frequency-offset estimate is made: residual offset
is out of scope for this model version.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import le1m_rx  # noqa: E402
import oqpsk_tx  # noqa: E402
import traces  # noqa: E402

SPS_CHIP = oqpsk_tx.SPS_CHIP
SYMBOL_SAMPLES = SPS_CHIP * oqpsk_tx.CHIPS_PER_SYMBOL        # 128
NTAPS = oqpsk_tx.CHIPS_PER_SYMBOL - 1                        # 31 transitions per symbol

# --- registers / constants (README.md "802.15.4 width table") ---
FIR_TAPS = (1, 4, 6, 4, 1)                  # symmetric, sum = 2**FIR_SHIFT
FIR_SHIFT = 4
FIR_OUT_BITS = 9                            # saturating
MIN_AMPLITUDE = 4096                        # mean |g| floor per transition, 1/4 of nominal 16384
ACCEPT_NUM, ACCEPT_DEN_SHIFT = 3, 2         # accept when corr >= 3/4 * sum|g|
PREAMBLE_RUN = 4                            # consecutive symbol-0 matches that arm the SFD search
MAX_PREAMBLE_SYMBOLS = 16                   # symbol-0 run beyond this aborts the search
TBOUND_EDGE_CHIPS = 16
WINDOW_END = SPS_CHIP * (NTAPS - 1)          # sample offset of a symbol's end from its corr index


def _weights():
    """W[m, j]: expected sign of the chip-interval frequency for symbol m,
    transition k = j + 1 (see oqpsk_tx.chip_dev_signs)."""
    w = np.zeros((16, NTAPS), dtype=np.int64)
    for m, row in enumerate(oqpsk_tx.CHIP_TABLE):
        signs = oqpsk_tx.chip_dev_signs(row)
        w[m] = signs[1:oqpsk_tx.CHIPS_PER_SYMBOL]
    return w


WEIGHTS = _weights()


def channel_filter(x):
    """Causal FIR, round-half-up, saturate to FIR_OUT_BITS."""
    y = np.convolve(x.astype(np.int64), np.array(FIR_TAPS, dtype=np.int64))[: len(x)]
    return le1m_rx.saturate((y + (1 << (FIR_SHIFT - 1))) >> FIR_SHIFT, FIR_OUT_BITS)


def chip_integrate(f):
    """4-sample moving sum, g[n] = f[n-3] + ... + f[n]. Nominal +/-16384."""
    c = np.cumsum(f)
    g = c.copy()
    g[SPS_CHIP:] -= c[:-SPS_CHIP]
    return g


def correlate(g):
    """Symbol correlators. Window tap j (transition k = j + 1) is
    ``g[i + SPS_CHIP*j]``, so the window for corr index ``i`` ends (chip 31) at
    sample ``i + WINDOW_END``. Returns ``corr`` (16 x ncorr, signed) and ``mag``
    (sum of |tap|, unsigned)."""
    ncorr = len(g) - WINDOW_END
    if ncorr <= 0:
        return np.zeros((16, 0), dtype=np.int64), np.zeros(0, dtype=np.int64)
    v = np.stack([g[SPS_CHIP * j: SPS_CHIP * j + ncorr] for j in range(NTAPS)])
    return WEIGHTS @ v, np.abs(v).sum(axis=0)


def _accept(corr_best, mag):
    return (corr_best >= MIN_AMPLITUDE * NTAPS) & ((corr_best << ACCEPT_DEN_SHIFT) >= ACCEPT_NUM * mag)


def _walk_to_sfd(best, ok, i0, ncorr):
    """From a preamble run ending at corr index ``i0``, read symbols one per
    128 samples until symbol 7 then symbol 10 (SFD 0xA7, low nibble first).
    Returns the corr index of the SFD's last symbol, or (None, failed_at)."""
    i = i0
    zeros = PREAMBLE_RUN
    while True:
        i += SYMBOL_SAMPLES
        if i >= ncorr or not ok[i]:
            return None, i
        s = int(best[i])
        if s == 0:
            zeros += 1
            if zeros > MAX_PREAMBLE_SYMBOLS:
                return None, i
            continue
        if s != oqpsk_tx.DEFAULT_SFD & 0xF:
            return None, i
        i += SYMBOL_SAMPLES
        if i >= ncorr or not ok[i] or int(best[i]) != oqpsk_tx.DEFAULT_SFD >> 4:
            return None, i
        return i, i


def demodulate(iq, flags=None, gain=None):
    """Receive one packet from an RX stimulus. Returns a dict: ``synced``,
    ``psdu`` (octets as demodulated, bytes), ``crc_ok`` (FCS pass), ``length``
    (PHR length field, None before PHR), ``sync_index``, ``trace`` (0007
    records), ``timing_steps``."""
    i_f = channel_filter(iq[:, 0])
    q_f = channel_filter(iq[:, 1])
    g = chip_integrate(le1m_rx.discriminate(i_f, q_f))
    corr, mag = correlate(g)
    ncorr = corr.shape[1]

    records = []
    if flags is not None and gain is not None:
        for n in np.flatnonzero(np.asarray(flags) & 2):
            records.append((int(n), "gain", int(gain[n])))
    result = {"synced": False, "psdu": b"", "crc_ok": False, "length": None,
              "sync_index": None, "trace": records, "timing_steps": 0}
    if ncorr <= 0:
        return result

    best = np.argmax(corr, axis=0)
    ok = _accept(corr[best, np.arange(ncorr)], mag)
    zero = ok & (best == 0)
    run = zero.copy()
    for k in range(1, PREAMBLE_RUN):
        run[SYMBOL_SAMPLES * k:] &= zero[: ncorr - SYMBOL_SAMPLES * k]
        run[: SYMBOL_SAMPLES * k] = False
    hits = np.flatnonzero(run)

    floor = 0
    sfd_i = None
    for h in hits:
        if h < floor:
            continue
        h = int(h)
        # settle on the best of the next chip's worth of samples
        h += int(np.argmax(corr[0, h: min(h + SPS_CHIP, ncorr)]))
        sfd_i, floor = _walk_to_sfd(best, ok, h, ncorr)
        if sfd_i is not None:
            break
    if sfd_i is None:
        return result

    t = sfd_i
    result.update(synced=True, sync_index=t + WINDOW_END)
    records.append((t + WINDOW_END, "sync", 1))

    nsym_total = 2          # PHR, then 2 per PSDU octet once the length is known
    syms = []
    sym = 0
    boundaries = []         # (sample, packet chip number)
    while sym < nsym_total:
        t += SYMBOL_SAMPLES
        if t + 1 >= ncorr:
            break
        m = int(np.argmax(corr[:, t]))
        syms.append(m)
        step = 0
        if corr[m, t - 1] > corr[m, t] and corr[m, t - 1] >= corr[m, t + 1]:
            step = -1
        elif corr[m, t + 1] > corr[m, t]:
            step = 1
        base = t
        t += step
        for k in range(oqpsk_tx.CHIPS_PER_SYMBOL):
            boundaries.append((base + WINDOW_END - SPS_CHIP * (31 - k), 32 * sym + k))
        if step:
            result["timing_steps"] += 1
            records.append((t + WINDOW_END, "tbound", 32 * sym + 31))
        sym += 1
        if sym == 2:
            length = (syms[0] | (syms[1] << 4)) & 0x7F
            result["length"] = length
            nsym_total = 2 + 2 * length
    for idx, q in boundaries:
        if q < TBOUND_EDGE_CHIPS or q >= nsym_total * 32 - TBOUND_EDGE_CHIPS:
            records.append((idx, "tbound", q))
    if result["length"] is None:
        records.sort(key=lambda r: r[0])
        return result

    psdu = bytearray()
    for o in range(0, 2 * ((len(syms) - 2) // 2), 2):
        psdu.append(syms[2 + o] | (syms[3 + o] << 4))
        idx = boundaries[32 * (3 + o) + 31][0]
        records.append((idx, "octet", psdu[-1]))
    result["psdu"] = bytes(psdu)
    if len(syms) == nsym_total and result["length"] >= 2:
        ok_fcs = oqpsk_tx.crc16_fcs(psdu[:-2]) == int.from_bytes(psdu[-2:], "little")
        result["crc_ok"] = ok_fcs
        last = boundaries[-1][0]
        records.append((last, "crc", 1 if ok_fcs else 0))
        records.append((last, "rssi", le1m_rx._rssi(i_f, q_f, result["sync_index"])))
    elif len(syms) == nsym_total:
        records.append((boundaries[-1][0], "crc", 0))
    records.sort(key=lambda r: r[0])
    return result
