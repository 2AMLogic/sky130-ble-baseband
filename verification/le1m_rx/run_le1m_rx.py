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


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import cases  # noqa: E402
from cocotb_run import run_cocotb, verdict  # noqa: E402

SOURCES = [ROOT / "rtl/le1m_rx" / f for f in (
    "le1m_rx_fir.v", "le1m_rx_disc.v", "le1m_rx_cordic.v", "le1m_rx_integ.v",
    "le1m_rx_sync.v", "le1m_rx_pkt.v", "le1m_rx.v")]


def main(build_dir: str, names) -> int:
    build = Path(build_dir)
    vec = build / "vectors"
    manifest = cases.write_vectors(vec, names or None)
    os.environ["LE1M_RX_VECTORS"] = str(vec)
    os.environ["LE1M_RX_CASES"] = ",".join(manifest)
    total, failed = run_cocotb("le1m_rx", "test_le1m_rx", HERE, build, SOURCES)
    return verdict(total, failed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
