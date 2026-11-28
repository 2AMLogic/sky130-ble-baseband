"""CLI regression tests for the functional-verification report checker."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "verification" / "fv" / "check_reports.py"
COMMITTED = ROOT / "manifests" / "reports" / "fv"

# The message prefix of the shared envelope-shape validator
# (envelope_check.fv_shape_problems), which the signoff gate applies too.
SHAPE = ("not a well-formed klt functional-verification envelope "
         "(status/counts/tests)")

WRONG_REASON_PREFIX = "failed for the wrong reason; no error_message matches '"


def run_checker(reports):
    return subprocess.run(
        [sys.executable, CHECKER, "--reports", reports],
        capture_output=True,
        text=True,
        check=False,
    )


def corrupted_reports(tmp_path, name, **fields):
    """The committed report set, with one report's top-level `fields`
    replaced."""
    reports = shutil.copytree(COMMITTED, tmp_path / "fv")
    path = reports / name
    report = json.loads(path.read_text())
    report.update(fields)
    path.write_text(json.dumps(report))
    return reports


def failed_test(error_message):
    """Top-level fields making a negative control a one-test report whose
    only test failed carrying `error_message`."""
    return {"test_count": 1, "passed_count": 0, "failed_count": 1,
            "skipped_count": 0,
            "tests": [{"name": "t0", "status": "failed",
                       "error_message": error_message}]}


def test_non_object_reports_are_all_named(tmp_path):
    reports = shutil.copytree(ROOT / "manifests" / "reports" / "fv", tmp_path / "fv")
    bad_reports = {
        "le1m_tx.json": "42",
        "le1m_tx.negative.json": "[1, 2]",
        "top.json": "null",
    }
    for name, contents in bad_reports.items():
        (reports / name).write_text(contents)

    result = subprocess.run(
        [sys.executable, CHECKER, "--reports", reports],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    for name in bad_reports:
        assert f"ERROR: {reports / name}: not a JSON object" in result.stderr


@pytest.mark.parametrize("name, fields, shape, own, own_prefix", [
    # bool is an int subclass: `true` is not a count
    ("le1m_tx.json",
     {"test_count": True, "passed_count": True, "failed_count": False,
      "skipped_count": False},
     ["test_count is True, expected a non-negative int",
      "passed_count is True, expected a non-negative int",
      "failed_count is False, expected a non-negative int",
      "skipped_count is False, expected a non-negative int"],
     [], []),
    ("le1m_tx.json", {"tests": [42]},
     ["test 42 has status None"], [], []),
    ("le1m_tx.negative.json", {"tests": [42]},
     ["test 42 has status None"], ["no failed test recorded"], []),
    ("le1m_tx.json", {"passed_count": None},
     ["passed_count is None, expected a non-negative int"], [], []),
    ("le1m_tx.json", {"passed_count": "8"},
     ["passed_count is '8', expected a non-negative int"], [], []),
    ("le1m_tx.json", {"tests": None},
     ["tests is None, expected a list"], [], []),
    ("le1m_tx.negative.json", {"tests": None},
     ["tests is None, expected a list"], ["no failed test recorded"], []),
    ("le1m_tx.negative.json", {"tests": "oops"},
     ["tests is 'oops', expected a list"], ["no failed test recorded"], []),
    ("le1m_tx.negative.json", failed_test(5),
     ["test 't0' has error_message 5, expected a string or null"],
     [], [WRONG_REASON_PREFIX]),
    ("le1m_tx.negative.json", failed_test(["x"]),
     ["test 't0' has error_message ['x'], expected a string or null"],
     [], [WRONG_REASON_PREFIX]),
    ("le1m_tx.negative.json", failed_test(0),
     ["test 't0' has error_message 0, expected a string or null"],
     [], [WRONG_REASON_PREFIX]),
    ("le1m_tx.negative.json", failed_test(False),
     ["test 't0' has error_message False, expected a string or null"],
     [], [WRONG_REASON_PREFIX]),
    ("le1m_tx.negative.json", failed_test(None), [],
     [], [WRONG_REASON_PREFIX]),
])
def test_malformed_envelope_is_named_not_a_crash(tmp_path, name, fields,
                                                 shape, own, own_prefix):
    """A report whose envelope is malformed is rejected the way the signoff
    gate's envelope_check.py rejects it: `shape` details carry the shared
    validator's prefix, `own` are the checker's own rules and `own_prefix`
    the starts of own-rule lines whose tail embeds suite.py's right-reason
    pattern -- and the run is named `ERROR:` lines and exit 1, never a
    traceback."""
    reports = corrupted_reports(tmp_path, name, **fields)

    result = run_checker(reports)

    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    lines = result.stderr.splitlines()
    assert lines, "no problem named"
    assert all(line.startswith("ERROR: ") for line in lines), result.stderr
    for detail in shape:
        assert f"ERROR: {reports / name}: {SHAPE}: {detail}" in lines
    for detail in own:
        assert f"ERROR: {reports / name}: {detail}" in lines
    for prefix in own_prefix:
        assert any(line.startswith(f"ERROR: {reports / name}: {prefix}")
                   for line in lines), result.stderr


def test_committed_reports_still_pass(tmp_path):
    result = run_checker(shutil.copytree(COMMITTED, tmp_path / "fv"))

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
