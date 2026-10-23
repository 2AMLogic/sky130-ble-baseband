#!/usr/bin/env python3
"""CM-A channel model for LE 1M (target-spec "Channel model", decision 0002).

A pure function of (packet bits, parameters, seeded generator). The signal path
follows the spec order, with the stages 2-5 realised as one resampling step:

1. GFSK transmit waveform (h = 0.5, Gaussian BT = 0.5), 8 Msps complex, unit
   mean power over the packet. Noise-only lead-in and tail around it.
2. Carrier-frequency offset, 3. carrier drift, 5. initial carrier phase: one
   unwrapped phase track on the transmit grid.
4. Relative sample-clock offset and initial timing phase: 4-point Lagrange
   resampling of the baseband and of the phase track at the receiver's sample
   instants. (Resampling before the rotation keeps the interpolated signal
   narrow-band; the order is otherwise equivalent.)
6. AWGN, complex, generated over the full 8 MHz simulation bandwidth, variance
   from Eb/N0 (sigma^2 = fs/fsym / 10^(EbN0/10) for unit signal power).
7. AGC (fixed rule, from the noisy received record) and quantization to the
   RX input width, clipping counted.

Nothing is clamped to the spec ranges: an offset outside the row's range is
injected as asked (negative controls rely on that).
"""

import math
from dataclasses import dataclass, field

import numpy as np

FS = 8_000_000            # simulation / RX sample rate, Hz
SYMBOL_RATE = 1_000_000   # LE 1M
SPS = FS // SYMBOL_RATE   # 8
DEVIATION_HZ = 250_000    # h = 0.5 at 1 Msym/s
GAUSS_BT = 0.5
GAUSS_SPAN = 4            # symbols

RX_BITS = 8
AGC_TARGET_RMS = 32.0     # complex rms of the record after gain, in LSB
GAIN_INDEX_BIAS = 32      # gain = 2**((index - 32) / 4)
GAIN_STEPS_PER_OCTAVE = 4
STEPPED_RATE_HZ_PER_US = 20e3 / 50.0   # 20 kHz per 50 us, the spec's peak rate


@dataclass(frozen=True)
class CmAParams:
    """One CM-A operating point. ``None`` for a ``*_hz``/``*_ppm`` value means
    draw it per packet uniformly from ``+/- *_range``."""

    ebn0_db: float = math.inf
    cfo_hz: float = 0.0
    cfo_range_hz: float = 150_000.0
    drift_profile: str = "none"        # none | linear | stepped
    drift_hz: float = 0.0              # signed total drift over the packet
    clock_ppm: float = 0.0
    clock_range_ppm: float = 100.0
    lead_symbols: int = 64
    tail_symbols: int = 64
    draw_cfo: bool = False             # True: cfo_hz ignored, uniform +/- cfo_range_hz
    draw_clock: bool = False           # True: clock_ppm ignored, uniform +/- clock_range_ppm

    def describe(self):
        """JSON-able, deterministic description (used in seeds and reports)."""
        return {
            "ebn0_db": "inf" if math.isinf(self.ebn0_db) else self.ebn0_db,
            "cfo_hz": "uniform" if self.draw_cfo else self.cfo_hz,
            "cfo_range_hz": self.cfo_range_hz,
            "drift_profile": self.drift_profile,
            "drift_hz": self.drift_hz,
            "clock_ppm": "uniform" if self.draw_clock else self.clock_ppm,
            "clock_range_ppm": self.clock_range_ppm,
            "lead_symbols": self.lead_symbols,
            "tail_symbols": self.tail_symbols,
        }


@dataclass
class ChannelOutput:
    iq: np.ndarray            # int8, shape (n, 2)
    flags: np.ndarray         # uint8: bit0 rx_sat, bit1 gain_reply
    gain: np.ndarray          # uint8 gain index in force (0..63)
    clipped: int              # samples with a saturated component
    cfo_hz: float
    clock_ppm: float
    timing_phase: float       # samples, in [0, SPS)
    carrier_phase: float      # rad
    noise_var: float          # complex-sample variance before gain
    gain_index: int
    packet_start: int         # approximate first RX sample of the packet
    packet_stop: int
    float_iq: np.ndarray = field(default=None, repr=False)   # complex, before gain


def _gaussian_taps():
    sigma = math.sqrt(math.log(2.0)) / (2.0 * math.pi * GAUSS_BT) * SPS   # samples
    half = GAUSS_SPAN * SPS // 2
    k = np.arange(-half, half + 1)
    h = np.exp(-(k * k) / (2.0 * sigma * sigma))
    return h / h.sum()


def gfsk_baseband(bits):
    """Unit-amplitude complex GFSK waveform for ``bits`` at 8 Msps; also the
    unwrapped phase. Length is ``SPS * len(bits) + len(taps) - 1``."""
    nrz = np.repeat(np.where(np.asarray(bits) != 0, 1.0, -1.0), SPS)
    freq = DEVIATION_HZ * np.convolve(nrz, _gaussian_taps())
    phase = 2.0 * np.pi * np.cumsum(freq) / FS
    return np.exp(1j * phase)


