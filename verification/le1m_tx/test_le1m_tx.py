"""cocotb replay of model-generated LE 1M TX traces against rtl/le1m_tx.

Per decision 0007 the Python model is not run in the simulator: run_le1m_tx.py
generates the expected trace files beforehand (the committed golden file for
the first case, `sim/model/le1m_tx.py --out` for the rest) and this test reads
them through the shared reader sim/model/traces.py, drives the RTL with the same
PDU, writes the RTL's own trace in the same format and compares by
(sample index, field). Equality is exact; the first mismatch is reported with
the file, record number and field.

Sample index is the 4-clock sample slot counted from the first tx_valid, which
equals the tx_valid strobe count for every txdev record. The model puts the
txact fall at index len(words) + 1: tx_active stays high one slot past the last
word, where there is no strobe, so only the slot count gives that index.

Setting LE1M_TX_NEGATIVE=1 corrupts one expected txdev value of the first
case so the test must fail (`make test-le1m-tx-negative` inverts the exit
status and checks for the 'tx trace mismatch' message).
"""

import json
import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim" / "model"))
import traces  # noqa: E402

CASES = json.loads(Path(os.environ["LE1M_TX_CASES"]).read_text())
OUT_DIR = Path(os.environ["LE1M_TX_OUT"])
NEGATIVE = os.environ.get("LE1M_TX_NEGATIVE") == "1"


def compare(expected_path, expected, got, corrupt=False):
    """Exact compare keyed by (index, field); report file, record number, field."""
    if corrupt:
        n = next(i for i, r in enumerate(expected) if r[1] == "txdev" and r[0] >= 100)
        i, f, v = expected[n]
        expected = expected[:n] + [(i, f, v ^ 0x01)] + expected[n + 1:]
    got_map = {}
    for idx, field, value in got:
        assert (idx, field) not in got_map, f"RTL trace has duplicate record index {idx} field {field}"
        got_map[(idx, field)] = value
    exp_keys = set()
    for n, (idx, field, value) in enumerate(expected, 1):
        exp_keys.add((idx, field))
        if (idx, field) not in got_map:
            raise AssertionError(
                f"tx trace mismatch: {expected_path} record {n} field {field} index {idx}: "
                f"RTL produced no such record (expected {value:x})")
        if got_map[(idx, field)] != value:
            raise AssertionError(
                f"tx trace mismatch: {expected_path} record {n} field {field} index {idx}: "
                f"RTL={got_map[(idx, field)]:x} expected={value:x}")
    extra = sorted(set(got_map) - exp_keys)
    if extra:
        raise AssertionError(
            f"tx trace mismatch: {expected_path}: RTL has {len(extra)} record(s) not in the "
            f"expected trace, first at index {extra[0][0]} field {extra[0][1]}")


async def reset(dut):
    dut.start.value = 0
    dut.pdu_valid.value = 0
    dut.pdu_data.value = 0
    dut.access_address.value = 0
    dut.channel.value = 0
    dut.crc_init.value = 0
    dut.pdu_len.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await FallingEdge(dut.clk)


def assert_idle(dut, where):
    assert int(dut.tx_dev.value) == 0, f"{where}: tx_dev not 0"
    assert int(dut.tx_valid.value) == 0, f"{where}: tx_valid not 0"
    assert int(dut.tx_active.value) == 0, f"{where}: tx_active not 0"
    assert int(dut.busy.value) == 0, f"{where}: busy not 0"


async def run_packet(dut, case):
    """Drive one packet and return the RTL trace records."""
    pdu = bytes.fromhex(case["pdu"])
    clock_started = Clock(dut.clk, 31250, unit="ps")  # 32 MHz
    cocotb.start_soon(clock_started.start())
    await reset(dut)
    for _ in range(8):
        assert_idle(dut, "after reset")
        await FallingEdge(dut.clk)

    # All sampling is at the falling edge, where every signal is stable.
    dut.access_address.value = case["aa"]
    dut.channel.value = case["channel"]
    dut.crc_init.value = case["crc_init"]
    dut.pdu_len.value = len(pdu)
    dut.start.value = 1
    await FallingEdge(dut.clk)
    dut.start.value = 0

    words = []          # tx_dev words, in order
    cycle = 0
    c0 = None           # cycle of the first tx_valid
    prev_valid = 0
    rise = fall = None  # (cycle) of tx_active edges
    prev_active = 0
    idx = 0             # PDU octets handed over
    limit = 4 * (8 * (8 + 32 + 8 * len(pdu) + 24) + 40) + 400
    while cycle < limit:
        # Octet source: present the next octet, it is taken at the next edge if ready.
        if idx < len(pdu):
            dut.pdu_valid.value = 1
            dut.pdu_data.value = pdu[idx]
            if int(dut.pdu_ready.value):
                idx += 1
        else:
            dut.pdu_valid.value = 0
        valid = int(dut.tx_valid.value)
        active = int(dut.tx_active.value)
        if valid:
            assert not prev_valid, f"tx_valid held for two cycles at cycle {cycle}"
            if c0 is None:
                c0 = cycle
            assert (cycle - c0) % 4 == 0, f"tx_valid off the 4-cycle grid at cycle {cycle}"
            assert (cycle - c0) // 4 == len(words), f"tx_valid strobe missing before cycle {cycle}"
            assert active, "tx_valid without tx_active"
            words.append(int(dut.tx_dev.value))
        if active and not prev_active:
            assert rise is None, "tx_active rose twice"
            rise = cycle
        if prev_active and not active:
            fall = cycle
            break
        if not active:
            assert int(dut.tx_dev.value) == 0, f"tx_dev not 0 while inactive at cycle {cycle}"
        prev_valid, prev_active = valid, active
        cycle += 1
        await FallingEdge(dut.clk)
    assert fall is not None, "tx_active never fell"
    assert rise == c0, "tx_active must rise with the first tx_valid"
    assert (fall - c0) % 4 == 0, "tx_active fall is off the sample grid"
    assert int(dut.underrun.value) == 0, "underrun flagged"
    for _ in range(40):
        await FallingEdge(dut.clk)
        assert_idle(dut, "after packet")

    recs = [(0, "txact", 1)]
    recs += [(i, "txdev", w) for i, w in enumerate(words)]
    recs.append(((fall - c0) // 4, "txact", 0))
    return recs


@cocotb.test()
@cocotb.parametrize(case=CASES)
async def replay(dut, case):
    got = await run_packet(dut, case)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    traces.write_trace(OUT_DIR / f"rtl_{case['name']}.trace", got)
    expected = traces.read_trace(case["trace"])
    first = case["name"] == CASES[0]["name"]
    compare(case["trace"], expected, got, corrupt=NEGATIVE and first)
    dut._log.info("%s: %d words match %s", case["name"], len(expected) - 2, case["trace"])
