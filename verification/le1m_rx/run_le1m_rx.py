"""Build rtl/le1m_rx with Icarus and replay the shared stimulus through cocotb.

Usage: python verification/le1m_rx/run_le1m_rx.py <build_dir> [case ...]

Generates the vectors (stimulus + model trace, see cases.py) under
<build_dir>/vectors, builds the RTL, and runs test_le1m_rx.py against them.
Environment: LE1M_RX_NEGATIVE=1 perturbs one expected record so the replay
must fail (the Makefile `test-negative` target inverts the exit status).
Exits non-zero if any cocotb test fails.
"""

import os
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import cases  # noqa: E402

SOURCES = [ROOT / "rtl/le1m_rx" / f for f in (
    "le1m_rx_fir.v", "le1m_rx_disc.v", "le1m_rx_cordic.v", "le1m_rx_integ.v",
    "le1m_rx_sync.v", "le1m_rx_pkt.v", "le1m_rx.v")]


def main(build_dir: str, names) -> int:
    build = Path(build_dir)
    vec = build / "vectors"
    manifest = cases.write_vectors(vec, names or None)
    os.environ["LE1M_RX_VECTORS"] = str(vec)
    os.environ["LE1M_RX_CASES"] = ",".join(manifest)
    runner = get_runner("icarus")
    runner.build(
        sources=SOURCES,
        hdl_toplevel="le1m_rx",
        build_dir=build,
        always=True,
        timescale=("1ns", "1ps"),
    )
    results = runner.test(
        hdl_toplevel="le1m_rx",
        test_module="test_le1m_rx",
        test_dir=HERE,
        build_dir=build,
    )
    total, failed = get_results(results)
    print(f"cocotb le1m_rx: {total} tests, {failed} failed")
    return 1 if failed or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
