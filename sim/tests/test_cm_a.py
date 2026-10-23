"""CM-A channel model: calibration, determinism, no silent clamping."""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "channel"), os.path.join(HERE, "..", "model")]
import cm_a  # noqa: E402
import packet  # noqa: E402


def _bits(seed=0, payload=37):
    rng = np.random.default_rng(seed)
    bits, _ = packet.build_frame_bits(bytes(rng.integers(0, 256, payload, dtype=np.uint8).tolist()))
    return bits


def _gen(params, seed=1, payload=37, keep_float=True):
    rng = np.random.Generator(np.random.PCG64(seed))
    return cm_a.generate_packet(_bits(seed, payload), params, rng, keep_float=keep_float)


def test_noise_calibration_matches_requested_ebn0():
    """Measured Eb/N0 of the generated noise is within 0.1 dB of the request."""
    for target in (6.0, 12.0, 16.0):
        p_noise, p_sig = [], []
        for seed in range(200):
            out = _gen(cm_a.CmAParams(ebn0_db=target), seed=seed)
            x = out.float_iq
            lead = out.packet_start - 8
            p_noise.append(np.mean(np.abs(x[:lead]) ** 2))                   # noise only
            mid = slice(out.packet_start + 60, out.packet_stop - 60)
            p_sig.append(np.mean(np.abs(x[mid]) ** 2))                        # signal + noise
        noise = float(np.mean(p_noise))
        sig = float(np.mean(p_sig)) - noise
        measured = 10 * math.log10((sig / cm_a.SYMBOL_RATE) / (noise / cm_a.FS))
        assert abs(measured - target) < 0.1, (target, measured)


def test_signal_has_unit_power_without_noise():
    out = _gen(cm_a.CmAParams(), keep_float=True)
    mid = out.float_iq[out.packet_start + 60: out.packet_stop - 60]
    assert abs(np.mean(np.abs(mid) ** 2) - 1.0) < 0.01


def test_same_seed_same_samples_and_different_seed_differs():
    a, b = _gen(cm_a.CmAParams(ebn0_db=12.0)), _gen(cm_a.CmAParams(ebn0_db=12.0))
    assert cm_a.pack_rx_records(a) == cm_a.pack_rx_records(b)
    c = _gen(cm_a.CmAParams(ebn0_db=12.0), seed=2)
    assert cm_a.pack_rx_records(a) != cm_a.pack_rx_records(c)


def _measured_offset_hz(out):
    z = out.iq[:, 0].astype(float) + 1j * out.iq[:, 1].astype(float)
    z = z[out.packet_start + 40: out.packet_stop - 40]
    return np.angle(np.sum(z[1:] * np.conj(z[:-1]))) * cm_a.FS / (2 * np.pi)


def test_offset_is_applied_unclamped():
    """An injected offset beyond the spec range reaches the samples as asked."""
    for cfo in (-800e3, -150e3, 0.0, 150e3, 300e3, 800e3):
        out = _gen(cm_a.CmAParams(cfo_hz=cfo))
        assert out.cfo_hz == cfo
        assert abs(_measured_offset_hz(out) - cfo) < 25e3, (cfo, _measured_offset_hz(out))


def test_uniform_offset_draw_stays_in_range_and_spreads():
    vals = [_gen(cm_a.CmAParams(draw_cfo=True), seed=s, keep_float=False).cfo_hz for s in range(60)]
    assert max(abs(v) for v in vals) <= 150e3
    assert max(vals) > 100e3 and min(vals) < -100e3


def test_clock_offset_stretches_the_record():
    base = _gen(cm_a.CmAParams(clock_ppm=0.0), keep_float=False)
    fast = _gen(cm_a.CmAParams(clock_ppm=-5000.0), keep_float=False)
    # receiver clock 0.5 % faster samples more often: more output samples
    assert len(fast.iq) > len(base.iq) + 10


def test_drift_profiles():
    n = 4000
    lin = cm_a.drift_track_hz(n, "linear", 50e3)
    assert lin[0] == 0.0 and abs(lin[-1] - 50e3) < 1e-6
    st = cm_a.drift_track_hz(n, "stepped", -50e3)
    assert st[0] == 0.0 and abs(st[-1] + 50e3) < 1e-6
    slope = np.max(np.abs(np.diff(st))) * cm_a.FS               # Hz per second
    assert abs(slope - 20e3 / 50e-6) < 1.0                       # 20 kHz per 50 us
    assert not np.any(cm_a.drift_track_hz(n, "none", 50e3))


def test_clipping_is_counted_not_hidden():
    out = _gen(cm_a.CmAParams(ebn0_db=16.0), keep_float=False)
    assert out.clipped == int(np.sum(out.flags & 1))
    assert out.iq.dtype == np.int8


def test_agc_uses_noisy_record_and_stays_in_index_range():
    out = _gen(cm_a.CmAParams(ebn0_db=0.0), keep_float=False)
    assert 0 <= out.gain_index <= 63 and out.flags[0] & 2
    quiet = _gen(cm_a.CmAParams(ebn0_db=30.0), keep_float=False)
    assert quiet.gain_index != out.gain_index          # gain follows the received power


def test_rx_record_round_trip():
    out = _gen(cm_a.CmAParams(ebn0_db=12.0), keep_float=False)
    iq, flags, gain = cm_a.unpack_rx_records(cm_a.pack_rx_records(out))
    assert np.array_equal(iq, out.iq) and np.array_equal(flags, out.flags) and np.array_equal(gain, out.gain)
    assert len(cm_a.pack_rx_records(out)) == 4 * len(out.iq)
