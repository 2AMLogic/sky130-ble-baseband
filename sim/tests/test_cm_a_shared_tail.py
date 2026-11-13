"""Both CM-A generators share one copy of stages 4, 6 and 7.

Decision 0002 declares a single channel model, and every BER (#55) and PER
(#56) row is labelled "simulated, CM-A" on that basis. The per-modem tests in
``test_cm_a.py`` and ``test_cm_a_oqpsk.py`` check each generator on its own, so
they would all still pass if one modem's resampling, AGC or clipping were
re-inlined and then fixed in only one place. These tests fail on that instead:
the shared tail must stay a call to ``cm_a.receive_chain``, and it must keep
taking exactly one draw from the generator, so no sweep seed moves.
"""

import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "channel"), os.path.join(HERE, "..", "model")]
import cm_a  # noqa: E402
import cm_a_oqpsk  # noqa: E402
import oqpsk_tx  # noqa: E402

BITS = np.random.default_rng(7).integers(0, 2, 296)
PSDU = oqpsk_tx.with_fcs(bytes(range(18)))


def _rng(seed=1):
    return np.random.Generator(np.random.PCG64(seed))


class _CountingRng:
    """Forwards to a real Generator, recording the draws taken."""

    def __init__(self, inner):
        self._inner = inner
        self.draws = []

    def uniform(self, *args, **kwargs):
        self.draws.append("uniform")
        return self._inner.uniform(*args, **kwargs)

    def standard_normal(self, *args, **kwargs):
        self.draws.append("standard_normal")
        return self._inner.standard_normal(*args, **kwargs)


def _both_generators():
    return [
        ("le1m", lambda rng, **kw: cm_a.generate_packet(
            BITS, cm_a.CmAParams(ebn0_db=8.0), rng, **kw)),
        ("oqpsk", lambda rng, **kw: cm_a_oqpsk.generate_packet(
            PSDU, cm_a_oqpsk.OqpskParams(snr_db=6.0), rng, **kw)),
    ]


def test_both_generators_route_the_tail_through_receive_chain(monkeypatch):
    """Neither modem may carry its own copy of stages 4, 6 and 7."""
    for name, gen in _both_generators():
        seen = []
        real = cm_a.receive_chain

        def spy(*args, **kwargs):
            seen.append((args, kwargs))
            return real(*args, **kwargs)

        monkeypatch.setattr(cm_a, "receive_chain", spy)
        out = gen(_rng())
        monkeypatch.undo()
        assert len(seen) == 1, f"{name} did not call cm_a.receive_chain exactly once"
        assert len(out.iq) > 0 and out.flags[0] & 2, f"{name} produced no usable record"


