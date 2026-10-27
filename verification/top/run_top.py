"""Build rtl/top (baseband_top with every sub-block) with Icarus and run test_top.py.

Usage: python verification/top/run_top.py <build_dir> [test_name ...]

TOP_NEGATIVE=1 perturbs one expected value of each test, so the run must fail
with an `expected=` message (the Makefile `test-top-negative` target inverts
the exit status). Exits non-zero if any cocotb test fails.
"""

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

# The file list is read from the one place lint and synthesis also use.
RTL = [ln.strip() for ln in (ROOT / "rtl" / "baseband.f").read_text().splitlines()
       if ln.strip() and not ln.startswith("#")]


def main(build_dir: str, names) -> int:
    runner = get_runner("icarus")
    build = Path(build_dir)
    runner.build(sources=[ROOT / f for f in RTL], hdl_toplevel="baseband_top", build_dir=build,
                 always=True, timescale=("1ns", "1ps"))
    results = runner.test(hdl_toplevel="baseband_top", test_module="test_top", test_dir=HERE,
                          build_dir=build, testcase=names or None)
    total, failed = get_results(results)
    print(f"cocotb baseband_top: {total} tests, {failed} failed")
    return 1 if failed or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
