"""cocotb replay of the TX cases through rtl/oqpsk/oqpsk_tx.v (decision 0007).

For each case the testbench loads the payload into an asynchronous-read
buffer, pulses tx_start, drives tx_tick at the interface rate (nominally one
per 4 clk, +/-1 clk jitter as the front-end spec allows), records every
tx_valid word and the tx_active level at each strobe index, writes them in the
trace format and compares them with the model trace *by sample index*, exactly.
The first mismatch fails the test with case, record group and field.

Index convention (sim/model/README.md, `le1m_tx` reading): index n is the
n-th tick; the word of tick n appears with tx_valid one clk later, and
tx_active is sampled in that same clk. It rises at index 0 and is still high
at index len(words) (the tick after the last word); it is low at len(words)+1.
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
sys.path[:0] = [str(ROOT / "sim" / "model"), str(HERE)]
import cases  # noqa: E402
import traces  # noqa: E402

GAP = 4           # nominal clk per word (32 MHz clk, 8 Msps)


class Bench:
    def __init__(self, dut, payload):
        self.dut = dut
        self.payload = payload
        self.words = []          # (tick index, signed value) of tx_valid strobes
        self.tick_prev = None    # tick index asserted in the previous cycle
        self.active = {}         # tick index -> tx_active sampled one clk after the tick
        self.ticks = 0
        self.done_pulses = 0
        self.rejects = 0
        self.valid_gaps = []     # clk between consecutive tx_valid strobes
        self.running = True

    async def monitor(self):
        d = self.dut
        last_valid_clk = None
        clk = 0
        while self.running:
            await RisingEdge(d.clk)
            await ReadOnly()
            clk += 1
            if int(d.tx_done.value):
                self.done_pulses += 1
            if int(d.tx_reject.value):
                self.rejects += 1
            # the tick asserted in the previous cycle shows up in this one
            if self.tick_prev is not None:
                n = self.tick_prev
                self.tick_prev = None
                self.active[n] = int(d.tx_active.value)
                if int(d.tx_valid.value):
                    v = int(d.tx_dev.value)
                    self.words.append((n, v - 256 if v >= 128 else v))
                    if last_valid_clk is not None:
                        self.valid_gaps.append(clk - last_valid_clk)
                    last_valid_clk = clk
                else:
                    assert int(d.tx_dev.value) == 0, "tx_dev must be 0 when tx_valid is low"

    async def reset(self):
        d = self.dut
        d.tx_start.value = 0
        d.tx_len.value = 0
        d.tx_tick.value = 0
        d.psdu_data.value = 0
        d.rst_n.value = 0
        await ClockCycles(d.clk, 4)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 2)

    async def start(self, length):
        d = self.dut
        await FallingEdge(d.clk)
        d.tx_len.value = length
        d.tx_start.value = 1
        await FallingEdge(d.clk)
        d.tx_start.value = 0
        d.tx_len.value = 0

    async def drive_ticks(self, count, jitter_seed):
        """One tx_tick per word-slot on a 4-clk grid with +/-1 clk jitter."""
        d = self.dut
        rng = random.Random(jitter_seed)
        await FallingEdge(d.clk)
        clk = 0
        for n in range(count):
            due = GAP * n + rng.choice((-1, 0, 0, 1)) + GAP
            due = max(due, clk)
            while clk < due:
                d.tx_tick.value = 0
                await FallingEdge(d.clk)
                clk += 1
            d.tx_tick.value = 1
            self.tick_prev = n
            self.ticks = n + 1
            await FallingEdge(d.clk)
            clk += 1
        d.tx_tick.value = 0
        await ClockCycles(d.clk, 3)


def compare(name, rtl_records, model_records, negative):
    traces.compare_by_index(name, rtl_records, model_records, flip=('txdev', 0x40) if negative else None)


def rtl_records(b, nwords):
    """Trace records from the observed words and the tx_active levels."""
    recs = [(n, "txdev", v & 0xFF) for n, v in b.words]
    last = nwords + 1
    # txact: value at the first index it is 1, and at the first index it is 0 again
    first_hi = next((n for n in sorted(b.active) if b.active[n]), None)
    if first_hi is not None:
        recs.append((first_hi, "txact", 1))
    first_lo = next((n for n in sorted(b.active) if n > (first_hi or 0) and not b.active[n]), None)
    if first_lo is not None:
        recs.append((first_lo, "txact", 0))
    return sorted(recs, key=lambda r: r[0]), last


def load_case(vec, name):
    return (Path(vec) / f"{name}.psdu").read_bytes(), traces.read_trace(Path(vec) / f"{name}.model.trace")


@cocotb.test()
async def replay_matches_model(dut):
    """Every case: the RTL words and tx_active edges equal the model trace by tick index."""
    vec = os.environ["OQPSK_VECTORS"]
    names = os.environ["OQPSK_CASES"].split(",")
    negative = os.environ.get("OQPSK_NEGATIVE") == "1"
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for n, name in enumerate(names):
        payload, model = load_case(vec, name)
        nwords = sum(1 for r in model if r[1] == "txdev")
        b = Bench(dut, payload)
        await b.reset()
        mon = cocotb.start_soon(b.monitor())
        feeder = cocotb.start_soon(feed_buffer(b))
        await b.start(len(payload))
        # the words, then two more ticks: the "last word + 1" sample and the falling edge
        await b.drive_ticks(nwords + 2, jitter_seed=2000 + n)
        b.running = False
        feeder.cancel()
        await RisingEdge(dut.clk)
        mon.cancel()
        recs, _ = rtl_records(b, nwords)
        out = Path(vec) / f"{name}.rtl.trace"
        traces.write_trace(out, recs)
        assert b.done_pulses == 1, f"{name}: tx_done pulses = {b.done_pulses}"
        assert b.rejects == 0, f"{name}: unexpected tx_reject"
        compare(name, traces.read_trace(out), model, negative)
        if name == "golden_payload18":
            # the committed golden trace, not only a regenerated model trace
            compare(name + " (committed golden)", traces.read_trace(out),
                    traces.read_trace(cases.GOLDEN_TX), negative)
        dut._log.info("%s: %d words match", name, nwords)


async def feed_buffer(b):
    """Asynchronous-read payload buffer: psdu_data follows psdu_idx."""
    d = b.dut
    while True:
        await ReadOnly()
        idx = int(d.psdu_idx.value)
        await FallingEdge(d.clk)
        d.psdu_data.value = b.payload[idx] if idx < len(b.payload) else 0xEE


@cocotb.test()
async def refuses_bad_start(dut):
    """A start with tx_len > 125, or while busy, is refused and sends nothing new."""
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    b = Bench(dut, bytes(range(10)))
    await b.reset()
    mon = cocotb.start_soon(b.monitor())
    feeder = cocotb.start_soon(feed_buffer(b))
    await b.start(126)
    await ClockCycles(dut.clk, 4)
    assert b.rejects == 1, f"tx_len 126: tx_reject pulses = {b.rejects}"
    assert not int(dut.tx_active.value)
    await b.start(10)                       # accepted
    await b.start(4)                        # busy: refused
    await ClockCycles(dut.clk, 4)
    assert b.rejects == 2, f"start while busy: tx_reject pulses = {b.rejects}"
    nwords = 4 * (32 * 2 * (6 + 12) + 1)
    await b.drive_ticks(nwords + 2, jitter_seed=7)
    b.running = False
    feeder.cancel()
    mon.cancel()
    assert len(b.words) == nwords, f"words {len(b.words)} != {nwords}"
