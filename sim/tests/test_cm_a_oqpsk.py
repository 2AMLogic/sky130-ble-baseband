"""CM-A 802.15.4 source: SNR calibration in 2 MHz, applied offsets, determinism."""

import math
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "channel"), os.path.join(HERE, "..", "model")]
import cm_a_oqpsk as ch  # noqa: E402
import oqpsk_rx  # noqa: E402
import oqpsk_tx  # noqa: E402

PSDU = oqpsk_tx.with_fcs(bytes(range(18)))


def rng(seed=1):
    return np.random.Generator(np.random.PCG64(seed))


def test_source_is_unit_amplitude_and_matches_tx_words():
    sig = ch.oqpsk_baseband(PSDU)
    assert len(sig) == len(oqpsk_tx.tx_dev_words(PSDU))
    assert np.allclose(np.abs(sig), 1.0)
    # phase advances 1/16 turn per sample at |tx_dev| = 64, like oqpsk_tx.modulate
    step = np.angle(sig[1:] / sig[:-1]) / (2 * np.pi)
    assert set(np.round(np.abs(step) * 16, 6)) <= {0.0, 1.0}


def test_noise_variance_is_defined_in_2mhz():
    assert ch.noise_variance(math.inf) == 0.0
    # 0 dB: noise power in 2 MHz equals signal power, so full-band variance is fs / 2 MHz
    assert ch.noise_variance(0.0) == pytest.approx(4.0)
    assert ch.noise_variance(10.0) == pytest.approx(0.4)


def test_snr_calibration_measured_in_2mhz():
    """Measure the noise-only part of the record: power in the central 2 MHz of
    the spectrum over the signal power must equal the requested SNR."""
    snr = 5.0
    p = ch.OqpskParams(snr_db=snr, lead_samples=1 << 16, tail_samples=0)
    out = ch.generate_packet(PSDU, p, rng(), keep_float=True)
    noise = out.float_iq[: (1 << 16) - 2000]
    spec = np.fft.fftshift(np.fft.fft(noise)) / math.sqrt(len(noise))
    freqs = np.fft.fftshift(np.fft.fftfreq(len(noise), 1.0 / ch.FS))
    in_band = np.abs(freqs) <= ch.NOISE_BANDWIDTH_HZ / 2
    # per-bin power sums to the time-domain power; in-band share of white noise = 2/8
    band_power = np.sum(np.abs(spec[in_band]) ** 2) / len(noise)
    assert 10 * math.log10(1.0 / band_power) == pytest.approx(snr, abs=0.3)


def test_cfo_is_applied():
    p = ch.OqpskParams(cfo_hz=100e3, lead_samples=0, tail_samples=64)
    out = ch.generate_packet(PSDU, p, rng(), keep_float=True)
    ref = ch.generate_packet(PSDU, ch.OqpskParams(lead_samples=0, tail_samples=64), rng(),
                             keep_float=True)
    n = min(len(out.float_iq), len(ref.float_iq)) - 8
    prod = out.float_iq[1:n] * np.conj(out.float_iq[:n - 1]) * np.conj(
        ref.float_iq[1:n] * np.conj(ref.float_iq[:n - 1]))
    f = np.angle(np.mean(prod)) / (2 * np.pi) * ch.FS
    assert f == pytest.approx(100e3, rel=0.02)
    assert out.cfo_hz == 100e3


def test_clock_offset_changes_record_length():
    base = ch.generate_packet(PSDU, ch.OqpskParams(), rng())
    fast = ch.generate_packet(PSDU, ch.OqpskParams(clock_ppm=-80000.0), rng())
    slow = ch.generate_packet(PSDU, ch.OqpskParams(clock_ppm=80000.0), rng())
    assert len(fast.iq) > len(base.iq) > len(slow.iq)


def test_timing_phase_is_within_one_chip_and_drawn_offsets_in_range():
    p = ch.OqpskParams(draw_cfo=True, draw_clock=True)
    for seed in range(20):
        out = ch.generate_packet(PSDU, p, rng(seed))
        assert 0.0 <= out.timing_phase < ch.SPS_CHIP
        assert abs(out.cfo_hz) <= ch.CFO_SPEC_HZ
        assert abs(out.clock_ppm) <= ch.CLOCK_SPEC_PPM


def test_out_of_range_offset_is_not_clamped():
    out = ch.generate_packet(PSDU, ch.OqpskParams(cfo_hz=800e3), rng())
    assert out.cfo_hz == 800e3


def test_deterministic_for_a_seed():
    p = ch.OqpskParams(snr_db=5.0, draw_cfo=True, draw_clock=True)
    a, b = ch.generate_packet(PSDU, p, rng(7)), ch.generate_packet(PSDU, p, rng(7))
    assert np.array_equal(a.iq, b.iq) and a.cfo_hz == b.cfo_hz
    c = ch.generate_packet(PSDU, p, rng(8))
    assert not np.array_equal(a.iq[:100], c.iq[:100])


def test_quantized_and_clipping_counted():
    out = ch.generate_packet(PSDU, ch.OqpskParams(snr_db=5.0), rng())
    assert out.iq.dtype == np.int8 and out.iq.shape[1] == 2
    assert out.clipped >= 0 and out.flags[0] & 2


def test_noiseless_channel_is_receivable():
    out = ch.generate_packet(PSDU, ch.OqpskParams(), rng())
    r = oqpsk_rx.demodulate(out.iq, out.flags, out.gain)
    assert r["synced"] and r["crc_ok"] and r["psdu"] == PSDU
