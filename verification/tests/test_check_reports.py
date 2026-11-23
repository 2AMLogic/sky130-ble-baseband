"""CLI regression tests for the functional-verification report checker."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "verification" / "fv" / "check_reports.py"


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
