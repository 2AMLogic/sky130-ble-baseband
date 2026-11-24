"""Unit and CLI tests for verification/fv/envelope_check.py (issue #208).

Test-plan rows from the issue, each asserted on the library functions
(`check_envelope` / `check_manifest`) or on the CLI's exit code and
GitHub-Actions `::error file=<f>::...` diagnostics:

- FV envelope (tests + test_count) without a provenance block passes, whether
  the key is absent or explicitly null (both exempt)
- FV envelope with a provenance block whose klt_version matches --want-klt
  passes: the exemption is self-retiring, not a skip
- FV envelope with a mismatching klt_version, an empty provenance block, or a
  non-dict provenance block fails, naming the envelope and both versions
- an FV envelope with host paths embedded in two separate fields reports BOTH
  field paths in one run (not first-match-and-bail)
- host-path variants (leading /, embedded multi-segment, known host root,
  file:///, Windows drive) are flagged; relative paths such as
  `flow/build/fv/...` or `model_traces/tx_adv_ch37.trace` are not
- malformed FV shape (status, per-key counts, bool/negative counts, tests not
  a list, count disagreement, per-test status) fails naming the detail
- non-FV envelopes: matching provenance passes; missing provenance block and
  mismatching klt_version fail
- manifest-level failures are loud, never a vacuous pass: unreadable JSON,
  non-object top level, missing/empty evidence map, entry without a `file`
  string, and an envelope file that is not JSON
- multiple offending envelopes are all reported before the non-zero exit
- the repo's committed manifests/sky130-ble-baseband.json passes whole
  (24 envelopes, 22 functional-verification) against the recorded pin
- usage errors exit 2; check_reports.py keeps no second copy of the regex or
  walker, and envelope_check.py imports no cocotb-reachable module

Pure Python: no simulator, no PDK, no cocotb. Carried by `make parser-test`.
"""

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fv"))
import envelope_check  # noqa: E402

SCRIPT = Path(envelope_check.__file__).resolve()
REPO_ROOT = Path(__file__).resolve().parents[2]
COMMITTED_MANIFEST = "manifests/sky130-ble-baseband.json"
PIN = "0.9.2"


def fv_envelope(**over):
    """A well-formed functional-verification envelope; `over` wins."""
    d = {
        "schema_version": 2,
        "engine": "icarus",
        "hdl_toplevel": "baseband_top",
        "testbench": "test_top",
        "status": "pass",
        "test_count": 1,
        "passed_count": 1,
        "failed_count": 0,
        "skipped_count": 0,
        "tests": [{"name": "t0", "status": "passed"}],
    }
    d.update(over)
    return d


def provenance_envelope(version=PIN):
    return {"schema_version": 1, "kind": "generic", "status": "pass",
            "provenance": {"klt_version": version}}


def msgs(problems):
    return [m for _, m in problems]


def write_manifest(tmp_path, entries):
    """Write envelope files plus the manifest citing them. `entries` is
    {item: [(repo-relative path, envelope dict), ...]}; returns the
    manifest's path."""
    evidence = {}
    for item, envs in entries.items():
        evidence[item] = []
        for rel, d in envs:
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(d))
            evidence[item].append({"file": rel})
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"kind": "block", "evidence": evidence}))
    return m


def run_cli(manifest, want=PIN, cwd=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(manifest),
         "--want-klt", want],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None)


# ---------------------------------------------------------------- FV kind

def test_fv_without_provenance_passes():
    assert envelope_check.check_envelope("e.json", fv_envelope(), PIN) == []


def test_fv_with_null_provenance_passes():
    assert envelope_check.check_envelope(
        "e.json", fv_envelope(provenance=None), PIN) == []


def test_fv_with_matching_provenance_passes():
    assert envelope_check.check_envelope(
        "e.json", fv_envelope(provenance={"klt_version": PIN}), PIN) == []


