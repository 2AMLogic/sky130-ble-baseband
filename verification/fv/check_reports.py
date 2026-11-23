"""Validate the committed klt functional-verification reports (issue #202).

    $(PYTHON) verification/fv/check_reports.py

Checks every report the suite declares, against the bench table in suite.py:

- every positive run: report exists, `status` is `"pass"`, the counts agree
  with the per-test records, no test failed, none skipped, and the DUT /
  testbench echoes match the request;
- every negative control: report exists, `status` is `"fail"`, at least one
  test failed, and some failure's `error_message` matches the right-reason
  pattern -- the same rule `make test-*-negative` greps the bench log for;
- no string anywhere in a report is or embeds an absolute host path
  (2AMLogic/klayout-tools#6005 tracks the remaining open klt fields; #5784
  is closed): committed evidence must not name the machine that produced it;
- no extra undeclared `*.json` report sits in the reports directory.

Pure Python (stdlib only) and read-only, so `make lint` can run it in CI.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import suite  # noqa: E402
# The host-path regex and string walker live in envelope_check.py (issue
# #208): pure stdlib, no cocotb, so the signoff CI job and this checker
# share one copy of the invariant.
from envelope_check import _ABS_HOST_PATH_RE, _walk_strings  # noqa: E402


def _load(path, problems, expect):
    try:
        with open(path) as f:
            report = json.load(f)
    except (OSError, ValueError) as e:
        problems.append(f"{path}: unreadable ({e}); expected {expect}")
        return None
    if not isinstance(report, dict):
        problems.append(f"{path}: not a JSON object; expected {expect}")
        return None
    return report


def _check_common(path, rep, bench, problems):
    for field, s in _walk_strings(rep):
        if _ABS_HOST_PATH_RE.search(s):
            problems.append(f"{path}: absolute host path at {field}: {s!r}")
    if rep.get("hdl_toplevel") != bench["hdl_toplevel"]:
        problems.append(f"{path}: hdl_toplevel is {rep.get('hdl_toplevel')!r}, "
                        f"expected {bench['hdl_toplevel']!r}")
    if rep.get("testbench") != bench["module"]:
        problems.append(f"{path}: testbench is {rep.get('testbench')!r}, "
                        f"expected {bench['module']!r}")
    tests = rep.get("tests")
    counts = {k: rep.get(k) for k in ("test_count", "passed_count",
                                      "failed_count", "skipped_count")}
    if not isinstance(tests, list) or not all(isinstance(v, int) and v >= 0
                                              for v in counts.values()):
        problems.append(f"{path}: missing tests/counts")
        return
    if not (counts["passed_count"] + counts["failed_count"]
            + counts["skipped_count"] == counts["test_count"] == len(tests)):
        problems.append(f"{path}: counts disagree with tests[]: {counts} "
                        f"vs {len(tests)} test records")
    for t in tests:
        if t.get("status") not in ("passed", "failed", "skipped"):
            problems.append(f"{path}: test {t.get('name')!r} has status "
                            f"{t.get('status')!r}")


def main(argv):
    reports = suite.REPORTS_DIR
    if len(argv) == 2 and argv[0] == "--reports":
        reports = Path(argv[1])
    elif argv:
        print(f"usage: {Path(__file__).name} [--reports DIR]", file=sys.stderr)
        return 2
    problems = []
    for bench in suite.POSITIVE:
        path = reports / f"{bench['name']}.json"
        rep = _load(path, problems, "a passing report")
        if rep is None:
            continue
        _check_common(path, rep, bench, problems)
        if rep.get("status") != "pass":
            problems.append(f"{path}: status is {rep.get('status')!r}, expected 'pass'")
        if rep.get("failed_count") != 0:
            problems.append(f"{path}: {rep.get('failed_count')} failed test(s)")
        if rep.get("skipped_count") != 0:
            problems.append(f"{path}: {rep.get('skipped_count')} skipped test(s)")
        if rep.get("passed_count", 0) < 1:
            problems.append(f"{path}: no test passed")
    for neg in suite.NEGATIVE:
        bench = suite.positive_by_name(neg["base"])
        path = reports / f"{neg['name']}.json"
        rep = _load(path, problems, "a failing negative-control report")
        if rep is None:
            continue
        _check_common(path, rep, bench, problems)
        if rep.get("status") != "fail":
            problems.append(f"{path}: status is {rep.get('status')!r}, expected "
                            f"'fail' (negative control detected nothing)")
        failures = [t.get("error_message") or "" for t in rep.get("tests", [])
                    if t.get("status") == "failed"]
        if not failures:
            problems.append(f"{path}: no failed test recorded")
        elif not any(re.search(neg["reason"], m) for m in failures):
            problems.append(f"{path}: failed for the wrong reason; no "
                            f"error_message matches {neg['reason']!r}")
    expected = ({f"{b['name']}.json" for b in suite.POSITIVE}
                | {f"{n['name']}.json" for n in suite.NEGATIVE})
    if reports.is_dir():
        for extra in sorted(p.name for p in reports.glob("*.json") if p.name not in expected):
            problems.append(f"{reports / extra}: committed report not declared in suite.py; "
                            f"delete it (suite changed)")
    if problems:
        for p in problems:
            print(f"ERROR: {p}", file=sys.stderr)
        return 1
    print(f"fv-reports OK: {len(suite.POSITIVE)} passing reports, "
          f"{len(suite.NEGATIVE)} detected negative controls")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
