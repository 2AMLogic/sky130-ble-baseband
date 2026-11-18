"""BER sweep driver: grids, stop rule, row verdict, shards and the JSON contract.

The statistics, seeding and shared scaffolding these exercise through the driver
are tested directly in test_sweep_common.py."""

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SWEEP = os.path.join(HERE, "..", "sweep", "ber_sweep.py")
sys.path[:0] = [os.path.join(HERE, "..", "sweep")]
import ber_sweep  # noqa: E402
import cm_a  # noqa: E402
import sweep_common  # noqa: E402


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


# ------------------------------------ undelivered-packet accounting (issue #133)

def _noiseless():
    """A channel no noise, offset or clock error can touch: charges come only
    from the injected length-field flip."""
    return cm_a.CmAParams(ebn0_db=float("inf"), cfo_hz=0.0, clock_ppm=0.0)


def _flip_tx_length_bit(bit):
    """Flip one bit of the on-air length octet (tx[48:56], LSB first): the
    packet the receiver demodulates really does carry the corrupted field,
    exactly as a noise hit delivers it. 37 with bit ``bit`` flipped."""
    real = cm_a.generate_packet

    def wrapper(tx, params, rng):
        tx = list(tx)
        tx[48 + bit] ^= 1
        return real(tx, params, rng)

    return wrapper


def _force_sync_miss(rx):
    rx["synced"] = False


def _demodulate_wrapper(mutate):
    real = ber_sweep.le1m_rx.demodulate

    def wrapper(iq, flags=None, gain=None, **kw):
        rx = real(iq, flags, gain, **kw)
        mutate(rx)
        return rx

    return wrapper


def test_length_flip_charges_only_demodulated_bits(monkeypatch):
    """Issue #133: the receiver derives its output length from the received
    length field. Bit 5 flipped (37 reads as 5, and the flip is inside the
    delivered 80 bits) makes it return 80 of the 336 PDU+CRC bits; the 256
    un-demodulated tail bits are not wrong decisions and must not be charged.
    The no-flip control charges 0, so the assertion cannot pass vacuously."""
    control = ber_sweep.run_point("t", 0, _noiseless(), 37, 1, 100, 1)
    assert control["packets"] == 1
    assert control["errors"] == 0 and control["bits"] == 336
    assert control["undelivered_packets"] == 0 and control["crc_failures"] == 0

    monkeypatch.setattr(cm_a, "generate_packet", _flip_tx_length_bit(5))
    flipped = ber_sweep.run_point("t", 0, _noiseless(), 37, 1, 100, 1)
    assert flipped["packets"] == 1 and flipped["errors"] == 1
    assert flipped["bits"] == 16 + 8 * 5 + 24            # the delivered prefix only
    assert flipped["undelivered_packets"] == 1 and flipped["crc_failures"] == 1


def test_overlong_delivery_is_counted_undelivered_not_charged(monkeypatch):
    """Bit 6 flipped (37 reads as 101) makes the receiver demodulate past the
    packet end until the record exhausts; the surplus bits are handled
    explicitly — the packet is counted undelivered and only the comparable
    prefix is scored — never folded into a bit-error charge."""
    monkeypatch.setattr(cm_a, "generate_packet", _flip_tx_length_bit(6))
    pt = ber_sweep.run_point("t", 0, _noiseless(), 37, 1, 100, 1)
    assert pt["packets"] == 1 and pt["errors"] == 1 and pt["bits"] == 336
    assert pt["undelivered_packets"] == 1 and pt["crc_failures"] == 1


def test_sync_miss_convention_is_unchanged(monkeypatch):
    """A sync-missed packet still counts as every PDU+CRC bit in error — the
    convention the committed record documents as ``missed_packet_counts_as``.
    It has its own counter and is not an undelivered wrong-length delivery."""
    monkeypatch.setattr(ber_sweep.le1m_rx, "demodulate",
                        _demodulate_wrapper(_force_sync_miss))
    missed = ber_sweep.run_point("t", 0, _noiseless(), 37, 1, 100, 1)
    assert missed["sync_misses"] == 1
    assert missed["errors"] == 336 and missed["bits"] == 336
    assert missed["undelivered_packets"] == 0


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
    monkeypatch.setattr(sweep_common, "SIM", str(tmp_path))
    monkeypatch.setattr(sweep_common, "git_sha", lambda: CLEAN_SHA)
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


# ------------------------------------- an asserted sim_git_sha (batch sharding)

def test_asserted_sha_is_recorded_as_asserted(tmp_path, monkeypatch):
    """A runner with no repo git root names the commit; the report says so."""
    monkeypatch.setattr(sweep_common, "SIM", str(tmp_path))
    monkeypatch.setattr(sweep_common, "git_sha",
                        lambda: pytest.fail("git must not be consulted for an asserted sha"))
    assert ber_sweep.main(["--only", "le1m_uniform", "--sim-git-sha", CLEAN_SHA, *TINY]) == 0
    files = list(tmp_path.glob("results/*/shards/*.json"))
    assert [f.name for f in files] == ["le1m_uniform.json"]
    assert files[0].parent.parent.name.endswith(f"-{CLEAN_SHA}")
    rep = json.loads(files[0].read_text())
    assert rep["sim_git_sha"] == CLEAN_SHA
    assert rep["sim_git_sha_source"] == ber_sweep.SHA_ASSERTED


