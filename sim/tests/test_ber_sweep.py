"""BER sweep harness: statistics, seeds, stop rule, JSON contract."""

import json
import math
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "..", "sweep", "ber_sweep.py")
sys.path[:0] = [os.path.join(HERE, "..", "sweep")]
import ber_sweep  # noqa: E402
import cm_a  # noqa: E402


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
    got_lo, got_hi = ber_sweep.clopper_pearson(k, n)
    assert got_lo == pytest.approx(lo, rel=1e-6, abs=1e-12)
    assert got_hi == pytest.approx(hi, rel=1e-6, abs=1e-12)


def test_clopper_pearson_zero_errors_closed_form():
    n = 5000
    assert ber_sweep.clopper_pearson(0, n)[1] == pytest.approx(1 - 0.025 ** (1.0 / n), rel=1e-9)


def test_clopper_pearson_rejects_bad_input():
    for k, n in ((-1, 10), (11, 10), (0, 0)):
        with pytest.raises(ValueError):
            ber_sweep.clopper_pearson(k, n)


def test_point_seed_is_stable_and_sensitive():
    base = ber_sweep.point_seed("r", {"a": 1}, 3, 0, 1)
    assert base == ber_sweep.point_seed("r", {"a": 1}, 3, 0, 1)
    assert base == int.from_bytes(__import__("hashlib").sha256(
        b'["r",{"a":1},3,0,1]').digest()[:8], "big")      # pinned: not Python's hash()
    for other in (("s", {"a": 1}, 3, 0, 1), ("r", {"a": 2}, 3, 0, 1),
                  ("r", {"a": 1}, 4, 0, 1), ("r", {"a": 1}, 3, 1, 1), ("r", {"a": 1}, 3, 0, 2)):
        assert base != ber_sweep.point_seed(*other)


def test_capped_point_is_an_upper_bound_and_measured_point_is_not():
    capped = ber_sweep.run_point("t", 0, cm_a.CmAParams(), 37, 3, 100, 1)
    assert capped["errors"] == 0 and capped["stopped_by"] == "packet_cap" and capped["bound_only"]
    assert capped["packets"] == 3 and capped["label"] == "simulated, CM-A"
    assert capped["cp_upper"] > 0.0 and capped["cp_lower"] == 0.0
    noisy = ber_sweep.run_point("t", 1, cm_a.CmAParams(ebn0_db=6.0, cfo_hz=0.0), 37, 200, 100, 1)
    assert noisy["errors"] >= 100 and noisy["stopped_by"] == "errors" and not noisy["bound_only"]
    assert noisy["cp_lower"] <= noisy["ber"] <= noisy["cp_upper"]


def _run(tmp_path, name, *extra):
    out = tmp_path / name / "ber.json"
    t0 = time.time()
    subprocess.run([sys.executable, SWEEP, "--quick", "--out", str(out), *extra],
                   check=True, capture_output=True, text=True)
    return out, time.time() - t0


def test_quick_run_contract_and_byte_identical_reruns(tmp_path):
    a, elapsed = _run(tmp_path, "a")
    b, _ = _run(tmp_path, "b")
    assert elapsed < 300
    assert a.read_bytes() == b.read_bytes()
    c, _ = _run(tmp_path, "c", "--seed", "2")
    assert a.read_bytes() != c.read_bytes()

    rep = json.loads(a.read_text())
    assert rep["label"] == "simulated, CM-A" and rep["prng"]["family"] == "PCG64"
    assert rep["prng"]["numpy_version"] and rep["sim_git_sha"]
    text = a.read_text()
    assert "timestamp" not in text and "hostname" not in text
    need = {"seed", "errors", "bits", "cp_lower", "cp_upper", "clipped_samples", "label",
            "stopped_by", "bound_only", "ebn0_db", "impairments", "row_id"}
    assert rep["points"]
    for p in rep["points"]:
        assert need <= set(p) and p["label"] == "simulated, CM-A"
        assert p["cp_lower"] <= p["ber"] <= p["cp_upper"] + 1e-12
        assert p["bound_only"] == (p["errors"] < rep["stop_rule"]["min_errors"])
    assert len({p["seed"] for p in rep["points"]}) == len(rep["points"])


def test_quick_negative_control_is_flagged_and_visibly_worse(tmp_path):
    out, _ = _run(tmp_path, "n")
    rep = json.loads(out.read_text())
    ctrl = [p for p in rep["points"] if p["negative_control"]]
    assert len(ctrl) == 1 and ctrl[0]["out_of_spec"]
    assert abs(ctrl[0]["impairments"]["cfo_hz"]) > 250e3
    in_spec = [p for p in rep["points"] if not p["out_of_spec"] and p["ebn0_db"] == 16.0]
    assert ctrl[0]["ber"] > 10 * max(p["ber"] for p in in_spec)
    assert "negative_control" not in rep["rows"] and all(not p["out_of_spec"] for p in in_spec)


def test_grids_cover_both_extremes_and_zero():
    offs = {p[1].cfo_hz for p in ber_sweep.full_grid() if p[0] == "le1m_cfo"}
    assert {-150e3, 0.0, 150e3} <= offs
    clocks = {p[1].clock_ppm for p in ber_sweep.full_grid() if p[0] == "le1m_clock"}
    assert {-100.0, 0.0, 100.0} <= clocks
    assert all(p[2] == ber_sweep.PAYLOAD_MAX for p in ber_sweep.full_grid() if p[0] == "le1m_clock")
    assert {p[1].ebn0_db for p in ber_sweep.full_grid()} >= {16.0}


def test_row_summary_reports_not_asserts():
    pts = [{"row_id": "r", "ebn0_db": 16.0, "cp_upper": 5e-4, "bound_only": True,
            "negative_control": False, "out_of_spec": False},
           {"row_id": "r", "ebn0_db": 16.0, "cp_upper": 2e-3, "bound_only": False,
            "negative_control": False, "out_of_spec": False},
           {"row_id": "r", "ebn0_db": 12.0, "cp_upper": 9e-1, "bound_only": False,
            "negative_control": False, "out_of_spec": False}]
    r = ber_sweep.row_summary(pts)["r"]
    assert r["points"] == 2 and r["worst_cp_upper"] == 2e-3
    assert r["upper_bound_meets_target"] is False and r["all_points_measured"] is False
