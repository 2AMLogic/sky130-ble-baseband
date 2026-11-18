"""Build rtl/top (baseband_top with every sub-block) with Icarus and run test_latency.py.

Usage: python verification/top/run_latency.py <build_dir> [test_name ...]

Measures L_rx / L_tx / L_dig and their spread over the shared stimulus at
32 MHz and checks them against the spec/timing-and-area.md section 3 bounds
(issue #122). The measured numbers are written to <build_dir>/latency.json;
the committed evidence is verification/top/latency_record.md.

LATENCY_NEGATIVE=1 tightens one bound below the measurement, so the run must
fail with an `expected=` message (the Makefile `test-top-latency-negative`
target inverts the exit status). Exits non-zero if any cocotb test fails.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cocotb_run import run_cocotb, verdict  # noqa: E402
from rtl_sources import rtl_sources  # noqa: E402

HERE = Path(__file__).resolve().parent

# The file list is read from the one place lint, synthesis and every other
# bench also use, through the one parser (verification/rtl_sources.py).
RTL = rtl_sources()


def main(build_dir: str, names) -> int:
    os.environ["LATENCY_JSON"] = str(Path(build_dir) / "latency.json")
    return verdict(*run_cocotb("baseband_top", "test_latency", HERE, build_dir,
                               RTL, testcase=names or None))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2:]))
