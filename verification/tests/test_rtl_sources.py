"""Negative and positive controls for verification/rtl_sources.py (issue #147).

Rows 1-18 of the issue's rejection-path table, each asserted with its exit
code (CLI) or exception type (library) and a distinguishing message fragment:

- rows 1-11: `_parse()` ValueErrors (marker form, argument counts, duplicates,
  ordering)
- rows 12-13: `check()`'s completeness errors (declared-but-missing,
  on-disk-but-undeclared), driven through `--check` (exit 1) and the library
  surface
- row 14: `block_sources()` KeyError on an unknown block name, exit 1 at the CLI
- rows 15-18: the four `_usage()` errors, exit 2

Row 19 (run_mac.py's missing-bench-parameter SystemExit) is out of scope: it
lives in verification/mac/run_mac.py, not in the file-list parser this module
tests.

Positive controls: `--all` reproduces rtl/baseband.f's non-comment lines in
order, a plain `# comment` line is ignored, `--out` writes the generated
header and creates missing parent directories, `--modules <block>` returns one
module name per file, and empty / comment-only list files parse to nothing.

CLI cases run a COPY of the script in a tmp_path fixture tree: LIST is bound
from Path(__file__).resolve().parents[1], and resolve() follows a symlink
back to the real repo's rtl/baseband.f, so a symlinked script would read the
repo list instead of the fixture.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rtl_sources  # noqa: E402

SCRIPT = Path(rtl_sources.__file__).resolve()
REPO_ROOT = SCRIPT.parent.parent
LIST_FILE = REPO_ROOT / "rtl" / "baseband.f"

# (row, list text, fragment of the ValueError message that identifies the path)
PARSE_REJECTIONS = [
    (1, "  # block: blk\n",
     "must start at column 0 and read exactly '# block: <argument>...'; "
     "got '  # block: blk'"),
    (2, "#block: blk\n",
     "must start at column 0 and read exactly '# block: <argument>...'; "
     "got '#block: blk'"),
    (3, "# block: blk extra\n",
     "'# block:' takes one block name, got ['blk', 'extra']"),
    (4, "# block: \n",
     "'# block:' takes one block name, got []"),
    (5, "# block: blk\n# block: blk\n",
     "block 'blk' is declared more than once"),
    (6, "# reuse: rtl/a.v\n",
     "'# reuse:' outside any '# block:' section"),
    (7, "# block: blk\n# reuse: \n",
     "'# reuse:' needs at least one path"),
    (8, "# block: blk\n# reuse: rtl/a.v\n",
     "'# reuse: rtl/a.v' is not declared earlier in this file"),
    (9, "# block: blk\nrtl/a.v\n# reuse: rtl/a.v\n",
     "'rtl/a.v' is already in block 'blk'"),
    (10, "rtl/a.v\n",
     "appears before any '# block:' marker"),
    (11, "# block: blk\nrtl/a.v\nrtl/a.v\n",
     "'rtl/a.v' is listed more than once"),
]


def write_list(tmp_path, text):
    lst = tmp_path / "rtl" / "baseband.f"
    lst.parent.mkdir(parents=True, exist_ok=True)
    lst.write_text(text)
    return lst


def make_tree(tmp_path, list_text, files=("rtl/a.v", "rtl/b.v")):
    """A fixture tree with a copy of the parser: <tmp>/verification/ and
    <tmp>/rtl/ with dummy .v files. Returns the copied script's path."""
    (tmp_path / "verification").mkdir(exist_ok=True)
    script = tmp_path / "verification" / "rtl_sources.py"
    shutil.copy(SCRIPT, script)
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("module dummy;\nendmodule\n")
    write_list(tmp_path, list_text)
    return script


def run(script, *argv):
    return subprocess.run([sys.executable, str(script), *argv],
                          capture_output=True, text=True, timeout=60)


@pytest.mark.parametrize("row,text,fragment", PARSE_REJECTIONS,
                         ids=[f"row{r}" for r, _, _ in PARSE_REJECTIONS])
def test_parse_rejections(tmp_path, row, text, fragment):
    with pytest.raises(ValueError, match=re.escape(fragment)):
        rtl_sources._parse(write_list(tmp_path, text))


