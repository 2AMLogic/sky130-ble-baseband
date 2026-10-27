"""Build rtl/host/ with Icarus and run the cocotb host-interface tests.

Usage: python verification/host/run_host.py <build_dir>

Two configurations are run: the ratified defaults (288-deep FIFOs, 32 clocks per
microsecond) and the 16 MHz fallback with a small odd FIFO depth to exercise
pointer wrap. HOST_NEGATIVE=1 flips one expectation so the run must fail.
Exits non-zero if any cocotb test fails.
"""

import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "rtl/host" / f for f in (
    "host_fifo.v", "host_desc_fifo.v", "host_irq.v", "host_timestamp.v",
    "host_regs.v", "host_top.v")]
CONFIGS = [
    {"FIFO_DEPTH": 288, "CLK_PER_US": 32},
    {"FIFO_DEPTH": 5, "CLK_PER_US": 16},
]


def main(build_dir: str) -> int:
    runner = get_runner("icarus")
    total = failed = 0
    for cfg in CONFIGS:
        tag = f"d{cfg['FIFO_DEPTH']}_c{cfg['CLK_PER_US']}"
        bdir = Path(build_dir) / tag
        runner.build(
            sources=SOURCES,
            hdl_toplevel="host_top",
            build_dir=bdir,
            always=True,
            parameters=cfg,
            timescale=("1ns", "1ps"),
        )
        os.environ["HOST_FIFO_DEPTH"] = str(cfg["FIFO_DEPTH"])
        os.environ["HOST_CLK_PER_US"] = str(cfg["CLK_PER_US"])
        results = runner.test(
            hdl_toplevel="host_top",
            test_module="test_host",
            test_dir=Path(__file__).resolve().parent,
            build_dir=bdir,
        )
        t, f = get_results(results)
        print(f"cocotb host [{tag}]: {t} tests, {f} failed")
        total += t
        failed += f
    return 1 if failed or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
