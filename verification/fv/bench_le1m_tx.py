"""cocotb entry for the klt functional-verification le1m_tx run (issue #202).

The pre-step of `verification/le1m_tx/run_le1m_tx.py`: generate the expected
model traces with the reference model's own command line (`sim/model/
le1m_tx.py --out`, decision 0007 section 2 -- the model is never run inside
the simulator), write the case list the bench replays, point the bench at
both through LE1M_TX_CASES / LE1M_TX_OUT, then re-export the unmodified
`verification/le1m_tx/test_le1m_tx.py` suite. The case table (including the
seeded random PDUs and the committed golden trace) is read from the runner,
not duplicated here. Environment is set at run time so no host path is
echoed into committed evidence; the traces are a pure function of the case
table, so re-running reproduces them.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent / "le1m_tx"

sys.path[:0] = [str(BENCH), str(HERE.parent)]
import run_le1m_tx  # noqa: E402

# klt runs cocotb with cwd set to the run's output directory (-o), so relative
# paths land in that artifact directory and never echo a host path into
# cases.json or failure messages (test_le1m_tx interpolates case["trace"]).
GEN = Path("model_traces")
GEN.mkdir(parents=True, exist_ok=True)
OUT = []
for name, pdu, ch, aa, crc in run_le1m_tx.cases():
    if name == "golden_ch37":
        trace = GEN / run_le1m_tx.GOLDEN.name
        shutil.copyfile(run_le1m_tx.GOLDEN, trace)
    else:
        trace = GEN / f"model_{name}.trace"
        subprocess.run([sys.executable, str(run_le1m_tx.MODEL), "--pdu", pdu,
                        "--channel", str(ch), "--access-address", f"{aa:x}",
                        "--crc-init", f"{crc:x}", "--out", str(trace)],
                       check=True, stdout=subprocess.DEVNULL)
    OUT.append({"name": name, "pdu": pdu, "channel": ch, "aa": aa,
                "crc_init": crc, "trace": trace.as_posix()})

CASES_JSON = Path("cases.json")
CASES_JSON.write_text(json.dumps(OUT))
os.environ["LE1M_TX_CASES"] = CASES_JSON.as_posix()
os.environ["LE1M_TX_OUT"] = "rtl_traces"

from test_le1m_tx import *  # noqa: E402,F401,F403
