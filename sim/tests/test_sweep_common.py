"""Scaffolding shared by the two sweep drivers: statistics, seeds, and the
guarantee that neither driver keeps its own copy.

The statistics and seed tests here moved with their code out of
test_ber_sweep.py. The rest are the dedupe's own guard: the per-driver tests
exercise each sweep alone and would all still pass if a driver quietly
re-inlined the shared scaffolding, which is exactly how the two copies drifted
apart before.
"""

import argparse
import ast
import hashlib
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP_DIR = os.path.join(HERE, "..", "sweep")
sys.path[:0] = [SWEEP_DIR]
import ber_sweep  # noqa: E402
import cm_a  # noqa: E402
import cm_a_oqpsk  # noqa: E402
import per_sweep  # noqa: E402
import sweep_common  # noqa: E402

DRIVERS = (ber_sweep, per_sweep)

# The 18 point-record keys that are the same in both sweeps (issue #116). The
# two parameterized ones (ebn0_db/snr_db, ber/per) are deliberately not here.
SHARED_POINT_KEYS = {
    "row_id", "point_index", "run_index", "seed", "label", "channel_model", "impairments",
    "out_of_spec", "negative_control", "packets", "errors", "cp_lower", "cp_upper",
    "stopped_by", "bound_only", "sync_misses", "clipped_samples", "samples",
}

# Everything moved out of ber_sweep. A driver that defines any of these again
# has re-inlined the copy this module exists to remove.
MOVED_NAMES = {
    "_log_binom_cdf", "_solve", "clopper_pearson", "point_seed", "_round", "git_sha",
    "write_report", "default_out", "shard_out", "MergeError", "merge_shards",
}


# ---------------------------------------------------------------- statistics

@pytest.mark.parametrize("k,n,lo,hi", [
    (0, 10, 0.0, 0.3084971078187608),
    (10, 10, 0.6915028921812392, 1.0),
    (0, 3000, 0.0, 0.0012288708038255115),
    (100, 1000, 0.08210533435558, 0.12028793651869264),
    (100, 100000, 0.0008137116819701752, 0.001216136395647647),
    (1, 33600, 7.535059061229095e-07, 0.00016581143942111533),
    (5, 50, 0.03327509358902247, 0.21813536643420225),
])
def test_clopper_pearson_known_values(k, n, lo, hi):
    """Reference values from the beta-quantile form of the exact interval."""
    got_lo, got_hi = sweep_common.clopper_pearson(k, n)
    assert got_lo == pytest.approx(lo, rel=1e-6, abs=1e-12)
    assert got_hi == pytest.approx(hi, rel=1e-6, abs=1e-12)


def test_clopper_pearson_zero_errors_closed_form():
    n = 5000
    assert sweep_common.clopper_pearson(0, n)[1] == pytest.approx(1 - 0.025 ** (1.0 / n), rel=1e-9)


def test_clopper_pearson_rejects_bad_input():
    for k, n in ((-1, 10), (11, 10), (0, 0)):
        with pytest.raises(ValueError):
            sweep_common.clopper_pearson(k, n)


def test_point_seed_is_stable_and_sensitive():
    base = sweep_common.point_seed("r", {"a": 1}, 3, 0, 1)
    assert base == sweep_common.point_seed("r", {"a": 1}, 3, 0, 1)
    assert base == int.from_bytes(hashlib.sha256(
        b'["r",{"a":1},3,0,1]').digest()[:8], "big")      # pinned: not Python's hash()
    for other in (("s", {"a": 1}, 3, 0, 1), ("r", {"a": 2}, 3, 0, 1),
                  ("r", {"a": 1}, 4, 0, 1), ("r", {"a": 1}, 3, 1, 1), ("r", {"a": 1}, 3, 0, 2)):
        assert base != sweep_common.point_seed(*other)


def test_both_sweeps_derive_their_seeds_from_the_one_implementation():
    """Both drivers must hash the same tuple; a second copy could drift silently."""
    for mod in DRIVERS:
        assert mod.sweep_common.point_seed is sweep_common.point_seed


