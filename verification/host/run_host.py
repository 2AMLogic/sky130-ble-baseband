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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cocotb_run import run_cocotb, verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SOURCES = [ROOT / "rtl/host" / f for f in (
    "host_fifo.v", "host_desc_fifo.v", "host_irq.v", "host_timestamp.v",
    "host_regs.v", "host_top.v")]
CONFIGS = [
    {"FIFO_DEPTH": 288, "CLK_PER_US": 32},
    {"FIFO_DEPTH": 5, "CLK_PER_US": 16},
]


def main(build_dir: str) -> int:
    total = failed = 0
    for cfg in CONFIGS:
        tag = f"d{cfg['FIFO_DEPTH']}_c{cfg['CLK_PER_US']}"
        os.environ["HOST_FIFO_DEPTH"] = str(cfg["FIFO_DEPTH"])
        os.environ["HOST_CLK_PER_US"] = str(cfg["CLK_PER_US"])
        t, f = run_cocotb("host_top", "test_host", Path(__file__).resolve().parent,
                          Path(build_dir) / tag, SOURCES, label=f"host [{tag}]",
                          parameters=cfg)
        total += t
        failed += f
    return verdict(total, failed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
