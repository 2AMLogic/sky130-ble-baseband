"""cocotb entry for the klt functional-verification oqpsk_rx run (issue #202).

The pre-step of `verification/oqpsk/run_oqpsk.py <build> rx`: regenerate the
RX vectors (including the committed golden case) from the case table, point
the bench at them through OQPSK_VECTORS / OQPSK_CASES, then re-export the
unmodified `verification/oqpsk/test_oqpsk_rx.py` suite. Environment is set at
run time so no host path is echoed into committed evidence.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "oqpsk"

sys.path[:0] = [str(BENCH), str(HERE.parent)]
import cases  # noqa: E402

VEC = Path("vectors")
MANIFEST = cases.write_vectors(VEC, "rx", None)
os.environ["OQPSK_VECTORS"] = VEC.as_posix()
os.environ["OQPSK_CASES"] = ",".join(MANIFEST)

from test_oqpsk_rx import *  # noqa: E402,F401,F403
