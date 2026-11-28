"""Shared evidence-envelope invariants for the signoff gate (issue #208).

    python3 verification/fv/envelope_check.py \
        --manifest manifests/sky130-ble-baseband.json --want-klt <version>

Every envelope the block manifest cites is one of two kinds:

- a klt report with a `provenance` block, whose `klt_version` must equal the
  pinned release the caller installed (`--want-klt`), or the envelope was
  re-attested off-pin and the evidence provenance is broken;
- a klt functional-verification report (`"tests" in d and "test_count" in d`,
  the same classifier the gate always used), which carries NO provenance
  block at the klayout-tools==0.9.2 pin -- its verdict depends on no PDK and
  no rule deck (klt docs/cli/functional-verification.md at the pin; upstream
  2AMLogic/klayout-tools#5550's fix is unreleased). Such an envelope is
  instead shape-checked (status/counts/tests, the same envelope shape klt
  signoff itself validates) and must contain no absolute host path -- the
  same invariant `make fv-check` enforces on the reports directory, so
  committed evidence cannot name the machine that produced it.

The functional-verification provenance exemption is self-retiring, not
lenient: it applies only while `provenance` is absent or null. The day a
future klt release adds a provenance block to FV reports and this repo bumps
its pin, the block is already held to the same `klt_version == want`
assertion instead of being skipped silently while the gate stays green.

Pure Python stdlib on purpose: `.github/workflows/signoff.yml` runs this on
bare system Python with only klayout-tools installed (no `.venv`, no
cocotb), so this module must not import `check_reports.py` or `suite.py`
(`suite` imports `run_mac` -> `cocotb`). The dependency runs the other way:
`check_reports.py` imports the FV shape validator, the host-path check and
the count predicate from here (`fv_shape_problems`, `host_path_problems`,
`is_count`), so `make fv-check` and this gate apply one copy of each
invariant.
Envelope paths in the manifest are repo-relative: run from the repo root.
"""

import json
import re
import sys
from pathlib import Path

# Match any leading POSIX path, any embedded multi-segment POSIX path or known
# host root (e.g. inside an assertion message), file:/// URIs, or Windows drive
# paths, while ignoring relative paths like `flow/build/fv/...` or `replay/case=0`.
_ABS_HOST_PATH_RE = re.compile(
    r"(?:^/"
    r"|(?<![A-Za-z0-9_./-])/[A-Za-z0-9._-]+/[A-Za-z0-9._-]+"
    r"|(?<![A-Za-z0-9_./-])/(?:home|Users|tmp|var|opt|root|etc|usr|srv|mnt|media|private|workspace|runner|github)(?:/|\b)"
    r"|file:///"
    r"|(?<![A-Za-z0-9_])[A-Za-z]:[/\\])"
)


def _walk_strings(node, field=""):
    if isinstance(node, str):
        yield field, node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{field}.{k}" if field else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{field}[{i}]")


def is_fv_envelope(d):
    """The classifier the signoff gate always used: a klt functional-
    verification report carries `tests` plus `test_count`."""
    return isinstance(d, dict) and "tests" in d and "test_count" in d


def is_count(v):
    """A klt count: a non-negative int. bool is an int subclass, so `true`
    is not a count."""
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def fv_shape_problems(d):
    """Messages naming every way `d` is not a well-formed klt
    functional-verification envelope (status/counts/tests); empty when it is
    one. Shared with `check_reports.py`, so `make fv-check` and this gate
    cannot drift apart."""
    problems = []
    if d.get("status") not in ("pass", "fail"):
        problems.append(f"status is {d.get('status')!r}, "
                        "expected 'pass' or 'fail'")
    counts = {}
    for k in ("test_count", "passed_count", "failed_count", "skipped_count"):
        v = d.get(k)
        if not is_count(v):
            problems.append(f"{k} is {v!r}, expected a non-negative int")
        else:
            counts[k] = v
    tests = d.get("tests")
    if not isinstance(tests, list):
        problems.append(f"tests is {tests!r}, expected a list")
        tests = None
    if len(counts) == 4 and tests is not None:
        total = counts["passed_count"] + counts["failed_count"] + counts["skipped_count"]
        if not (total == counts["test_count"] == len(tests)):
            problems.append("counts disagree with tests[]: "
                            f"passed+failed+skipped={total}, "
                            f"test_count={counts['test_count']}, "
                            f"len(tests)={len(tests)}")
    if tests is not None:
        for t in tests:
            status = t.get("status") if isinstance(t, dict) else None
            if status not in ("passed", "failed", "skipped"):
                name = t.get("name") if isinstance(t, dict) else t
                problems.append(f"test {name!r} has status {status!r}")
    return ["not a well-formed klt functional-verification envelope "
            f"(status/counts/tests): {detail}" for detail in problems]


