"""PER sweep harness: stop rule, bound_only marking, determinism, negative control."""

import json
import os
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "..", "sweep", "per_sweep.py")
sys.path[:0] = [os.path.join(HERE, "..", "sweep")]
import cm_a_oqpsk  # noqa: E402
import per_sweep  # noqa: E402


def point(snr=9.0, cap=6, min_errors=100, cfo=0.0, psdu=20, flags=None):
    return per_sweep.run_point("t", 0, cm_a_oqpsk.OqpskParams(snr_db=snr, cfo_hz=cfo), psdu, cap,
                               min_errors, 1, flags=flags)


def test_clean_point_hits_cap_and_is_bound_only():
    p = point(cap=5)
    assert p["errors"] == 0 and p["packets"] == 5
    assert p["bound_only"] and p["stopped_by"] == "packet_cap"
    assert p["cp_lower"] == 0.0 and p["cp_upper"] > per_sweep.TARGET_PER   # 5 packets prove nothing
    assert p["label"] == "simulated, CM-A" and p["channel_model"] == "CM-A"


def test_stops_at_min_errors_and_is_measured():
    p = point(snr=-5.0, cap=1000, min_errors=3)        # hopeless SNR: every packet fails
    assert p["errors"] == 3 and p["packets"] == 3
    assert not p["bound_only"] and p["stopped_by"] == "errors"
    assert p["cp_lower"] < p["per"] <= p["cp_upper"]


def test_deterministic_and_seed_sensitive():
    a, b = point(cap=3), point(cap=3)
    assert a == b
    c = per_sweep.run_point("t", 1, cm_a_oqpsk.OqpskParams(snr_db=9.0), 20, 3, 100, 1)
    assert c["seed"] != a["seed"]


def test_127_octet_psdu_runs():
    p = point(psdu=127, cap=2)
    assert p["packets"] == 2 and p["impairments"]["psdu_octets"] == 127


def test_grids_include_both_cfo_extremes_and_clock_ends():
    for grid in (per_sweep.full_grid(), per_sweep.quick_grid()):
        cfos = {p.cfo_hz for r, p, _, _ in grid if r == "per_cfo"}
        assert {-196e3, 196e3} <= cfos
        clocks = {p.clock_ppm for r, p, _, _ in grid if r == "per_clock"}
        assert {-80.0, 80.0} <= clocks
        assert all(n == 127 for r, _, n, _ in grid if r == "per_clock")
        assert all(n == 20 for r, _, n, _ in grid if r in ("per_snr", "per_cfo"))
        assert grid[-1][0] == "negative_control"


def test_negative_control_fails_the_row_for_the_right_reason():
    row_id, params, psdu, flags = per_sweep._negative_control()
    ctl = per_sweep.run_point(row_id, 0, params, psdu, 20, 100, 1, flags=per_sweep._flag_out_of_spec(params, flags))
    assert ctl["negative_control"] and ctl["out_of_spec"]
    assert ctl["cp_upper"] >= per_sweep.TARGET_PER
    # same SNR with no offset is clean, so the offset is what fails it
    clean = point(snr=params.snr_db, cap=20)
    assert clean["errors"] == 0


def test_row_summary_excludes_control_and_out_of_spec_and_reports_verdict():
    ok = point(snr=per_sweep.TARGET_SNR_DB, cap=3)
    ctl = dict(ok, negative_control=True, row_id="negative_control")
    off = dict(ok, out_of_spec=True, row_id="per_cfo")
    rows = per_sweep.row_summary([dict(ok, row_id="per_cfo"), ctl, off])
    assert list(rows) == ["per_cfo"] and rows["per_cfo"]["points"] == 1
    assert rows["per_cfo"]["all_points_measured"] is False
    ctl_report = per_sweep.control_summary([dict(ctl, cp_upper=1.0)])
    assert ctl_report["fails_row"] is True
    assert per_sweep.control_summary([dict(ctl, cp_upper=0.001)])["fails_row"] is False


def test_quick_mode_cli_json_contract_and_time_bound(tmp_path):
    out = tmp_path / "per.json"
    t0 = time.time()
    subprocess.run([sys.executable, SWEEP, "--quick", "--out", str(out)], check=True,
                   capture_output=True)
    assert time.time() - t0 < 120
    rep = json.loads(out.read_text())
    assert rep["mode"] == "quick" and rep["label"] == "simulated, CM-A"
    assert rep["prng"]["family"] == "PCG64"
    assert rep["negative_control"]["fails_row"] is True
    assert all(p["label"] == "simulated, CM-A" for p in rep["points"])
    capped = [p for p in rep["points"] if p["errors"] < 100]
    assert capped and all(p["bound_only"] for p in capped)
