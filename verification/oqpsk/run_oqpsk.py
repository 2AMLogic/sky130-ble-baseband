"""Build rtl/oqpsk with Icarus and replay the shared stimulus through cocotb.

Usage: python verification/oqpsk/run_oqpsk.py <build_dir> [tx|rx] [case ...]

Generates the vectors (stimulus + model trace, see cases.py) under
<build_dir>/vectors, builds the RTL, and runs test_oqpsk_tx.py (top oqpsk_tx)
and test_oqpsk_rx.py (top oqpsk_rx) against them; `tx` or `rx` runs only that
half. Environment: OQPSK_NEGATIVE=1 perturbs one expected record so the replay
must fail (the Makefile `test-oqpsk-negative` target inverts the exit status).
Exits non-zero if any cocotb test fails.

The RX top reuses rtl/le1m_rx/le1m_rx_disc.v and le1m_rx_cordic.v unchanged
(the model shares le1m_rx.discriminate), so rtl/baseband.f's `# block: oqpsk_rx`
section reuses those two entries of the le1m_rx block.
"""

import os
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
import cases  # noqa: E402
from cocotb_run import run_cocotb, verdict  # noqa: E402
from rtl_sources import block_sources  # noqa: E402

TOPS = {
    "tx": ("oqpsk_tx", "test_oqpsk_tx", block_sources("oqpsk_tx")),
    "rx": ("oqpsk_rx", "test_oqpsk_rx", block_sources("oqpsk_rx")),
}


def run_one(kind, build_dir, names) -> int:
    top, module, sources = TOPS[kind]
    build = Path(build_dir) / kind
    vec = build / "vectors"
    manifest = cases.write_vectors(vec, kind, names or None)
    os.environ["OQPSK_VECTORS"] = str(vec)
    os.environ["OQPSK_CASES"] = ",".join(manifest)
    return verdict(*run_cocotb(top, module, HERE, build, sources))


def main(build_dir: str, args) -> int:
    kinds = [a for a in args if a in TOPS] or list(TOPS)
    names = [a for a in args if a not in TOPS]
    rc = 0
    for kind in kinds:
        rc |= run_one(kind, build_dir, [n for n in names if n in (cases.TX_CASES if kind == "tx" else cases.RX_CASES)])
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
