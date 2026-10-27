"""cocotb replay of the shared RX stimulus through rtl/oqpsk/oqpsk_rx.v (decision 0007).

For each case the testbench drives the stimulus file at the interface rate
(nominally one rx_valid per 4 clk, +/-1 clk jitter as the front-end spec
allows), collects the RTL's trace taps, writes them in the trace format, and
compares them with the model trace *by sample index*, exactly. The first
mismatch fails the test, reported with case, record group and field.

Two things are not compared, both stated in rtl/oqpsk/oqpsk_rx.v: the `gain`
records (an echo of the stimulus column; the model has no AGC policy and the
RTL's agc_gain is a constant), and the clock cycle of any event.
"""

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "sim" / "model"), str(ROOT / "sim" / "channel"), str(HERE), str(ROOT / "verification")]
import cases  # noqa: E402
import traces  # noqa: E402
from rx_common import GAP, RxHarness  # noqa: E402

KIND = {2: "sync", 3: "tbound", 5: "crc", 6: "rssi", 7: "octet"}
NOT_COMPARED = {"gain"}


class Harness(RxHarness):
    def __init__(self, dut):
        super().__init__(dut, KIND)
        self.rssi_pulses = []

    def on_cycle(self):
        if int(self.dut.rssi_valid.value):
            self.rssi_pulses.append(int(self.dut.rssi_lin.value))


def compare(name, rtl_records, model_records, negative):
    traces.compare_by_index(name, rtl_records, model_records, ignore=NOT_COMPARED, flip=('octet', 1) if negative else None)


load_case = traces.load_rx_case


async def run_case(dut, vec, name, jitter_seed, gap=GAP):
    iq, flags, model = load_case(vec, name)
    h = Harness(dut)
    await h.reset()
    mon = cocotb.start_soon(h.monitor())
    await h.drive(iq, flags, jitter_seed=jitter_seed, gap=gap)
    await h.flush()
    h.running = False
    await RisingEdge(dut.clk)
    mon.cancel()
    out = Path(vec) / f"{name}.rtl.trace"
    traces.write_trace(out, sorted(h.events, key=lambda r: r[0]))
    return h, traces.read_trace(out), model, len(iq)


@cocotb.test()
async def replay_matches_model(dut):
    """Every case: RTL trace equals the model trace by sample index."""
    vec = os.environ["OQPSK_VECTORS"]
    names = os.environ["OQPSK_CASES"].split(",")
    negative = os.environ.get("OQPSK_NEGATIVE") == "1"
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for n, name in enumerate(names):
        h, rtl, model, nsamples = await run_case(dut, vec, name, jitter_seed=1000 + n)
        compare(name, rtl, model, negative)
        synced = any(f == "sync" for _, f, _ in model)
        assert int(dut.pkt_synced.value) == int(synced), f"{name}: pkt_synced != model sync"
        assert h.done_pulses == 1, f"{name}: pkt_done pulses = {h.done_pulses}"
        crc = [v for _, f, v in model if f == "crc"]
        if crc:
            assert int(dut.pkt_crc_ok.value) == crc[0], f"{name}: pkt_crc_ok != model crc"
        rssi = [v for _, f, v in model if f == "rssi"]
        assert h.rssi_pulses == rssi, f"{name}: rssi_valid pulses {h.rssi_pulses} != model {rssi}"
        dut._log.info("%s: %d records match (%d samples)", name, len(h.events), nsamples)


@cocotb.test()
async def committed_golden_loopback(dut):
    """The committed golden RX trace (sim/model/golden), not only a regenerated one."""
    vec = os.environ["OQPSK_VECTORS"]
    if "golden_psdu20" not in os.environ["OQPSK_CASES"].split(","):
        return
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    _h, rtl, _model, _n = await run_case(dut, vec, "golden_psdu20", jitter_seed=77)
    compare("golden_psdu20 (committed golden)", rtl, traces.read_trace(cases.GOLDEN_RX), False)


@cocotb.test()
async def back_to_back_strobes(dut):
    """rx_valid on every clk (no minimum spacing, no back-pressure): same trace."""
    vec = os.environ["OQPSK_VECTORS"]
    names = [n for n in os.environ["OQPSK_CASES"].split(",") if n in ("loopback_psdu3", "psdu0")]
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for n, name in enumerate(names):
        _h, rtl, model, _n = await run_case(dut, vec, name, jitter_seed=5 + n, gap=1)
        compare(name + " (rx_valid every clk)", rtl, model, False)