def test_fv_with_mismatched_provenance_fails():
    problems = envelope_check.check_envelope(
        "e.json", fv_envelope(provenance={"klt_version": "0.8.0"}), PIN)
    assert len(problems) == 1
    assert problems[0][0] == "e.json"
    assert "provenance.klt_version is '0.8.0'" in problems[0][1]
    assert f"installed klt '{PIN}'" in problems[0][1]


@pytest.mark.parametrize("prov", [{}, "0.9.2", [], {"klt_version": None}])
def test_fv_with_provenance_lacking_klt_version_fails(prov):
    problems = envelope_check.check_envelope(
        "e.json", fv_envelope(provenance=prov), PIN)
    assert len(problems) == 1
    assert "klt_version" in problems[0][1]


def test_fv_host_paths_report_every_field():
    d = fv_envelope(
        status="fail", test_count=2, passed_count=1, failed_count=1,
        tests=[{"name": "t0", "status": "passed"},
               {"name": "t1", "status": "failed",
                "error_message": "mismatch vs /tmp/golden/le1m.bin"}],
        tool_copy="archived from /home/builder/run7",
    )
    problems = envelope_check.check_envelope("e.json", d, PIN)
    assert len(problems) == 2  # both leaks in one run, not first-and-bail
    text = msgs(problems)
    assert any("tests[1].error_message" in m for m in text)
    assert any("tool_copy" in m for m in text)
    assert all(p[0] == "e.json" for p in problems)


@pytest.mark.parametrize("bad", [
    "built at /home/builder/run7",            # known host root
    "/flow/build/fv/top.json",                # leading POSIX path
    "see icarus under /usr/local/bin/iverilog",  # embedded multi-segment
    "stored as file:///srv/evidence/top.json",   # file:/// URI
    "ran with C:\\tools\\icarus\\bin",        # Windows drive path
])
def test_host_path_variants_flagged(bad):
    problems = envelope_check.check_envelope(
        "e.json", fv_envelope(tool_copy=bad), PIN)
    assert len(problems) == 1
    assert "absolute host path" in problems[0][1]


@pytest.mark.parametrize("good", [
    "flow/build/fv/top.json",
    "model_traces/tx_adv_ch37.trace",
    "replay/case=0",
    "sha256:cfc7749b96263bd31c3f42b5c471bf756814053e847c10f3eb003417bc523d30",
    "icarus 13.0 (v13_0)",
])
def test_relative_paths_not_flagged(good):
    assert envelope_check.check_envelope(
        "e.json", fv_envelope(tool_copy=good), PIN) == []


@pytest.mark.parametrize("over,detail", [
    ({"status": "PASS"}, "status is 'PASS'"),
    ({"status": None}, "status is None"),
    ({"test_count": -1}, "test_count is -1"),
    ({"failed_count": True}, "failed_count is True"),
    ({"skipped_count": "0"}, "skipped_count is '0'"),
    ({"passed_count": None}, "passed_count is None"),
    ({"tests": {"t0": "passed"}}, "tests is"),
    ({"tests": []}, "counts disagree with tests[]"),
    ({"test_count": 2}, "counts disagree with tests[]"),
    ({"tests": [{"name": "t0", "status": "PASS"}]}, "test 't0' has status 'PASS'"),
    ({"tests": [{"name": "t0"}]}, "test 't0' has status None"),
])
def test_fv_shape_failures_name_the_detail(over, detail):
    problems = envelope_check.check_envelope("e.json", fv_envelope(**over), PIN)
    assert problems, "malformed FV envelope passed"
    assert problems[0][0] == "e.json"
    assert "not a well-formed klt functional-verification envelope" \
        in problems[0][1]
    assert detail in problems[0][1]


def test_fv_shape_reports_every_violation():
    problems = envelope_check.check_envelope(
        "e.json", fv_envelope(status="bogus", passed_count=-1,
                              tests=[{"status": "nope"}]), PIN)
    assert len(msgs(problems)) >= 3


# ------------------------------------------------------------ non-FV kind

