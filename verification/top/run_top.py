"""Build rtl/top (baseband_top with every sub-block) with Icarus and run test_top.py.

Usage: python verification/top/run_top.py <build_dir> [test_name ...]

TOP_NEGATIVE=1 perturbs one expected value of each test, so the run must fail
with an `expected=` message (the Makefile `test-top-negative` target inverts
the exit status). Exits non-zero if any cocotb test fails.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cocotb_run import run_cocotb, verdict  # noqa: E402

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# The file list is read from the one place lint and synthesis also use.
RTL = [ln.strip() for ln in (ROOT / "rtl" / "baseband.f").read_text().splitlines()
       if ln.strip() and not ln.startswith("#")]


def main(build_dir: str, names) -> int:
    return verdict(*run_cocotb("baseband_top", "test_top", HERE, build_dir,
                               [ROOT / f for f in RTL], testcase=names or None))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
