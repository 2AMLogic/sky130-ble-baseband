"""Build rtl/smoke/lfsr8.v with Icarus and run the cocotb smoke test.

Usage: python verification/smoke/run_smoke.py <build_dir>
Exits non-zero if any cocotb test fails.
"""

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]


def main(build_dir: str) -> int:
    runner = get_runner("icarus")
    runner.build(
        sources=[ROOT / "rtl/smoke/lfsr8.v"],
        hdl_toplevel="lfsr8",
        build_dir=build_dir,
        always=True,
        timescale=("1ns", "1ps"),
    )
    results = runner.test(
        hdl_toplevel="lfsr8",
        test_module="test_lfsr8",
        test_dir=Path(__file__).resolve().parent,
        build_dir=build_dir,
    )
    total, failed = get_results(results)
    print(f"cocotb smoke: {total} tests, {failed} failed")
    return 1 if failed or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
