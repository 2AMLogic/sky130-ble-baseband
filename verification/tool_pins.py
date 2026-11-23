"""The klayout-tools pin, checked for drift: CI installs it, the runbook prints it.

`.github/workflows/signoff.yml` installs the pinned `klt` build (one
`pip install klayout-tools==X.Y.Z` line), and `manifests/README.md`'s
re-attest runbook repeats that pin as a bare literal in every `uvx --from`
command block -- deliberately duplicated, one self-contained block per
re-attest case (decision recorded in #136), so the number of literal sites
only grows. Nothing compared the two kinds of place, and #148 is what the
gap costs: an envelope was committed from an unpinned `klt` build while CI
and the runbook both said the same older pin -- the runbook had become the
documented procedure for the wrong tool. This check ties them together:

    python3 verification/tool_pins.py --check     # `make lint`

The scan surface follows `git ls-files`, not a directory list, so a literal
placed anywhere tracked is guarded (issue #171). Excluded paths: `.loom/`
and `.claude/` (installed tooling provisioned outside this repo), the
byte-compared generated signoff record
(`manifests/*.signoff.json`), and this check's own negative-control suite
(`verification/tests/test_tool_pins.py`) -- those are excluded because this
repo cannot edit them to satisfy the check, not because they happen to be
clean today. Unpinned mentions are not
pins and are never flagged: `pip install klayout-tools`,
`klayout-tools[yield]`, `2AMLogic/klayout-tools@<sha>`.
"""

import fnmatch
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIGNOFF = Path(".github") / "workflows" / "signoff.yml"

# The one line CI executes; it defines "the version CI installs". Exactly one
# match is required: zero leaves the pin undefined and several leave it
# ambiguous -- both are errors, never a guess.
_PIN = re.compile(r"pip install klayout-tools==(\S+)")

# A pinned literal in any tracked file. The version must start with a digit so
# the non-pin mentions above (`yield` extra, `@<sha>`) can never match.
_SITE = re.compile(r"klayout-tools==([0-9][\w.\-+]*)")

# Paths this repo cannot edit to satisfy the check are excluded by policy, not
# because they happen to be clean today: `manifests/*.signoff.json` is the
# generated, byte-compared record. `.loom/` and `.claude/` are installed
# tooling whose sources live elsewhere. `verification/tests/test_tool_pins.py`
# is this check's own negative-control suite: its fixture literals are the
# drifted pins the tests deliberately assert on, so they cannot be edited to
# match the pin without destroying the tests.
_EXCLUDED_PREFIXES = (".loom/", ".claude/")
_EXCLUDED_FILES = ("verification/tests/test_tool_pins.py",)
_EXCLUDED_GLOBS = ("manifests/*.signoff.json",)


def _excluded(rel):
    return (rel.startswith(_EXCLUDED_PREFIXES)
            or rel in _EXCLUDED_FILES
            or any(fnmatch.fnmatch(rel, g) for g in _EXCLUDED_GLOBS))


def _tracked_files(root):
    """Every tracked path, repo-relative; refuses to return an empty scan."""
    try:
        r = subprocess.run(["git", "ls-files", "-z"], cwd=str(root),
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise ValueError(
            f"git is unavailable ({e.__class__.__name__}: {e}); refusing to "
            f"scan nothing and pass") from e
    if r.returncode != 0:
        detail = r.stderr.decode(errors="replace").strip()
        raise ValueError(f"git ls-files failed: {detail}; refusing to scan "
                         f"nothing and pass")
    names = [n for n in r.stdout.decode(errors="replace").split("\0") if n]
    if not names:
        raise ValueError("git ls-files returned no tracked files; refusing to "
                         "scan nothing and pass")
    return names


def _expected_pin(root):
    path = root / SIGNOFF
    if not path.is_file():
        raise ValueError(f"{SIGNOFF}: missing; the version CI installs is "
                         f"undefined")
    found = _PIN.findall(path.read_text())
    if not found:
        raise ValueError(f"{SIGNOFF}: no 'pip install klayout-tools==' line; "
                         f"the version CI installs is undefined")
    if len(found) > 1:
        raise ValueError(f"{SIGNOFF}: {len(found)} 'pip install "
                         f"klayout-tools==' lines; the version CI installs is "
                         f"ambiguous")
    return found[0]


def _audit(root=ROOT):
    """(pin, files scanned, sites checked, problems).

    Every mismatching site is reported, not just the first: a pin bump that
    missed one copy of the runbook command must list every remaining stale
    literal in a single run.
    """
    pin = _expected_pin(root)
    problems, scanned, sites = [], 0, 0
    for rel in _tracked_files(root):
        if _excluded(rel):
            continue
        try:
            lines = (root / rel).read_text().splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or binary: no literal to check there
        scanned += 1
        for lineno, line in enumerate(lines, 1):
            for m in _SITE.finditer(line):
                sites += 1
                if m.group(1) != pin:
                    problems.append(
                        f"{rel}:{lineno}: klayout-tools=={m.group(1)} but "
                        f"{SIGNOFF} installs {pin}")
    return pin, scanned, sites, problems


def check(root=ROOT):
    """Problems with the pin literals, as messages; empty means they all match."""
    return _audit(root)[3]


def main(argv):
    for a in argv:
        if a == "--check":
            continue
        return _usage(f"unknown option {a}" if a.startswith("-")
                      else f"unexpected argument {a!r}")
    try:
        pin, scanned, sites, problems = _audit()
    except ValueError as e:
        print(f"ERROR: {e.args[0]}", file=sys.stderr)
        return 1
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"tool-pins OK: klayout-tools=={pin}: {sites} sites in {scanned} "
          f"tracked files, all match")
    return 0


def _usage(msg):
    print(f"ERROR: {msg}\n"
          f"usage: {Path(__file__).name} --check",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
