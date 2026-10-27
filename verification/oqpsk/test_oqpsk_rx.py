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
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "sim" / "model"), str(ROOT / "sim" / "channel"), str(HERE)]
import cases  # noqa: E402
import cm_a  # noqa: E402
import traces  # noqa: E402

KIND = {2: "sync", 3: "tbound", 5: "crc", 6: "rssi", 7: "octet"}
NOT_COMPARED = {"gain"}
GAP = 4           # nominal clk per sample (32 MHz clk, 8 Msps)
DRAIN = 40        # clk after the last strobe before rx_flush (pipeline is 18)
SETTLE = 600      # clk after rx_flush for the engine to finish and emit


class Harness:
    def __init__(self, dut):
        self.dut = dut
        self.events = []
        self.done_pulses = 0
        self.rssi_pulses = []
        self.running = True

    async def monitor(self):
        d = self.dut
        while self.running:
            await RisingEdge(d.clk)
            await ReadOnly()
            if int(d.ev_valid.value):
                self.events.append((int(d.ev_index.value), KIND[int(d.ev_kind.value)],
                                    int(d.ev_value.value)))
            if int(d.pkt_done.value):
                self.done_pulses += 1
            if int(d.rssi_valid.value):
                self.rssi_pulses.append(int(d.rssi_lin.value))

    async def reset(self):
        d = self.dut
        d.rx_valid.value = 0
        d.rx_i.value = 0
        d.rx_q.value = 0
        d.rx_sat.value = 0
        d.rx_flush.value = 0
        d.agc_settled.value = 1
        d.rst_n.value = 0
        await ClockCycles(d.clk, 4)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 2)

    async def drive(self, iq, flags, jitter_seed, gap=GAP):
        """One rx_valid strobe per sample on a `gap`-clk grid, +/-1 clk jitter when gap > 1."""
        d = self.dut
        rng = random.Random(jitter_seed)
        await FallingEdge(d.clk)
        clk = 0
        for n in range(len(iq)):
            due = gap * n + (rng.choice((-1, 0, 0, 1)) if gap > 1 else 0)
            due = max(due, clk)
            while clk < due:
                d.rx_valid.value = 0
                await FallingEdge(d.clk)
                clk += 1
            d.rx_valid.value = 1
            d.rx_i.value = int(iq[n][0])
            d.rx_q.value = int(iq[n][1])
            d.rx_sat.value = int(flags[n]) & 1
            await FallingEdge(d.clk)
            clk += 1
        d.rx_valid.value = 0

    async def flush(self):
        d = self.dut
        await ClockCycles(d.clk, DRAIN)
        await FallingEdge(d.clk)
        d.rx_flush.value = 1
        await FallingEdge(d.clk)
        d.rx_flush.value = 0
        await ClockCycles(d.clk, SETTLE)


def compare(name, rtl_records, model_records, negative):
    """Exact comparison by (sample index, field); order within a pair is kept."""
    want = [r for r in model_records if r[1] not in NOT_COMPARED]
    if negative and want:
        k = next((i for i, r in enumerate(want) if r[1] == "octet"), 0)
        idx, field, val = want[k]
        want[k] = (idx, field, val ^ 1)

    def group(records):
        g = {}
        for idx, field, val in records:
            g.setdefault((idx, field), []).append(val)
        return g

    gr, gw = group(rtl_records), group(want)
    keys = sorted(set(gr) | set(gw))
    for n, key in enumerate(keys):
        if gr.get(key) != gw.get(key):
            raise AssertionError(
                f"{name}: first mismatch at record group {n} (sample {key[0]}, field {key[1]}): "
                f"rtl={[f'{v:x}' for v in gr.get(key, [])]} "
                f"expected={[f'{v:x}' for v in gw.get(key, [])]} "
                f"(rtl {len(rtl_records)} records, model {len(want)})")
    assert len(rtl_records) == len(want), f"{name}: record count rtl={len(rtl_records)} expected={len(want)}"


def load_case(vec, name):
    iq, flags, _gain = cm_a.unpack_rx_records((Path(vec) / f"{name}.rx.bin").read_bytes())
    model = traces.read_trace(Path(vec) / f"{name}.model.trace")
    return iq, flags, model


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
