"""CI workflow YAML parse-validity check (issue #172).

A workflow file that does not parse silently drops its required context
(signoff.yml at 23a387e5 left `signoff` never reporting, stalling every PR)
with no error anywhere. This module is the check: every `.yml`/`.yaml` under
`.github/` must `yaml.safe_load`, and the sweep itself must not pass vacuously.

Test-plan rows, from the issue:

- positive sweep: `check_github_yaml(REPO_ROOT)` parses all six current
  `.github` YAML files and asserts the discovered set is non-empty AND
  includes at least one file under `.github/workflows/` (a zero-match glob is
  the same bug class as the defect this issue reports)
- negative control: the committed fixture
  `fixtures/unparseable_workflow.yml` reproduces the real shape (a dedented
  inline `python3 -c` script inside a `run: |` block, whose column-0
  continuation lines end the block scalar) and MUST fail to parse — the test
  fails if the fixture parses or is missing
- control-of-the-control: the same code path parses a validated counterpart
  of the fixture, so the negative control's outcome is driven by parseability,
  not by an unrelated property of the fixture's path
- a parse failure is named: path + parser error text in the assertion
- edge cases: (a) a zero-match glob fails instead of passing vacuously;
  (b) `.yaml` files are covered as well as `.yml`; (c) an empty YAML file
  (`safe_load` -> None) parses fine; (d) the fixture itself is not matched by
  the production glob (it lives outside `.github/` for exactly that reason)

Pure Python: no simulator and no PDK. Carried by `make parser-test`
(verification/tests), which flow.yml's test-lint job already runs — so the
check inherits a required, PR-triggered context with no flow.yml change.
Parse validity only: no actionlint, expression or Actions-schema validation
(issue #172 Out of Scope).
"""

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "unparseable_workflow.yml"


def discover_github_yaml(root):
    """Every .yml/.yaml under root/.github, sorted (Path objects)."""
    github = root / ".github"
    if not github.is_dir():
        return []
    return sorted(p for p in github.rglob("*") if p.suffix in (".yml", ".yaml"))


def parse_github_yaml(path):
    """safe_load one YAML file; AssertionError naming path + parser error."""
    try:
        with open(path, encoding="utf-8") as stream:
            yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise AssertionError(f"{path}: not parseable YAML: {exc}") from exc


def check_github_yaml(root):
    """The production check: parse every .github YAML under root.

    Fails on a zero-match glob, on a tree whose discovered set contains no
    file under .github/workflows/, or on any unparseable file (named).
    Returns the discovered file list.
    """
    files = discover_github_yaml(root)
    assert files, f"no .yml/.yaml found under {root}/.github — glob matched nothing, check would pass vacuously"
    workflows = [p for p in files if p.parent.name == "workflows"]
    assert workflows, (
        f"no workflow YAML under {root}/.github/workflows — "
        f"discovered only: {[str(p.relative_to(root)) for p in files]}"
    )
    for path in files:
        parse_github_yaml(path)
    return files


def make_tree(tmp_path, files):
    """A fixture tree: {repo-relative path: text}, rooted at tmp_path."""
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_github_yaml_parses():
    """Positive sweep over the real repo: all .github YAML parses."""
    files = check_github_yaml(REPO_ROOT)
    names = [str(p.relative_to(REPO_ROOT)) for p in files]
    assert ".github/workflows/signoff.yml" in names, (
        f"the motivating file is no longer discovered; found: {names}"
    )


def test_zero_match_glob_fails(tmp_path):
    """Edge (a): an empty .github/ tree must fail, not pass vacuously."""
    root = make_tree(tmp_path, {".github/PULL_REQUEST_TEMPLATE.md": "x\n"})
    with pytest.raises(AssertionError, match="vacuously"):
        check_github_yaml(root)


def test_parse_error_names_path_and_error(tmp_path):
    """A parse failure names the offending path and the parser error."""
    root = make_tree(tmp_path, {".github/workflows/broken.yml": FIXTURE.read_text()})
    with pytest.raises(AssertionError) as excinfo:
        check_github_yaml(root)
    message = str(excinfo.value)
    assert "broken.yml" in message
    assert "could not find expected ':'" in message


def test_yaml_extension_covered(tmp_path):
    """Edge (b): .yaml files are checked as well as .yml."""
    root = make_tree(tmp_path, {".github/workflows/broken.yaml": FIXTURE.read_text()})
    with pytest.raises(AssertionError, match=r"broken\.yaml"):
        check_github_yaml(root)


def test_empty_yaml_file_parses(tmp_path):
    """Edge (c): an empty YAML file (safe_load -> None) parses fine."""
    root = make_tree(
        tmp_path,
        {
            ".github/workflows/empty.yml": "",
            ".github/workflows/comment-only.yml": "# nothing here\n",
        },
    )
    files = check_github_yaml(root)
    assert {p.name for p in files} == {"empty.yml", "comment-only.yml"}


def test_negative_control_fixture_is_unparseable():
    """The committed fixture must fail to parse; the control fails if it
    parses or is missing."""
    assert FIXTURE.is_file(), f"negative-control fixture missing: {FIXTURE}"
    with pytest.raises(AssertionError, match="not parseable YAML"):
        parse_github_yaml(FIXTURE)


def test_negative_control_is_content_driven(tmp_path):
    """Control-of-the-control: the same code path accepts a validated
    counterpart of the fixture (dedented lines re-indented into the block
    scalar), so the negative control fails on parseability alone."""
    valid_counterpart = (
        "name: signoff\n"
        "on: pull_request\n"
        "jobs:\n"
        "  attest:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: Attest\n"
        "        run: |\n"
        "          set -uo pipefail\n"
        "          for f in $(python3 -c '\n"
        "            import json\n"
        "            m = json.load(open(\"manifests/block.json\"))\n"
        "            for _, e in sorted(m.get(\"evidence\", {}).items()):\n"
        "                print(e[\"file\"])\n"
        "          '); do\n"
        "            echo \"$f\"\n"
        "          done\n"
    )
    root = make_tree(tmp_path, {".github/workflows/valid.yml": valid_counterpart})
    files = check_github_yaml(root)
    assert files[0].name == "valid.yml"


def test_fixture_not_matched_by_production_glob():
    """Edge (d): the fixture lives outside .github/, so the production glob
    never picks it up and GitHub never tries to run it."""
    github = REPO_ROOT / ".github"
    assert github not in FIXTURE.parents, (
        "the unparseable fixture moved under .github/ — GitHub would ingest it "
        "and the production glob would fail the repo on it"
    )
    assert FIXTURE not in discover_github_yaml(REPO_ROOT)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__]))
