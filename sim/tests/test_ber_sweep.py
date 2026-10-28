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


# ------------------------------------------------------------ shards and merge

TINY = ["--packet-cap", "2", "--max-length-packet-cap", "2"]
CLEAN_SHA = "0123456789ab"


def _rows():
    return list(dict.fromkeys(g[0] for g in ber_sweep.full_grid()))


def _rewrite(path, **changes):
    rep = json.loads(path.read_text())
    rep.update(changes)
    path.write_text(json.dumps(rep, indent=1, sort_keys=True) + "\n")


@pytest.fixture(scope="module")
def tiny(tmp_path_factory):
    """One non-sharded tiny full run and one tiny shard per row, SHA made clean."""
    root = tmp_path_factory.mktemp("tiny")
    whole = root / "whole.json"
    subprocess.run([sys.executable, SWEEP, "--out", str(whole), *TINY],
                   check=True, capture_output=True, text=True)
    shards = root / "shards"
    for row in _rows():
        subprocess.run([sys.executable, SWEEP, "--only", row, "--out", str(shards / f"{row}.json"), *TINY],
                       check=True, capture_output=True, text=True)
    for f in [whole, *shards.iterdir()]:
        _rewrite(f, sim_git_sha=CLEAN_SHA)
    return whole, shards


def _copy(shards, tmp_path):
    dst = tmp_path / "shards"
    dst.mkdir()
    for f in shards.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    return dst


def test_full_grid_appends_negative_control_last_without_moving_seeds():
    grid = ber_sweep.full_grid()
    assert grid[-1][0] == "negative_control" and sum(g[0] == "negative_control" for g in grid) == 1
    assert grid[-1][1:] == ber_sweep.quick_grid()[-1][1:]
    assert grid[-1][3] == {"out_of_spec": True, "negative_control": True}
    assert [g[0] for g in grid[:-1]].count("le1m_uniform") == 4
    assert len(grid) == 93      # 92 pre-existing points keep indices 0..91


def test_single_row_shard_defaults_to_named_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ber_sweep, "SIM", str(tmp_path))
    monkeypatch.setattr(ber_sweep, "git_sha", lambda: CLEAN_SHA)
    assert ber_sweep.main(["--only", "le1m_uniform", *TINY]) == 0
    files = list(tmp_path.glob("results/*/shards/*.json"))
    assert [f.name for f in files] == ["le1m_uniform.json"]
    assert files[0].parent.parent.name.endswith(f"-{CLEAN_SHA}")
    rep = json.loads(files[0].read_text())
    assert rep["mode"] == "full" and rep["base_seed"] == 1 and rep["sim_git_sha"] == CLEAN_SHA
    assert rep["stop_rule"]["packet_cap"] == 2
    assert {p["row_id"] for p in rep["points"]} == {"le1m_uniform"}
    assert all(p["run_index"] == 0 and p["packets"] <= 2 for p in rep["points"])


def test_negative_control_is_a_valid_shard(tiny):
    rep = json.loads((tiny[1] / "negative_control.json").read_text())
    assert len(rep["points"]) == 1 and rep["points"][0]["negative_control"]
    assert rep["points"][0]["point_index"] == len(ber_sweep.full_grid()) - 1


def test_merge_equals_single_run(tiny, tmp_path):
    whole, shards = tiny
    out = tmp_path / "ber.json"
    assert ber_sweep.main(["--merge", str(shards), "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == json.loads(whole.read_text())
    assert out.read_bytes() == whole.read_bytes()


def test_merge_refuses_missing_row(tiny, tmp_path, capsys):
    d = _copy(tiny[1], tmp_path)
    (d / "negative_control.json").unlink()
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "negative_control" in capsys.readouterr().err and not (tmp_path / "o.json").exists()


def test_merge_refuses_duplicate_row(tiny, tmp_path, capsys):
    d = _copy(tiny[1], tmp_path)
    (d / "copy.json").write_bytes((d / "le1m_cfo.json").read_bytes())
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "duplicate row le1m_cfo" in capsys.readouterr().err


def test_merge_refuses_seed_mismatch(tiny, tmp_path, capsys):
    d = _copy(tiny[1], tmp_path)
    _rewrite(d / "le1m_clock.json", base_seed=2)
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "base_seed" in capsys.readouterr().err


def test_merge_refuses_dirty_and_quick_shards(tiny, tmp_path, capsys):
    d = _copy(tiny[1], tmp_path)
    _rewrite(d / "le1m_drift.json", sim_git_sha=CLEAN_SHA + "-dirty")
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "le1m_drift.json" in capsys.readouterr().err
    (tmp_path / "x").mkdir()
    d2 = _copy(tiny[1], tmp_path / "x")
    _rewrite(d2 / "le1m_drift.json", mode="quick")
    assert ber_sweep.main(["--merge", str(d2), "--out", str(tmp_path / "o.json")]) == 1
    assert "mode" in capsys.readouterr().err
