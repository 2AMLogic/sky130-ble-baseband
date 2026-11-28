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
- every report has the klt functional-verification envelope shape
  (status/counts/tests). Both rules are the signoff gate's own, imported
  from `envelope_check.py`, so `make fv-check` and the gate apply one copy
  of each;
- no extra undeclared `*.json` report sits in the reports directory.

Read-only, but not stdlib-only: importing `suite` pulls in the `run_*.py`
runners and through them `cocotb`, so run it under the repo venv
(`make fv-check` does). A malformed report is a named `ERROR:` line and
exit 1, never a traceback.
"""

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE)]

import suite  # noqa: E402
# The envelope shape (status/counts/tests) and the host-path rule live in
# envelope_check.py (issue #208): pure stdlib, no cocotb, so the signoff CI
# job and this checker share one copy of each invariant.
from envelope_check import (  # noqa: E402
    fv_shape_problems, host_path_problems, is_count)


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
    problems += [f"{path}: {m}" for m in host_path_problems(rep)]
    if rep.get("hdl_toplevel") != bench["hdl_toplevel"]:
        problems.append(f"{path}: hdl_toplevel is {rep.get('hdl_toplevel')!r}, "
                        f"expected {bench['hdl_toplevel']!r}")
    if rep.get("testbench") != bench["module"]:
        problems.append(f"{path}: testbench is {rep.get('testbench')!r}, "
                        f"expected {bench['module']!r}")
    problems += [f"{path}: {m}" for m in fv_shape_problems(rep)]


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
        passed = rep.get("passed_count")
        if is_count(passed) and passed < 1:
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
        tests = rep.get("tests")
        failures = ([t.get("error_message") for t in tests
                     if isinstance(t, dict) and t.get("status") == "failed"]
                    if isinstance(tests, list) else [])
        if not failures:
            problems.append(f"{path}: no failed test recorded")
        elif not any(isinstance(m, str) and re.search(neg["reason"], m)
                     for m in failures):
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
