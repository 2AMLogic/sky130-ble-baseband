"""Negative and positive controls for verification/tool_pins.py (issue #171).

The issue's test-plan rows, each asserted with its exit code and a
distinguishing stdout/stderr fragment, with `"Traceback" not in stderr` on
every failure path:

- (a) a consistent tree passes with an OK summary naming the pin and counts
- (b) one drifted literal fails, naming file:line and both versions
- (c) two drifted literals both appear (guards against first-match-and-bail)
- (d) signoff.yml with no `pip install klayout-tools==` line fails naming that
  cause
- (e) signoff.yml with two such lines fails naming the ambiguity
- (f) unpinned mentions (`pip install klayout-tools`, `klayout-tools[yield]`,
  `klayout-tools@<sha>`) pass, including a tree with zero pinned sites
- (g) a drifted literal under each excluded path does not fail the check
- edge cases: paths resolve from the repo root, not the cwd; git unavailable
  and a repo with no tracked files both fail loudly instead of scanning
  nothing and passing vacuously

CLI cases run a COPY of the script in a tmp_path fixture tree with its own
`git init` (the scan enumerates `git ls-files` output from the repo root the
script resolves to), mirroring test_rtl_sources.py: LIST-style module paths
are bound from `Path(__file__).resolve()`, so a symlinked script would read
the real repo instead of the fixture.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tool_pins  # noqa: E402

SCRIPT = Path(tool_pins.__file__).resolve()

# The fixture's CI pin: exactly one `pip install klayout-tools==` line.
SIGNOFF_OK = ("name: signoff\njobs:\n  attest:\n    steps:\n"
              "      - run: pip install klayout-tools==0.8.0\n")

# A fixture runbook: one pinned `uvx` literal on line 1.
README_OK = 'uvx --from "klayout-tools==0.8.0" klt signoff --attest 9\n'


def make_tree(tmp_path, signoff_text, files, track=True):
    """A fixture tree with a copy of the checker, a signoff.yml and `files`
    ({repo-relative path: text}); `git init` + `git add -A` unless `track`
    is False. Returns the copied script's path."""
    (tmp_path / "verification").mkdir()
    script = tmp_path / "verification" / "tool_pins.py"
    shutil.copy(SCRIPT, script)
    signoff = tmp_path / ".github" / "workflows" / "signoff.yml"
    signoff.parent.mkdir(parents=True, exist_ok=True)
    signoff.write_text(signoff_text)
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    if track:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True,
                       timeout=60)
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True,
                       timeout=60)
    return script


def run(script, *argv, cwd=None, env=None):
    return subprocess.run([sys.executable, str(script), *argv],
                          capture_output=True, text=True, timeout=60,
                          cwd=cwd, env=env)


def test_a_consistent_tree_passes_with_ok_summary(tmp_path):
    script = make_tree(tmp_path, SIGNOFF_OK,
                       {"manifests/README.md": README_OK})
    r = run(script, "--check")
    assert r.returncode == 0
    # signoff.yml's own pin line is one of the sites: 2 sites, 3 files
    # (the copied checker itself is scanned too, and contributes none).
    assert ("tool-pins OK: klayout-tools==0.8.0: 2 sites in 3 tracked files, "
            "all match") in r.stdout
    assert r.stderr == ""


def test_b_one_drifted_literal_fails_naming_site_and_versions(tmp_path):
    drifted = 'uvx --from "klayout-tools==0.9.0" klt signoff --attest 9\n'
    script = make_tree(tmp_path, SIGNOFF_OK, {"manifests/README.md": drifted})
    r = run(script, "--check")
    assert r.returncode == 1
    assert ("manifests/README.md:1: klayout-tools==0.9.0 but "
            ".github/workflows/signoff.yml installs 0.8.0") in r.stderr
    assert "Traceback" not in r.stderr


def test_c_two_drifted_literals_both_named(tmp_path):
    files = {
        "manifests/README.md": 'uvx --from "klayout-tools==0.9.0" klt\n',
        "docs/runbook.md": 'uvx --from "klayout-tools==0.7.1" klt\n',
    }
    script = make_tree(tmp_path, SIGNOFF_OK, files)
    r = run(script, "--check")
    assert r.returncode == 1
    assert "manifests/README.md:1: klayout-tools==0.9.0" in r.stderr
    assert "docs/runbook.md:1: klayout-tools==0.7.1" in r.stderr
    assert "Traceback" not in r.stderr