def drift_track_hz(n, profile, total_hz):
    """Drift f_drift(t) in Hz on n samples. ``linear``: ramp from 0 to
    ``total_hz`` over the packet. ``stepped``: worst case, the whole drift
    taken at the spec's peak rate (20 kHz / 50 us) from the packet midpoint."""
    if profile == "none" or total_hz == 0.0:
        return np.zeros(n)
    t_us = np.arange(n) * (1e6 / FS)
    if profile == "linear":
        return total_hz * np.arange(n) / max(n - 1, 1)
    if profile == "stepped":
        t0 = t_us[n // 2]
        ramp = np.minimum((t_us - t0).clip(min=0.0) * STEPPED_RATE_HZ_PER_US, abs(total_hz))
        return math.copysign(1.0, total_hz) * ramp
    raise ValueError(f"unknown drift profile {profile!r}")


def noise_variance(ebn0_db):
    """Complex noise variance for unit signal power: N0 = sigma^2 / fs and
    Eb = Ps / fsym, so sigma^2 = (fs / fsym) / (Eb/N0)."""
    if math.isinf(ebn0_db):
        return 0.0
    return (FS / SYMBOL_RATE) / 10.0 ** (ebn0_db / 10.0)


def _lagrange4(x, tau):
    """4-point cubic Lagrange interpolation of x at fractional positions tau
    (all 1 <= tau < len(x) - 2)."""
    i = np.floor(tau).astype(np.int64)
    mu = tau - i
    xm1, x0, x1, x2 = x[i - 1], x[i], x[i + 1], x[i + 2]
    c_m1 = -mu * (mu - 1.0) * (mu - 2.0) / 6.0
    c_0 = (mu + 1.0) * (mu - 1.0) * (mu - 2.0) / 2.0
    c_1 = -(mu + 1.0) * mu * (mu - 2.0) / 2.0
    c_2 = (mu + 1.0) * mu * (mu - 1.0) / 6.0
    return c_m1 * xm1 + c_0 * x0 + c_1 * x1 + c_2 * x2


def gain_from_index(index):
    return 2.0 ** ((index - GAIN_INDEX_BIAS) / GAIN_STEPS_PER_OCTAVE)


def agc_gain_index(rms):
    """Fixed AGC rule: settled gain from the rms of the whole noisy received
    record, in 1.5 dB steps, index 0..63. Not derived from the noiseless signal."""
    if rms <= 0.0:
        return 63
    idx = round(GAIN_STEPS_PER_OCTAVE * math.log2(AGC_TARGET_RMS / rms)) + GAIN_INDEX_BIAS
    return int(min(63, max(0, idx)))


def generate_packet(bits, params, rng, keep_float=False):
    """Pass one packet (``bits``, on-air order) through CM-A. ``rng`` is a
    ``numpy.random.Generator`` (PCG64); draw order is fixed, so the output is a
    pure function of its state."""
    cfo = rng.uniform(-params.cfo_range_hz, params.cfo_range_hz) if params.draw_cfo else params.cfo_hz
    clock = (rng.uniform(-params.clock_range_ppm, params.clock_range_ppm)
             if params.draw_clock else params.clock_ppm)
    timing = rng.uniform(0.0, SPS)
    phase0 = rng.uniform(0.0, 2.0 * np.pi)

    sig = gfsk_baseband(bits)
    lead = params.lead_symbols * SPS
    total = lead + len(sig) + params.tail_symbols * SPS
    x = np.zeros(total, dtype=complex)
    x[lead:lead + len(sig)] = sig

    # drift spans the packet only; the tail keeps the final drift value
    drift = drift_track_hz(len(sig), params.drift_profile, params.drift_hz)
    freq = np.full(total, float(cfo))
    freq[lead:lead + len(sig)] += drift
    freq[lead + len(sig):] += drift[-1]
    theta = phase0 + 2.0 * np.pi * np.cumsum(freq) / FS

    step = 1.0 + clock * 1e-6
    m = int((total - 4 - timing - 1) / step)
    tau = 1.0 + timing + step * np.arange(m)
    xr = _lagrange4(x, tau) * np.exp(1j * _lagrange4(theta, tau))

    var = noise_variance(params.ebn0_db)
    if var > 0.0:
        nz = rng.standard_normal((m, 2)) * math.sqrt(var / 2.0)
        xr = xr + nz[:, 0] + 1j * nz[:, 1]

    rms = math.sqrt(float(np.mean(np.abs(xr) ** 2)))
    gidx = agc_gain_index(rms)
    g = gain_from_index(gidx)
    qi, qq = np.rint(g * xr.real), np.rint(g * xr.imag)
    sat = (qi < -128) | (qi > 127) | (qq < -128) | (qq > 127)
    iq = np.stack([np.clip(qi, -128, 127), np.clip(qq, -128, 127)], axis=1).astype(np.int8)
    flags = sat.astype(np.uint8)
    flags[0] |= 2                                  # gain_reply strobe before sample 0
    gain = np.full(m, gidx, dtype=np.uint8)
    start = int(round((lead - 1 - timing) / step)) if lead else 0
    stop = int(round((lead + len(sig) - 1 - timing) / step))
    return ChannelOutput(iq, flags, gain, int(sat.sum()), float(cfo), float(clock), float(timing),
                         float(phase0), var, gidx, max(start, 0), min(stop, m),
                         xr if keep_float else None)


def pack_rx_records(out):
    """RX stimulus bytes of decision 0007: per sample int8 I, int8 Q, uint8 flags,
    uint8 gain (4 octets, little-endian fields are all single octets)."""
    rec = np.empty((len(out.iq), 4), dtype=np.uint8)
    rec[:, 0] = out.iq[:, 0].view(np.uint8)
    rec[:, 1] = out.iq[:, 1].view(np.uint8)
    rec[:, 2] = out.flags
    rec[:, 3] = out.gain
    return rec.tobytes()


def unpack_rx_records(data):
    rec = np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)
    iq = np.stack([rec[:, 0].view(np.int8), rec[:, 1].view(np.int8)], axis=1)
    return iq, rec[:, 2].copy(), rec[:, 3].copy()
