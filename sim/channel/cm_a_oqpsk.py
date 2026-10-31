#!/usr/bin/env python3
"""CM-A channel model for IEEE 802.15.4 O-QPSK (target-spec "Channel model").

Same stage order, resampling, AGC and quantization as ``cm_a`` (LE 1M); only
the source, the swept quantity and the timing-phase range differ:

1. Source: the TX reference model's ``tx_dev`` words (``model/oqpsk_tx.py``)
   integrated by the same ideal frequency modulator as ``oqpsk_tx.modulate``
   (phase += 64 * tx_dev per sample, turns / 2**16), but with unit amplitude and
   no int8 rounding. 8 Msps complex, constant envelope, unit mean power.
   Noise-only lead-in and tail around it.
2. Static carrier-frequency offset (no drift: target-spec "802.15.4 carrier
   drift"), 4. relative chip-clock offset and initial timing phase uniform over
   one chip (4 samples), 5. initial carrier phase: as ``cm_a``.
6. AWGN, complex, generated over the full 8 MHz simulation bandwidth. The swept
   quantity is SNR = signal power / noise power in a 2 MHz noise bandwidth, so
   sigma^2 = (fs / 2 MHz) / 10^(SNR/10) for unit signal power.
7. Fixed AGC and 8-bit quantization, clipping counted: ``cm_a``'s rule.

Nothing is clamped to the spec ranges: an offset outside the row's range is
injected as asked (negative controls rely on that).
"""

import math
import os
import sys
from dataclasses import dataclass

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(os.path.dirname(HERE), "model")]
import cm_a  # noqa: E402
import oqpsk_tx  # noqa: E402

FS = cm_a.FS
NOISE_BANDWIDTH_HZ = 2_000_000
SPS_CHIP = oqpsk_tx.SPS_CHIP            # 4 samples per chip
CFO_SPEC_HZ = 196_000.0                 # +-80 ppm relative at 2.45 GHz (two +-40 ppm ends)
CLOCK_SPEC_PPM = 80.0


@dataclass(frozen=True)
class OqpskParams:
    """One CM-A operating point. ``draw_*`` means draw per packet uniformly from
    ``+/- *_range`` instead of using the fixed value."""

    snr_db: float = math.inf
    cfo_hz: float = 0.0
    cfo_range_hz: float = CFO_SPEC_HZ
    clock_ppm: float = 0.0
    clock_range_ppm: float = CLOCK_SPEC_PPM
    lead_samples: int = 512
    tail_samples: int = 512
    draw_cfo: bool = False
    draw_clock: bool = False

    def describe(self):
        """JSON-able, deterministic description (used in seeds and reports)."""
        return {
            "snr_db": "inf" if math.isinf(self.snr_db) else self.snr_db,
            "cfo_hz": "uniform" if self.draw_cfo else self.cfo_hz,
            "cfo_range_hz": self.cfo_range_hz,
            "clock_ppm": "uniform" if self.draw_clock else self.clock_ppm,
            "clock_range_ppm": self.clock_range_ppm,
            "lead_samples": self.lead_samples,
            "tail_samples": self.tail_samples,
        }


def oqpsk_baseband(psdu):
    """Unit-amplitude complex O-QPSK waveform for ``psdu`` at 8 Msps."""
    words = np.array(oqpsk_tx.tx_dev_words(psdu), dtype=np.int64)
    phase_turns = np.cumsum(64 * words) / float(1 << 16)
    return np.exp(2j * np.pi * phase_turns)


def noise_variance(snr_db):
    """Complex noise variance for unit signal power: noise power in the 2 MHz
    reference bandwidth is sigma^2 * 2 MHz / fs, so sigma^2 = (fs / 2 MHz) / SNR."""
    if math.isinf(snr_db):
        return 0.0
    return (FS / NOISE_BANDWIDTH_HZ) / 10.0 ** (snr_db / 10.0)


def generate_packet(psdu, params, rng, keep_float=False):
    """Pass one packet (``psdu`` octets) through CM-A. ``rng`` is a
    ``numpy.random.Generator`` (PCG64); the draw order is fixed, so the output
    is a pure function of its state. Returns a ``cm_a.ChannelOutput``."""
    cfo = rng.uniform(-params.cfo_range_hz, params.cfo_range_hz) if params.draw_cfo else params.cfo_hz
    clock = (rng.uniform(-params.clock_range_ppm, params.clock_range_ppm)
             if params.draw_clock else params.clock_ppm)
    timing = rng.uniform(0.0, SPS_CHIP)
    phase0 = rng.uniform(0.0, 2.0 * np.pi)

    sig = oqpsk_baseband(psdu)
    lead = params.lead_samples
    total = lead + len(sig) + params.tail_samples
    x = np.zeros(total, dtype=complex)
    x[lead:lead + len(sig)] = sig
    theta = phase0 + 2.0 * np.pi * cfo * np.arange(total) / FS

    step = 1.0 + clock * 1e-6
    m = int((total - 4 - timing - 1) / step)
    tau = 1.0 + timing + step * np.arange(m)
    xr = cm_a._lagrange4(x, tau) * np.exp(1j * cm_a._lagrange4(theta, tau))

    var = noise_variance(params.snr_db)
    if var > 0.0:
        nz = rng.standard_normal((m, 2)) * math.sqrt(var / 2.0)
        xr = xr + nz[:, 0] + 1j * nz[:, 1]

    rms = math.sqrt(float(np.mean(np.abs(xr) ** 2)))
    gidx = cm_a.agc_gain_index(rms)
    g = cm_a.gain_from_index(gidx)
    qi, qq = np.rint(g * xr.real), np.rint(g * xr.imag)
    sat = (qi < -128) | (qi > 127) | (qq < -128) | (qq > 127)
    iq = np.stack([np.clip(qi, -128, 127), np.clip(qq, -128, 127)], axis=1).astype(np.int8)
    flags = sat.astype(np.uint8)
    flags[0] |= 2                                  # gain_reply strobe before sample 0
    gain = np.full(m, gidx, dtype=np.uint8)
    start = int(round((lead - 1 - timing) / step))
    stop = int(round((lead + len(sig) - 1 - timing) / step))
    return cm_a.ChannelOutput(iq, flags, gain, int(sat.sum()), float(cfo), float(clock),
                              float(timing), float(phase0), var, gidx, max(start, 0), min(stop, m),
                              xr if keep_float else None)
