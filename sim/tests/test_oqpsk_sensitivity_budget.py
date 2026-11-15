"""Sensitivity-budget analysis (issue #137): override proofing, class split,
crossing/slope arithmetic, and the frac_bits=0 reproduction anchor."""

import json
import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(SIM, "analysis"), os.path.join(SIM, "sweep"),
                os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import cm_a_oqpsk  # noqa: E402
import oqpsk_rx  # noqa: E402
import oqpsk_tx  # noqa: E402
import oqpsk_sensitivity_budget as sb  # noqa: E402


def point(snr=5.0, packets=1000, errors=100, sync=60, fcs=20, cap=False, per=None):
    return {"snr_db": snr, "packets": packets, "errors": errors,
            "sync_misses": sync, "fcs_failures": fcs,
            "per": errors / packets if per is None else per,
            "cp_upper": 0.02, "bound_only": cap}


# ------------------------------------------------------------- class split

def test_residual_class_is_real_not_assumed_zero():
    # A packet that syncs, passes FCS and still returns a wrong PSDU counts in
    # errors but in neither named class (issue #137 correction 2).
    p = point(errors=10, sync=4, fcs=3)
    s = sb.split_classes(p)
    assert s["classes"] == {"sync_misses": 4, "fcs_failures": 3, "residual": 3}
    assert s["dominant"] == "sync_misses"


def test_residual_is_reported_even_when_zero_and_dominance_moves():
    s = sb.split_classes(point(errors=100, sync=100, fcs=0))
    assert s["classes"]["residual"] == 0 and s["dominant"] == "sync_misses"
    s = sb.split_classes(point(errors=100, sync=10, fcs=10))
    assert s["dominant"] == "residual"


def test_split_raises_on_negative_residual():
    with pytest.raises(AssertionError):
        sb.split_classes(point(errors=5, sync=4, fcs=3))


# ------------------------------------------------- override proofing (AC 2)

def test_override_context_probes_behaviour_and_restores():
    committed = oqpsk_rx.MIN_AMPLITUDE
    with sb.override_constants({"MIN_AMPLITUDE": 2048}):
        assert oqpsk_rx.MIN_AMPLITUDE == 2048
        # the probe point: accepted only under the halved floor
        c = committed * oqpsk_rx.NTAPS - 1
        assert bool(oqpsk_rx._accept(np.int64(c), np.int64(1)))
    assert oqpsk_rx.MIN_AMPLITUDE == committed
    assert not bool(oqpsk_rx._accept(np.int64(c), np.int64(1)))


def test_override_context_rejects_unknown_and_misspelled_names():
    with pytest.raises(AssertionError, match="not an overridable"):
        with sb.override_constants({"MIN_APMPLITUDE": 2048}):
            pass
    assert oqpsk_rx.MIN_AMPLITUDE == 4096          # untouched


def test_override_context_detects_a_model_that_ignores_globals(monkeypatch):
    # The failure mode the probe exists for: the constants are set but the
    # receiver no longer reads them at call time.
    frozen_a, frozen_n, frozen_d = oqpsk_rx.MIN_AMPLITUDE, oqpsk_rx.ACCEPT_NUM, oqpsk_rx.ACCEPT_DEN_SHIFT
    monkeypatch.setattr(oqpsk_rx, "_accept",
                        lambda corr, mag: sb._accept_from(frozen_a, frozen_n, frozen_d, int(corr), int(mag)))
    with pytest.raises(AssertionError, match="ignores the overridden constants"):
        with sb.override_constants({"MIN_AMPLITUDE": 0}):
            pass


def test_fir_out_bits_override_is_probed_through_channel_filter():
    with sb.override_constants({"FIR_OUT_BITS": oqpsk_rx.FIR_OUT_BITS + 4}):
        assert oqpsk_rx.FIR_OUT_BITS == 13
        assert int(oqpsk_rx.channel_filter(np.array([30000], dtype=np.int64))[0]) == 1875
    assert oqpsk_rx.FIR_OUT_BITS == 9
    assert int(oqpsk_rx.channel_filter(np.array([30000], dtype=np.int64))[0]) == 255