# ----------------------------------------------- the two documented divergences

def test_row_verdict_inclusivity_differs_between_the_two_sweeps():
    """BER's documented rule is <= 1e-3, PER's is < 1 % (sim/README.md). At the
    target exactly, the BER row passes and the PER row does not -- if a shared
    helper ever unified them, one of these flips."""
    ber_pt = {"row_id": "r", "ebn0_db": ber_sweep.TARGET_EBN0_DB, "cp_upper": ber_sweep.TARGET_BER,
              "bound_only": False, "negative_control": False, "out_of_spec": False}
    per_pt = {"row_id": "r", "snr_db": per_sweep.TARGET_SNR_DB, "cp_upper": per_sweep.TARGET_PER,
              "bound_only": False, "negative_control": False, "out_of_spec": False}
    assert ber_sweep.row_summary([ber_pt])["r"]["upper_bound_meets_target"] is True
    assert per_sweep.row_summary([per_pt])["r"]["upper_bound_meets_target"] is False
    # and just inside/outside each target, so the above is not passing by accident
    nudge = 1e-12
    assert ber_sweep.row_summary([dict(ber_pt, cp_upper=ber_sweep.TARGET_BER + nudge)]
                                 )["r"]["upper_bound_meets_target"] is False
    assert per_sweep.row_summary([dict(per_pt, cp_upper=per_sweep.TARGET_PER - nudge)]
                                 )["r"]["upper_bound_meets_target"] is True


def test_only_the_per_sweep_reports_a_top_level_negative_control():
    """ber.json carries the control as a flagged point only; giving it the PER
    sweep's report field would be a report-format change (issue #116, #55)."""
    assert hasattr(per_sweep, "control_summary") and not hasattr(ber_sweep, "control_summary")
    args = _args()
    assert "negative_control" in per_sweep.build_report([], args, "0" * 12)
    assert "negative_control" not in ber_sweep.build_report([], args, "0" * 12)


def test_flag_out_of_spec_makes_each_sweep_state_both_limits():
    """Keyword-only and un-defaulted: a new sweep cannot inherit LE 1M's CFO
    threshold or 802.15.4's clock threshold by omission."""
    params = cm_a.CmAParams(cfo_hz=0.0)
    with pytest.raises(TypeError):
        sweep_common.flag_out_of_spec(params, None)
    with pytest.raises(TypeError):
        sweep_common.flag_out_of_spec(params, None, cfo_limit_hz=1.0)
    with pytest.raises(TypeError):
        sweep_common.flag_out_of_spec(params, None, clock_limit_ppm=1.0)


def test_each_sweep_keeps_its_own_out_of_spec_limits():
    # LE 1M: a fixed offset past 250 kHz is flagged; +-100 ppm is the declared
    # clock extreme of the sweep, not an out-of-spec row.
    assert ber_sweep._flag_out_of_spec(cm_a.CmAParams(cfo_hz=300e3), None)["out_of_spec"]
    assert ber_sweep._flag_out_of_spec(cm_a.CmAParams(cfo_hz=-300e3), None)["out_of_spec"]
    assert ber_sweep._flag_out_of_spec(cm_a.CmAParams(cfo_hz=150e3), None) == {}
    assert ber_sweep._flag_out_of_spec(cm_a.CmAParams(clock_ppm=100.0), None) == {}
    # 802.15.4: both the offset and the chip clock have a limit, and the pinned
    # grid ends stay in spec.
    assert per_sweep._flag_out_of_spec(_oq(cfo_hz=cm_a_oqpsk.CFO_SPEC_HZ), None) == {}
    assert per_sweep._flag_out_of_spec(_oq(cfo_hz=-cm_a_oqpsk.CFO_SPEC_HZ), None) == {}
    assert per_sweep._flag_out_of_spec(_oq(cfo_hz=800e3), None)["out_of_spec"]
    assert per_sweep._flag_out_of_spec(_oq(clock_ppm=cm_a_oqpsk.CLOCK_SPEC_PPM), None) == {}
    assert per_sweep._flag_out_of_spec(_oq(clock_ppm=100.0), None)["out_of_spec"]
    # a drawn impairment is never flagged: the draw stays in its own range
    assert ber_sweep._flag_out_of_spec(cm_a.CmAParams(draw_cfo=True, draw_clock=True), None) == {}