def test_non_fv_matching_provenance_passes():
    assert envelope_check.check_envelope(
        "e.json", provenance_envelope(), PIN) == []


def test_non_fv_missing_provenance_fails():
    absent = provenance_envelope()
    del absent["provenance"]
    for d in (absent, dict(provenance_envelope(), provenance=None)):
        problems = envelope_check.check_envelope("e.json", d, PIN)
        assert len(problems) == 1
        assert "does not record a provenance.klt_version" in problems[0][1]


def test_non_fv_mismatched_provenance_fails():
    problems = envelope_check.check_envelope(
        "e.json", provenance_envelope(version="0.8.0"), PIN)
    assert len(problems) == 1
    assert "provenance.klt_version is '0.8.0'" in problems[0][1]


# ------------------------------------------------- manifest-level failures

def test_manifest_unreadable_json_is_fatal(tmp_path):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text("{not json")
    problems, total, fv = envelope_check.check_manifest(m, PIN)
    assert total == 0 and fv == 0
    assert len(problems) == 1
    assert "unreadable" in problems[0][1]


def test_manifest_non_object_top_level_is_fatal(tmp_path):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text("[1, 2]")
    problems, _, _ = envelope_check.check_manifest(m, PIN)
    assert "not a JSON object" in problems[0][1]


@pytest.mark.parametrize("body", [{}, {"kind": "block"}])
def test_manifest_without_evidence_never_passes_vacuously(tmp_path, body):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps(body))
    problems, total, _ = envelope_check.check_manifest(m, PIN)
    assert total == 0
    assert len(problems) == 1
    assert "cites no evidence envelopes" in problems[0][1]


def test_manifest_entry_without_file_is_schema_drift(tmp_path):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"evidence": {"5": [{"path": "x.json"}]}}))
    problems, _, _ = envelope_check.check_manifest(m, PIN)
    assert "evidence['5'] entry has no 'file' string" in problems[0][1]


def test_manifest_envelope_not_json_is_named(tmp_path):
    bad = tmp_path / "evidence" / "bad.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("not json at all")
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"evidence": {"5": [{"file": "evidence/bad.json"}]}}))
    problems, total, _ = envelope_check.check_manifest(m, PIN)
    assert total == 0
    assert problems[0][0] == "evidence/bad.json"
    assert "unreadable as JSON" in problems[0][1]


def test_manifest_missing_envelope_file_is_named(tmp_path):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"evidence": {"9": [{"file": "gone.json"}]}}))
    problems, _, _ = envelope_check.check_manifest(m, PIN)
    assert problems[0][0] == "gone.json"


def test_every_offending_envelope_reported(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = write_manifest(tmp_path, {
        "10": [("envs/ten.json", provenance_envelope(version="0.8.0"))],
        "5": [("envs/ok.json", fv_envelope()),
              ("envs/leak.json", fv_envelope(tool_copy="from /home/me/run")),
              ("envs/drift.json", fv_envelope(status="bogus"))],
        "9": [("envs/nine.json", provenance_envelope())],
    })
    problems, total, fv = envelope_check.check_manifest(m, PIN)
    assert (total, fv) == (5, 3)
    assert set(p[0] for p in problems) == {"envs/ten.json", "envs/leak.json",
                                           "envs/drift.json"}
    rc = run_cli(m, cwd=tmp_path)
    assert rc.returncode == 1
    for f in ("envs/ten.json", "envs/leak.json", "envs/drift.json"):
        assert f"::error file={f}::" in rc.stdout
    assert "::error file=envs/ok.json::" not in rc.stdout
    assert "FAILED" in rc.stderr


def test_cli_empty_evidence_lists_exit_1(tmp_path):
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"evidence": {"5": []}}))
    rc = run_cli(m, cwd=tmp_path)
    assert rc.returncode == 1
    assert "cites no evidence envelopes" in rc.stdout
    assert "OK" not in rc.stdout