def host_path_problems(d):
    """One message per string in `d` that is or embeds an absolute host path.

    Every offending field is reported, not just the first: one envelope can
    embed several host paths, and each names a leak to fix. Shared with
    `check_reports.py`.
    """
    return [f"absolute host path at {field}: {s!r}"
            for field, s in _walk_strings(d) if _ABS_HOST_PATH_RE.search(s)]


def _provenance_problems(f, d, want):
    prov = d.get("provenance")
    if prov is None:
        return [(f, f"does not record a provenance.klt_version (unreadable or "
                   f"not a klt signoff envelope); expected the installed "
                   f"version '{want}'")]
    got = prov.get("klt_version") if isinstance(prov, dict) else None
    if got is None:
        return [(f, f"provenance block carries no klt_version; expected the "
                   f"installed version '{want}'")]
    if got != want:
        return [(f, f"provenance.klt_version is '{got}' but this job "
                   f"installed klt '{want}' - re-attest with the pinned "
                   f"release")]
    return []


def check_envelope(f, d, want):
    """Validate one loaded envelope against the installed klt version.

    Returns a list of (file, message) problem tuples; empty means the
    envelope is fine. `f` is the envelope's cited path (used verbatim in
    GitHub Actions `::error file=...::` diagnostics).
    """
    problems = []
    if not isinstance(d, dict):
        return [(f, f"envelope is a JSON {type(d).__name__}, not an object; "
                    f"expected a klt envelope")]
    if is_fv_envelope(d):
        problems += [(f, m) for m in
                     fv_shape_problems(d) + host_path_problems(d)]
        # Self-retiring exemption: an FV report is exempt from the
        # klt_version assertion only for as long as it actually lacks a
        # provenance block. A present one (dict or not) is held to it.
        if d.get("provenance") is not None:
            problems += _provenance_problems(f, d, want)
    else:
        problems += _provenance_problems(f, d, want)
    return problems


def check_manifest(manifest_path, want):
    """Check every envelope the block manifest cites.

    Returns (problems, envelope_count, fv_count): `problems` is a list of
    (file, message) tuples, empty when everything passes. An unreadable,
    schema-drifted or empty manifest yields a single fatal problem -- the
    check never passes vacuously over a manifest it could not read.
    """
    problems = []
    f = str(manifest_path)
    try:
        with open(manifest_path) as fh:
            manifest = json.load(fh)
    except (OSError, ValueError) as e:
        return [(f, f"unreadable ({e}); expected the block manifest")], 0, 0
    if not isinstance(manifest, dict):
        return [(f, "schema-drifted: top level is not a JSON object")], 0, 0
    evidence = manifest.get("evidence")
    if not isinstance(evidence, dict) or not evidence:
        return [(f, "cites no evidence envelopes (evidence map missing, "
                    "schema-drifted, or empty)")], 0, 0
    envelope_count = 0
    fv_count = 0
    for item, entry in sorted(evidence.items()):
        for e in entry if isinstance(entry, list) else [entry]:
            if not isinstance(e, dict) or not isinstance(e.get("file"), str) \
                    or not e["file"]:
                problems.append((f, f"evidence[{item!r}] entry has no 'file' "
                                    f"string (schema drift)"))
                continue
            ef = e["file"]
            try:
                with open(ef) as fh:
                    d = json.load(fh)
            except (OSError, ValueError) as e2:
                problems.append((ef, f"unreadable as JSON ({e2})"))
                continue
            envelope_count += 1
            fv_count += 1 if is_fv_envelope(d) else 0
            problems += check_envelope(ef, d, want)
    if envelope_count == 0 and not problems:
        problems.append((f, "cites no evidence envelopes (every evidence "
                            "entry is an empty list)"))
    return problems, envelope_count, fv_count


def main(argv):
    manifest = None
    want = None
    args = iter(argv)
    for a in args:
        if a == "--manifest":
            manifest = next(args, None)
        elif a == "--want-klt":
            want = next(args, None)
        else:
            print(f"unknown argument: {a}", file=sys.stderr)
            print(f"usage: {Path(__file__).name} --manifest <path> "
                  f"--want-klt <version>", file=sys.stderr)
            return 2
    if not manifest or not want:
        print(f"usage: {Path(__file__).name} --manifest <path> "
              f"--want-klt <version>", file=sys.stderr)
        return 2
    problems, total, fv = check_manifest(manifest, want)
    if problems:
        for f, m in problems:
            print(f"::error file={f}::{m}")
        print(f"envelope-check FAILED: {len(problems)} problem(s) across the "
              f"evidence cited by {manifest}", file=sys.stderr)
        return 1
    print(f"envelope-check OK: {total} envelope(s) cited by {manifest} "
          f"({fv} functional-verification, {total - fv} provenance-pinned) "
          f"match klt {want}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