# ----------------------------------------------------- no second copy anywhere

def _defined_names(mod):
    tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


@pytest.mark.parametrize("mod", DRIVERS, ids=lambda m: os.path.basename(m.__file__))
def test_driver_does_not_redefine_the_shared_scaffolding(mod):
    assert not (_defined_names(mod) & MOVED_NAMES)


def test_per_sweep_does_not_hang_off_ber_sweep():
    """The 802.15.4 driver must not reach through the LE 1M one for statistics,
    seeds, report writing or channel constants (issue #116)."""
    src = open(per_sweep.__file__, encoding="utf-8").read()
    assert "ber_sweep" not in src
    assert per_sweep.cm_a is cm_a          # imported directly, not reached through


def test_both_drivers_return_the_shared_point_record(monkeypatch):
    """Not just "calls it": the record a driver returns IS the shared envelope."""
    sentinel = {"sentinel": True}
    seen = []

    def spy(**kw):
        seen.append(kw)
        return sentinel

    monkeypatch.setattr(sweep_common, "point_record", spy)
    assert ber_sweep.run_point("t", 0, cm_a.CmAParams(), 37, 1, 100, 1) is sentinel
    assert per_sweep.run_point("t", 0, _oq(snr_db=9.0), 20, 1, 100, 1) is sentinel
    assert [kw["x_key"] for kw in seen] == ["ebn0_db", "snr_db"]
    assert [kw["rate_key"] for kw in seen] == ["ber", "per"]


def test_both_drivers_report_rows_through_the_shared_summary(monkeypatch):
    seen = []
    monkeypatch.setattr(sweep_common, "row_summary",
                        lambda points, **kw: seen.append(kw) or {})
    args = _args()
    ber_sweep.build_report([], args, "0" * 12)
    per_sweep.build_report([], args, "0" * 12)
    assert [kw["x_key"] for kw in seen] == ["ebn0_db", "snr_db"]
    assert [kw["inclusive"] for kw in seen] == [True, False]
    assert [kw["target"] for kw in seen] == [ber_sweep.TARGET_BER, per_sweep.TARGET_PER]


def test_the_report_preamble_is_one_copy():
    """The 8 preamble keys must be byte-identical across the two reports for the
    same arguments -- that identity is what made two copies invisible."""
    args, sha = _args(), "0123456789ab"
    ber, per = ber_sweep.build_report([], args, sha), per_sweep.build_report([], args, sha)
    preamble = sweep_common.report_preamble(args, sha)
    assert set(preamble) == {"format", "label", "channel_model", "mode", "sim_git_sha",
                             "prng", "base_seed", "stop_rule"}
    for key, value in preamble.items():
        assert ber[key] == per[key] == value, key


def test_the_shared_point_keys_are_the_same_eighteen_in_both_sweeps():
    ber = ber_sweep.run_point("t", 0, cm_a.CmAParams(), 37, 1, 100, 1)
    per = per_sweep.run_point("t", 0, _oq(snr_db=9.0), 20, 1, 100, 1)
    assert set(ber) & set(per) == SHARED_POINT_KEYS
    assert set(ber) - set(per) == {"ebn0_db", "ber", "bits", "crc_failures", "timing_steps"}
    assert set(per) - set(ber) == {"snr_db", "per", "fcs_failures"}
    for key in SHARED_POINT_KEYS - {"impairments", "cp_lower", "cp_upper", "errors", "samples"}:
        assert type(ber[key]) is type(per[key]), key