def test_row12_and_13_check_returns_problem_messages(tmp_path):
    lst = write_list(tmp_path, "# block: blk\nrtl/a.v\nrtl/ghost.v\n")
    (tmp_path / "rtl" / "b.v").write_text("module dummy;\nendmodule\n")
    problems = rtl_sources.check(lst)
    assert any("rtl/ghost.v: declared in baseband.f but not on disk" in p
               for p in problems)
    assert any("rtl/b.v: on disk but no '# block:' section declares it" in p
               for p in problems)


def test_row14_block_sources_keyerror(tmp_path):
    lst = write_list(tmp_path, "# block: blk\nrtl/a.v\n")
    with pytest.raises(KeyError,
                       match=re.escape("no '# block: nope' section")):
        rtl_sources.block_sources("nope", lst)


def test_row12_check_declared_but_missing_exits_1(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\nrtl/ghost.v\n",
                       files=("rtl/a.v",))
    r = run(script, "--check")
    assert r.returncode == 1
    assert "rtl/ghost.v: declared in baseband.f but not on disk" in r.stderr
    assert "Traceback" not in r.stderr


def test_row13_check_on_disk_but_undeclared_exits_1(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\n")
    r = run(script, "--check")
    assert r.returncode == 1
    assert ("rtl/b.v: on disk but no '# block:' section declares it"
            in r.stderr)
    assert "Traceback" not in r.stderr


def test_row14_unknown_block_name_exits_1(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\n")
    r = run(script, "nope")
    assert r.returncode == 1
    assert "ERROR: " in r.stderr
    assert "no '# block: nope' section" in r.stderr
    assert "Traceback" not in r.stderr


@pytest.mark.parametrize("argv,fragment", [
    (["--out"], "--out needs a path"),                         # row 15
    (["--bogus"], "unknown option --bogus"),                   # row 16
    ([], "expected exactly one block name"),                   # row 17, zero names
    (["blk", "extra"], "expected exactly one block name"),     # row 17, two names
    (["--modules", "--all"], "--modules takes a block name"),  # row 18
], ids=["row15", "row16", "row17-zero", "row17-two", "row18"])
def test_usage_errors_exit_2(tmp_path, argv, fragment):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\n")
    r = run(script, *argv)
    assert r.returncode == 2
    assert fragment in r.stderr
    assert "usage:" in r.stderr


def test_check_malformed_list_prints_error_not_traceback(tmp_path):
    script = make_tree(tmp_path, "  # block: blk\n")
    r = run(script, "--check")
    assert r.returncode != 0
    assert "Traceback" not in r.stdout
    assert "Traceback" not in r.stderr
    assert r.stderr.startswith("ERROR: ")
    assert "must start at column 0" in r.stderr


def test_check_ok(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\nrtl/b.v\n")
    r = run(script, "--check")
    assert r.returncode == 0
    assert "rtl-list OK: 2 files, all declared and present" in r.stdout


def test_all_reproduces_repo_list_in_order():
    expected = [l for l in LIST_FILE.read_text().splitlines()
                if l.strip() and not l.strip().startswith("#")]
    r = run(SCRIPT, "--all")
    assert r.returncode == 0
    assert r.stdout.splitlines() == expected


def test_plain_comment_ignored(tmp_path):
    lst = write_list(tmp_path, "# block: blk\n# an ordinary comment\nrtl/a.v\n")
    top, blocks = rtl_sources._parse(lst)
    assert top == ["rtl/a.v"]
    assert blocks == {"blk": ["rtl/a.v"]}


def test_out_writes_header_and_creates_parents(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\nrtl/b.v\n")
    out = tmp_path / "generated" / "deep" / "le1m_tx.f"
    r = run(script, "--out", str(out), "blk")
    assert r.returncode == 0
    lines = out.read_text().splitlines()
    assert lines[0].startswith("# Generated from rtl/baseband.f ")
    assert lines[0].endswith("Do not edit.")
    assert lines[1:] == ["rtl/a.v", "rtl/b.v"]


def test_modules_one_name_per_file(tmp_path):
    script = make_tree(tmp_path, "# block: blk\nrtl/a.v\nrtl/b.v\n")
    r = run(script, "--modules", "blk")
    assert r.returncode == 0
    assert r.stdout == "a\nb\n"


def test_empty_list_parses_to_nothing(tmp_path):
    assert rtl_sources._parse(write_list(tmp_path, "")) == ([], {})


def test_comment_only_list_parses_to_nothing(tmp_path):
    lst = write_list(tmp_path, "# just a comment\n")
    assert rtl_sources._parse(lst) == ([], {})