@pytest.mark.parametrize("bad", [None, 7, True, [1], "text"])
def test_cli_non_object_envelope_does_not_stop_validation(tmp_path, bad):
    (tmp_path / "envs").mkdir()
    (tmp_path / "envs" / "weird.json").write_text(json.dumps(bad))
    (tmp_path / "envs" / "old.json").write_text(
        json.dumps(provenance_envelope(version="0.8.0")))
    m = tmp_path / "manifests" / "block.json"
    m.parent.mkdir(parents=True)
    m.write_text(json.dumps({"evidence": {"5": [
        {"file": "envs/weird.json"}, {"file": "envs/old.json"}]}}))
    rc = run_cli(m, cwd=tmp_path)
    assert rc.returncode == 1
    assert "Traceback" not in rc.stderr
    assert "::error file=envs/weird.json::" in rc.stdout
    assert "::error file=envs/old.json::" in rc.stdout


# ----------------------------------------------------------- happy paths

def test_manifest_mixed_kinds_pass(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = write_manifest(tmp_path, {
        "10": [("envs/ten.json", provenance_envelope())],
        "5": [("envs/fv.json", fv_envelope()),
              ("envs/fvp.json", fv_envelope(provenance={"klt_version": PIN}))],
        "9": [("envs/nine.json", provenance_envelope())],
    })
    problems, total, fv = envelope_check.check_manifest(m, PIN)
    assert problems == []
    assert (total, fv) == (4, 2)
    rc = run_cli("manifests/block.json", cwd=tmp_path)
    assert rc.returncode == 0
    assert "envelope-check OK: 4 envelope(s)" in rc.stdout
    assert "2 functional-verification, 2 provenance-pinned" in rc.stdout
    assert f"match klt {PIN}" in rc.stdout


def test_committed_manifest_passes_at_the_pin(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    problems, total, fv = envelope_check.check_manifest(
        COMMITTED_MANIFEST, PIN)
    assert problems == []
    assert (total, fv) == (24, 22)
    rc = run_cli(COMMITTED_MANIFEST, cwd=REPO_ROOT)
    assert rc.returncode == 0
    assert "envelope-check OK: 24 envelope(s)" in rc.stdout
    assert "(22 functional-verification, 2 provenance-pinned)" in rc.stdout


def test_committed_manifest_rejects_wrong_pin(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    problems, total, _ = envelope_check.check_manifest(
        COMMITTED_MANIFEST, "0.8.0")
    assert total == 24
    assert {p[0] for p in problems} == {"manifests/item9-attestation.json",
                                        "manifests/item10-attestation.json"}


# -------------------------------------------------------------------- CLI

def test_cli_usage_errors_exit_2(tmp_path):
    m = write_manifest(tmp_path, {"5": [("envs/fv.json", fv_envelope())]})
    for argv in ([], ["--manifest", str(m)],
                 ["--want-klt", PIN],
                 ["--manifest", str(m), "--want-klt"],
                 ["--manifest", str(m), "--want-klt", PIN, "--bonus"]):
        rc = subprocess.run([sys.executable, str(SCRIPT), *argv],
                            capture_output=True, text=True)
        assert rc.returncode == 2, argv
        assert "usage:" in rc.stderr


# ---------------------------------------------- single source of truth

def test_check_reports_imports_the_shared_copies():
    src = (SCRIPT.parent / "check_reports.py").read_text()
    tree = ast.parse(src)
    imported = {n.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module == "envelope_check"
                for n in node.names}
    assert {"_ABS_HOST_PATH_RE", "_walk_strings"} <= imported
    defined = {node.name for node in ast.walk(tree)
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert "_walk_strings" not in defined
    assigned = {t.id for node in ast.walk(tree)
                if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Name)}
    assert "_ABS_HOST_PATH_RE" not in assigned


def test_envelope_check_stays_cocotb_free():
    tree = ast.parse(SCRIPT.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    assert not (modules & {"suite", "check_reports", "cocotb", "numpy"})