def test_the_shared_tail_is_byte_identical_for_both_callers():
    """The helper, called directly with a caller's own inputs, reproduces that
    caller's output exactly -- so the call really is the whole tail."""
    for name, gen in _both_generators():
        out = gen(_rng(), keep_float=True)
        assert out.float_iq is not None, f"{name} dropped float_iq"
        # re-run the helper alone on the same drawn parameters
        if name == "le1m":
            params = cm_a.CmAParams(ebn0_db=8.0)
            sig = cm_a.gfsk_baseband(BITS)
            lead = params.lead_symbols * cm_a.SPS
            total = lead + len(sig) + params.tail_symbols * cm_a.SPS
            x = np.zeros(total, dtype=complex)
            x[lead:lead + len(sig)] = sig
            drift = cm_a.drift_track_hz(len(sig), params.drift_profile, params.drift_hz)
            freq = np.full(total, float(out.cfo_hz))
            freq[lead:lead + len(sig)] += drift
            freq[lead + len(sig):] += drift[-1]
            theta = out.carrier_phase + 2.0 * np.pi * np.cumsum(freq) / cm_a.FS
            var = cm_a.noise_variance(params.ebn0_db)
        else:
            params = cm_a_oqpsk.OqpskParams(snr_db=6.0)
            sig = cm_a_oqpsk.oqpsk_baseband(PSDU)
            lead = params.lead_samples
            total = lead + len(sig) + params.tail_samples
            x = np.zeros(total, dtype=complex)
            x[lead:lead + len(sig)] = sig
            theta = (out.carrier_phase
                     + 2.0 * np.pi * out.cfo_hz * np.arange(total) / cm_a_oqpsk.FS)
            var = cm_a_oqpsk.noise_variance(params.snr_db)

        # With the default draw_* flags the callers take exactly two uniforms
        # before the tail (timing, then initial phase); mirror them so the
        # generator state the helper sees is the one it saw in the real run.
        rng = _rng()
        sps = cm_a.SPS if name == "le1m" else cm_a_oqpsk.SPS_CHIP
        assert rng.uniform(0.0, sps) == out.timing_phase, f"{name} timing draw moved"
        assert rng.uniform(0.0, 2.0 * np.pi) == out.carrier_phase, f"{name} phase draw moved"
        again = cm_a.receive_chain(x, theta, lead, len(sig), out.clock_ppm,
                                   out.timing_phase, var, rng, out.cfo_hz,
                                   out.carrier_phase, keep_float=True)
        assert np.array_equal(again.iq, out.iq), f"{name} iq differs from the shared tail"
        assert np.array_equal(again.flags, out.flags), f"{name} flags differ"
        assert np.array_equal(again.gain, out.gain), f"{name} gain differs"
        assert (again.clipped, again.gain_index) == (out.clipped, out.gain_index)
        assert (again.packet_start, again.packet_stop) == (out.packet_start, out.packet_stop)


def test_shared_tail_takes_exactly_one_draw_and_none_without_noise():
    """The draw order is the sweep seeds' contract: one ``standard_normal`` when
    there is noise, nothing at all when there is not."""
    for name, gen in _both_generators():
        counting = _CountingRng(_rng())
        gen(counting)
        assert counting.draws.count("standard_normal") == 1, (
            f"{name} took {counting.draws.count('standard_normal')} noise draws, want 1")
        assert counting.draws == ["uniform", "uniform", "standard_normal"], (
            f"{name} draw order changed: {counting.draws}")

    noiseless = [
        ("le1m", lambda rng: cm_a.generate_packet(BITS, cm_a.CmAParams(), rng)),
        ("oqpsk", lambda rng: cm_a_oqpsk.generate_packet(
            PSDU, cm_a_oqpsk.OqpskParams(), rng)),
    ]
    for name, gen in noiseless:
        counting = _CountingRng(_rng())
        out = gen(counting)
        assert out.noise_var == 0.0
        assert "standard_normal" not in counting.draws, (
            f"{name} drew noise at an infinite Eb/N0 or SNR")


def test_receive_chain_reports_the_packet_window_and_clips_at_int8():
    """The window the receivers slice, and the saturation count, come from the
    helper -- a loud record must clip and be counted, not silently wrap."""
    params = cm_a.CmAParams(ebn0_db=math.inf)
    out = cm_a.generate_packet(BITS, params, _rng())
    assert 0 <= out.packet_start < out.packet_stop <= len(out.iq)
    assert out.iq.dtype == np.int8
    assert out.iq.min() >= -128 and out.iq.max() <= 127

    # The AGC attenuates a loud record rather than clipping it, but it runs out
    # of range at index 0 (gain 1/256, so anything past ~32512 LSB saturates).
    # Past that floor every saturated sample must be counted, not wrapped.
    floor_gain = cm_a.gain_from_index(0)
    amplitude = 4.0 * 127.0 / floor_gain
    loud = cm_a.receive_chain(np.full(4096, amplitude + 0j), np.zeros(4096), 512, 2048,
                              0.0, 0.0, 0.0, _rng(), 0.0, 0.0)
    assert loud.gain_index == 0, "a record past the AGC floor did not pin the gain index"
    assert loud.clipped == len(loud.iq), "a record past the AGC floor did not clip"
    assert int((loud.flags & 1).sum()) == loud.clipped
    assert loud.iq.max() == 127, "clipping wrapped instead of saturating"