def test_gate_probe_point_separates_every_variant_gate():
    committed = {"MIN_AMPLITUDE": oqpsk_rx.MIN_AMPLITUDE,
                 "ACCEPT_NUM": oqpsk_rx.ACCEPT_NUM,
                 "ACCEPT_DEN_SHIFT": oqpsk_rx.ACCEPT_DEN_SHIFT}
    noops = (dict(committed),
             {**committed, "MIN_AMPLITUDE": 4096})
    for v in noops:
        assert sb._gate_probe_point(committed, v) is None
    changed = ({**committed, "MIN_AMPLITUDE": 2048},
               {**committed, "MIN_AMPLITUDE": 0},
               {**committed, "ACCEPT_NUM": -1, "ACCEPT_DEN_SHIFT": 0},
               {**committed, "ACCEPT_NUM": 1, "ACCEPT_DEN_SHIFT": 1})
    for v in changed:
        c, m = sb._gate_probe_point(committed, v)
        assert sb._accept_from(committed["MIN_AMPLITUDE"], committed["ACCEPT_NUM"],
                               committed["ACCEPT_DEN_SHIFT"], c, m) \
            != sb._accept_from(v["MIN_AMPLITUDE"], v["ACCEPT_NUM"], v["ACCEPT_DEN_SHIFT"], c, m)


# ---------------------------------------- quantization harness anchors (AC 3)

def _one_packet(snr=5.0):
    rng = np.random.Generator(np.random.PCG64(7))
    psdu = oqpsk_tx.with_fcs(bytes(rng.integers(0, 256, 18, dtype=np.uint8).tolist()))
    return psdu, cm_a_oqpsk.generate_packet(psdu, cm_a_oqpsk.OqpskParams(snr_db=snr),
                                            rng, keep_float=True)


def test_frac0_quantization_is_bit_identical_to_committed_int8():
    _, out = _one_packet()
    sb.quantize_float_frac0_matches_int8(out)      # raises on any mismatch
    fields = ("synced", "psdu", "crc_ok", "length", "sync_index", "timing_steps")
    a = oqpsk_rx.demodulate(out.iq, out.flags, out.gain)
    b = sb.demodulate_fine(out, 0)
    assert {k: a[k] for k in fields} == {k: b[k] for k in fields}


def test_fine_quantization_harness_runs_and_keeps_threshold_semantics():
    _, out = _one_packet()
    rx = sb.demodulate_fine(out, sb.FRAC_BITS)
    assert isinstance(rx["synced"], bool)
    # the discriminator is an angle: gate thresholds keep their absolute values
    assert oqpsk_rx.MIN_AMPLITUDE * oqpsk_rx.NTAPS == 126976


# ------------------------------------------- crossing / slope arithmetic (AC 4)

def test_crossing_snr_picks_lowest_point_under_target_and_flags_bounds():
    pts = [point(snr=9.0), point(snr=5.0, errors=1, cap=True), point(snr=7.0, errors=30)]
    for p in pts:
        p["cp_upper"] = {9.0: 0.0009, 5.0: 0.002, 7.0: 0.05}[p["snr_db"]]
    snr, xpt = sb.crossing_snr(pts)
    assert snr == 5.0 and xpt["bound_only"]          # caller must say bound, not measurement
    above = point(snr=9.0)                            # cp_upper 0.02 > 1 % target
    assert sb.crossing_snr([above]) == (None, None)


def test_slope_uses_measured_points_only():
    pts = [point(snr=5.0, per=0.4), point(snr=7.0, per=0.04), point(snr=9.0, per=0.0005, cap=True)]
    slope = sb.measured_slope_db_per_decade(pts)
    assert [e["between_db"] for e in slope] == [[5.0, 7.0]]
    assert slope[0]["db_per_decade"] == pytest.approx(2.0, rel=1e-3)


def test_equivalent_delta_sign_and_magnitude():
    base = point(snr=7.0, per=0.04)
    better = point(snr=7.0, per=0.004)
    entry = {"between_db": [5.0, 7.0], "db_per_decade": 2.0}
    assert sb.equivalent_db_delta(base, better, entry) == pytest.approx(-2.0, rel=1e-3)
    assert sb.equivalent_db_delta(base, base, entry) == 0.0
    assert sb.equivalent_db_delta(base, better, None) is None


# ------------------------------------------------------------- end-to-end

def test_quick_run_produces_a_complete_report(tmp_path):
    out = tmp_path / "budget.json"
    assert sb.main(["--quick", "--out", str(out)]) == 0
    r = json.loads(out.read_text())
    assert r["label"] == "simulated, CM-A" and r["channel_model"] == "CM-A"
    assert r["mode"] == "quick" and r["base_seed"] == 1 and r["run_index"] == 0
    for p in r["points"] + r["quantization"]["points"]:
        assert p["label"] == "simulated, CM-A" and p["variant"] and "seed" in p
        assert p["stopped_by"] == "packet_cap" and p["bound_only"]   # 40-packet caps
        assert p["errors"] <= p["packets"] and p["residual"] >= 0
    assert set(r["variants"]) >= {"baseline", "minamp_2048"}
    assert r["quantization"]["scaling_choice"]
