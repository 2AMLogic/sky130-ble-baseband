"""cocotb entry for the klt functional-verification le1m_rx run (issue #202).

Performs exactly the pre-step `verification/le1m_rx/run_le1m_rx.py` performs
before it hands over to the simulator -- regenerate the shared-stimulus
vectors from the case table into the run's scratch directory and point the
bench at them through LE1M_RX_VECTORS / LE1M_RX_CASES -- and then re-exports
the unmodified `verification/le1m_rx/test_le1m_rx.py` test suite. The
environment is set at run time (never through the request's `env`, which klt
echoes verbatim into the report), so no host path lands in committed
evidence. The vectors are a pure function of the case table, so re-running
reproduces them.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "le1m_rx"

sys.path[:0] = [str(BENCH), str(HERE.parent)]
import cases  # noqa: E402

VEC = Path("vectors")
MANIFEST = cases.write_vectors(VEC, None)
os.environ["LE1M_RX_VECTORS"] = VEC.as_posix()
os.environ["LE1M_RX_CASES"] = ",".join(MANIFEST)

from test_le1m_rx import *  # noqa: E402,F401,F403