def test_derived_sha_is_recorded_as_derived(tmp_path, monkeypatch):
    monkeypatch.setattr(sweep_common, "SIM", str(tmp_path))
    monkeypatch.setattr(sweep_common, "git_sha", lambda: CLEAN_SHA)
    assert ber_sweep.main(["--only", "le1m_uniform", *TINY]) == 0
    rep = json.loads(next(tmp_path.glob("results/*/shards/*.json")).read_text())
    assert rep["sim_git_sha_source"] == ber_sweep.SHA_DERIVED


@pytest.mark.parametrize("bad", ["", "0123456789AB", "0123", "0123456789ab-dirty",
                                 "unknown", "0123456789ab ", "z123456789ab"])
def test_asserted_sha_must_be_a_bare_hex_commit_id(tmp_path, monkeypatch, bad):
    monkeypatch.setattr(sweep_common, "SIM", str(tmp_path))
    with pytest.raises(SystemExit) as e:
        ber_sweep.main(["--only", "le1m_uniform", "--sim-git-sha", bad, *TINY])
    assert e.value.code == 2
    assert not list(tmp_path.glob("results/**/*.json"))


def test_asserted_sha_is_refused_with_merge(tiny, tmp_path):
    with pytest.raises(SystemExit) as e:
        ber_sweep.main(["--merge", str(tiny[1]), "--out", str(tmp_path / "o.json"),
                        "--sim-git-sha", CLEAN_SHA])
    assert e.value.code == 2
    assert not (tmp_path / "o.json").exists()


def test_merge_refuses_mixed_sha_provenance(tiny, tmp_path, capsys):
    """A derived shard and an asserted one are not the same evidence."""
    d = _copy(tiny[1], tmp_path)
    for f in d.iterdir():
        _rewrite(f, sim_git_sha_source=ber_sweep.SHA_ASSERTED)
    _rewrite(d / "le1m_clock.json", sim_git_sha_source=ber_sweep.SHA_DERIVED)
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "sim_git_sha_source" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


def test_merge_carries_sha_provenance_through(tiny, tmp_path):
    d = _copy(tiny[1], tmp_path)
    for f in d.iterdir():
        _rewrite(f, sim_git_sha_source=ber_sweep.SHA_ASSERTED)
    out = tmp_path / "ber.json"
    assert ber_sweep.main(["--merge", str(d), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["sim_git_sha_source"] == ber_sweep.SHA_ASSERTED


def test_merge_records_the_shards_numpy_not_the_merging_hosts(tiny, tmp_path):
    """A merge runs no simulation, so the PRNG record must come from the shards."""
    shard_numpy = f"0.0.1+not-{ber_sweep.np.__version__}"  # never the host's version
    d = _copy(tiny[1], tmp_path)
    for f in d.iterdir():
        _rewrite(f, prng={"family": "PCG64", "numpy_version": shard_numpy})
    out = tmp_path / "ber.json"
    assert ber_sweep.main(["--merge", str(d), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["prng"] == {"family": "PCG64",
                                                  "numpy_version": shard_numpy}
    assert shard_numpy != ber_sweep.np.__version__, "fixture no longer distinguishes the two"


def test_merge_refuses_mixed_numpy_versions(tiny, tmp_path, capsys):
    d = _copy(tiny[1], tmp_path)
    _rewrite(d / "le1m_clock.json", prng={"family": "PCG64", "numpy_version": "0.0.1"})
    assert ber_sweep.main(["--merge", str(d), "--out", str(tmp_path / "o.json")]) == 1
    assert "prng" in capsys.readouterr().err
    assert not (tmp_path / "o.json").exists()


# ------------------------------------------- the committed full-sweep evidence

RESULTS = pathlib.Path(SWEEP).parents[1] / "results"


def _committed_reports():
    return sorted(RESULTS.glob("*/ber.json"))


@pytest.mark.skipif(not _committed_reports(), reason="no committed full-sweep result yet")
@pytest.mark.parametrize("path", _committed_reports(), ids=lambda p: p.parent.name)
def test_committed_result_parses_and_its_negative_control_fails_the_row(path):
    """Append-only evidence: every committed result stays readable, and its
    deterministic negative control stays a visible failure. A capped point is
    never read as a measurement."""
    rep = json.loads(path.read_text())
    assert rep["format"] == sweep_common.FORMAT
    assert rep["mode"] == "full" and rep["label"] == sweep_common.LABEL
    assert not str(rep["sim_git_sha"]).endswith("-dirty")
    assert rep["prng"]["numpy_version"] and rep["prng"]["family"] == "PCG64"

    # the full grid, in grid order
    assert [p["point_index"] for p in rep["points"]] == list(range(len(ber_sweep.full_grid())))

    nc = [p for p in rep["points"] if p["negative_control"]]
    assert len(nc) == 1, "exactly one deterministic negative control"
    assert nc[0]["out_of_spec"], "the control is out of spec and excluded from rows"
    assert nc[0]["cp_upper"] > ber_sweep.TARGET_BER, "the control must visibly fail the row"
    assert nc[0]["row_id"] not in rep["rows"]

    for row_id, r in rep["rows"].items():
        assert r["ebn0_db"] == ber_sweep.TARGET_EBN0_DB
        # a row verdict is only reported as met when no point behind it was capped
        if r["upper_bound_meets_target"]:
            assert r["all_points_measured"], f"{row_id}: a capped point cannot meet the target"
    for p in rep["points"]:
        assert p["bound_only"] == (p["stopped_by"] == "packet_cap")
        assert p["cp_lower"] <= p["cp_upper"]