def test_d_no_pin_line_in_signoff_fails_naming_cause(tmp_path):
    signoff = ("name: signoff\njobs:\n  attest:\n    steps:\n"
               "      - run: pip install klayout-tools\n")
    script = make_tree(tmp_path, signoff, {"manifests/README.md": README_OK})
    r = run(script, "--check")
    assert r.returncode == 1
    assert "no 'pip install klayout-tools==' line" in r.stderr
    assert "the version CI installs is undefined" in r.stderr
    assert "Traceback" not in r.stderr


def test_e_two_pin_lines_in_signoff_fail_naming_cause(tmp_path):
    signoff = ("name: signoff\njobs:\n  attest:\n    steps:\n"
               "      - run: pip install klayout-tools==0.8.0\n"
               "      - run: pip install klayout-tools==0.9.0\n")
    script = make_tree(tmp_path, signoff, {"manifests/README.md": README_OK})
    r = run(script, "--check")
    assert r.returncode == 1
    assert "2 'pip install klayout-tools==' lines" in r.stderr
    assert "the version CI installs is ambiguous" in r.stderr
    assert "Traceback" not in r.stderr


def test_f_unpinned_mentions_are_not_flagged(tmp_path):
    files = {
        "docs/notes.md": ("pip install klayout-tools\n"
                          "pip install 'klayout-tools[yield]'\n"
                          "see 2AMLogic/klayout-tools@e88f211\n"),
    }
    script = make_tree(tmp_path, SIGNOFF_OK, files)
    r = run(script, "--check")
    assert r.returncode == 0
    assert "tool-pins OK: klayout-tools==0.8.0: 1 sites in 3 tracked files" \
        in r.stdout
    assert r.stderr == ""


@pytest.mark.parametrize("rel", [
    "manifests/design-evidence-tiers.md",   # vendored upstream checklist
    "manifests/repo.signoff.json",          # generated, byte-compared record
    ".loom/scripts/probe.sh",               # installed Loom tooling
    ".claude/skills/repo/SKILL.md",         # installed repo-skills
    "verification/tests/test_tool_pins.py",  # this file: load-bearing drift fixtures
])
def test_g_drifted_literal_in_excluded_path_passes(tmp_path, rel):
    files = {
        "manifests/README.md": README_OK,
        rel: 'uvx --from "klayout-tools==9.9.9" klt\n',
    }
    script = make_tree(tmp_path, SIGNOFF_OK, files)
    r = run(script, "--check")
    assert r.returncode == 0
    assert "9.9.9" not in r.stdout
    assert r.stderr == ""


def test_paths_resolve_from_repo_root_not_cwd(tmp_path):
    script = make_tree(tmp_path, SIGNOFF_OK,
                       {"manifests/README.md": README_OK})
    r = run(script, "--check", cwd=tmp_path / "manifests")
    assert r.returncode == 0
    assert "tool-pins OK" in r.stdout


def test_git_unavailable_fails_loudly(tmp_path):
    script = make_tree(tmp_path, SIGNOFF_OK,
                       {"manifests/README.md": README_OK})
    # An empty PATH hides git from the checker; sys.executable is absolute, so
    # the interpreter itself still starts.
    r = run(script, "--check", env={"PATH": "", "HOME": str(tmp_path)})
    assert r.returncode == 1
    assert "git is unavailable" in r.stderr
    assert "scan nothing and pass" in r.stderr
    assert "Traceback" not in r.stderr


def test_no_tracked_files_fails_loudly(tmp_path):
    script = make_tree(tmp_path, SIGNOFF_OK,
                       {"manifests/README.md": README_OK}, track=False)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, timeout=60)
    r = run(script, "--check")
    assert r.returncode == 1
    assert "no tracked files" in r.stderr
    assert "Traceback" not in r.stderr


def test_library_check_returns_problem_strings(tmp_path):
    drifted = 'uvx --from "klayout-tools==0.9.0" klt\n'
    make_tree(tmp_path, SIGNOFF_OK, {"manifests/README.md": drifted})
    problems = tool_pins.check(tmp_path)
    assert problems == [
        "manifests/README.md:1: klayout-tools==0.9.0 but "
        ".github/workflows/signoff.yml installs 0.8.0"]


def test_repo_pins_match_ci():
    r = run(SCRIPT, "--check")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("tool-pins OK: ")
