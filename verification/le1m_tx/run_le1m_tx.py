"""Build rtl/le1m_tx with Icarus, generate model traces, run the cocotb replay.

Usage: python verification/le1m_tx/run_le1m_tx.py <build_dir>
LE1M_TX_NEGATIVE=1 corrupts one expected record (see test_le1m_tx.py).
Exits non-zero if any cocotb test fails.

The expected traces are written by the reference model's command line
(sim/model/le1m_tx.py --out) before simulation starts; the model is not run
inside the simulator (decision 0007 section 2). The first case replays the
committed golden trace.
"""

import json
import os
import random
import subprocess
import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "sim" / "model" / "le1m_tx.py"
GOLDEN = ROOT / "sim" / "model" / "golden" / "tx_adv_ch37.trace"
GOLDEN_PDU = "4209010203040506020106"  # sim/model/README.md
ADV_AA = 0x8E89BED6
ADV_CRC = 0x555555

SOURCES = [ROOT / "rtl/le1m_tx" / f for f in (
    "le1m_whiten.v", "le1m_crc24.v", "le1m_frame.v", "le1m_gauss.v", "le1m_tx.v")]


def cases():
    rnd = random.Random(48)
    rand_pdu = lambda n: bytes(rnd.randrange(256) for _ in range(n)).hex()
    # (name, pdu hex, channel, access address, crc init); the first is the golden trace
    return [
        ("golden_ch37", GOLDEN_PDU, 37, ADV_AA, ADV_CRC),
        ("adv_ch38", "4210" + rand_pdu(16), 38, ADV_AA, ADV_CRC),
        ("adv_ch39", "4219" + rand_pdu(25), 39, ADV_AA, ADV_CRC),
        ("header_only", "4000", 37, ADV_AA, ADV_CRC),
        ("empty_pdu", "", 38, ADV_AA, ADV_CRC),
        ("max_len_257", rand_pdu(257), 39, ADV_AA, ADV_CRC),
        ("data_ch12_aa_lsb0", "0206" + rand_pdu(6), 12, 0x12345678, 0xABCDEF),
        ("data_ch0_aa_lsb1", "0205" + rand_pdu(5), 0, 0x12345679, 0x000001),
    ]


def main(build_dir: str) -> int:
    build = Path(build_dir).resolve()
    gen = build / "model_traces"
    gen.mkdir(parents=True, exist_ok=True)
    out = []
    for name, pdu, ch, aa, crc in cases():
        if name == "golden_ch37":
            trace = GOLDEN
        else:
            trace = gen / f"model_{name}.trace"
            subprocess.run([sys.executable, str(MODEL), "--pdu", pdu, "--channel", str(ch),
                            "--access-address", f"{aa:x}", "--crc-init", f"{crc:x}",
                            "--out", str(trace)], check=True, stdout=subprocess.DEVNULL)
        out.append({"name": name, "pdu": pdu, "channel": ch, "aa": aa, "crc_init": crc,
                    "trace": str(trace)})
    cases_json = build / "cases.json"
    cases_json.write_text(json.dumps(out))
    os.environ["LE1M_TX_CASES"] = str(cases_json)
    os.environ["LE1M_TX_OUT"] = str(build / "rtl_traces")

    runner = get_runner("icarus")
    runner.build(
        sources=SOURCES,
        hdl_toplevel="le1m_tx",
        build_dir=build / "sim_build",
        always=True,
        timescale=("1ns", "1ps"),
    )
    results = runner.test(
        hdl_toplevel="le1m_tx",
        test_module="test_le1m_tx",
        test_dir=Path(__file__).resolve().parent,
        build_dir=build / "sim_build",
    )
    total, failed = get_results(results)
    print(f"cocotb le1m_tx: {total} tests, {failed} failed")
    return 1 if failed or total == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