def test_capped_and_measured_marking_is_the_shared_rule():
    """One stop rule for both sweeps: bound_only iff errors < min_errors."""
    capped = ber_sweep.run_point("t", 0, cm_a.CmAParams(), 37, 2, 100, 1)
    assert capped["bound_only"] and capped["stopped_by"] == "packet_cap"
    measured = per_sweep.run_point("t", 0, _oq(snr_db=-5.0), 20, 1000, 3, 1)
    assert not measured["bound_only"] and measured["stopped_by"] == "errors"
    assert measured["errors"] == 3


def test_run_grid_keeps_the_grid_index_as_the_point_index():
    """A --only run must not renumber the points it skipped: the index is part
    of every seed."""
    grid = per_sweep.quick_grid()
    args = _args(only=["per_clock"], packet_cap=1, max_length_packet_cap=1)
    points = sweep_common.run_grid(grid, args, run_point=per_sweep.run_point,
                                   max_length_payload=per_sweep.PSDU_MAX,
                                   flag_point=per_sweep._flag_out_of_spec,
                                   progress=lambda *a: None)
    want = [i for i, g in enumerate(grid) if g[0] == "per_clock"]
    assert [p["point_index"] for p in points] == want and len(want) == 2
    assert all(p["packets"] == 1 for p in points)      # the max-length cap, not --packet-cap


def test_cap_defaults_and_the_two_quick_max_length_caps():
    for mod, quick_max in ((ber_sweep, 6), (per_sweep, 10)):
        quick = _args(quick=True, packet_cap=None, max_length_packet_cap=None)
        sweep_common.apply_cap_defaults(quick, quick_max_length_cap=mod.QUICK_MAX_LENGTH_PACKET_CAP)
        assert (quick.packet_cap, quick.max_length_packet_cap) == (40, quick_max)
        full = _args(quick=False, packet_cap=None, max_length_packet_cap=None)
        sweep_common.apply_cap_defaults(full, quick_max_length_cap=mod.QUICK_MAX_LENGTH_PACKET_CAP)
        assert (full.packet_cap, full.max_length_packet_cap) == (20000, 3000)


def test_unknown_only_row_is_a_usage_error_in_both_sweeps(capsys):
    for mod in DRIVERS:
        with pytest.raises(SystemExit) as e:
            mod.main(["--quick", "--only", "nope"])
        assert e.value.code == 2
        assert "unknown row id(s): nope" in capsys.readouterr().err


def test_row_summary_excludes_control_and_out_of_spec_and_off_target_points():
    on = {"row_id": "r", "ebn0_db": 16.0, "cp_upper": 5e-4, "bound_only": True,
          "negative_control": False, "out_of_spec": False}
    rows = sweep_common.row_summary(
        [on, dict(on, negative_control=True), dict(on, out_of_spec=True),
         dict(on, ebn0_db=12.0, cp_upper=0.9)],
        x_key="ebn0_db", x_target=16.0, target_field="target_ber", target=1e-3, inclusive=True)
    assert list(rows) == ["r"] and rows["r"]["points"] == 1
    assert rows["r"]["worst_cp_upper"] == 5e-4 and rows["r"]["all_points_measured"] is False
    assert rows["r"]["note"] == sweep_common.NOTE
    assert sweep_common.row_summary([], x_key="ebn0_db", x_target=16.0,
                                    target_field="target_ber", target=1e-3, inclusive=True) == {}


def test_log_binom_cdf_matches_a_direct_sum():
    n, p = 40, 0.3
    for k in (0, 1, 7, 39):
        direct = sum(math.comb(n, i) * p ** i * (1 - p) ** (n - i) for i in range(k + 1))
        assert sweep_common._log_binom_cdf(k, n, p) == pytest.approx(math.log(direct), rel=1e-12)
    assert sweep_common._log_binom_cdf(n, n, p) == 0.0


# ------------------------------------------------------------------- helpers

def _oq(**kw):
    return cm_a_oqpsk.OqpskParams(**kw)


def _args(**kw):
    base = dict(quick=True, seed=1, run_index=0, min_errors=100, packet_cap=40,
                max_length_packet_cap=10, only=[], out=None)
    base.update(kw)
    return argparse.Namespace(**base)
