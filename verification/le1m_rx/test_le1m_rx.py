"""cocotb replay of the shared RX stimulus through rtl/le1m_rx (decision 0007).

For each case the testbench drives the stimulus file at the interface rate
(nominally one rx_valid per 4 clk, +/-1 clk jitter as the front-end spec
allows), collects the RTL's trace taps, writes them in the trace format, and
compares them with the model trace *by sample index*, exactly. The first
mismatch fails the test, reported with case, record number and field.

Two things are not compared, both stated in rtl/le1m_rx/le1m_rx.v: the `gain`
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
import cm_a  # noqa: E402
import le1m_tx  # noqa: E402
import packet  # noqa: E402
import traces  # noqa: E402

KIND = {1: "bit", 2: "sync", 3: "tbound", 4: "cfo", 5: "crc", 6: "rssi"}
NOT_COMPARED = {"gain"}
GAP = 4           # nominal clk per sample (32 MHz clk, 8 Msps)
DRAIN = 40        # clk after the last strobe before rx_flush (pipeline is 16)
SETTLE = 600      # clk after rx_flush for the engine to finish and emit


class Harness:
    def __init__(self, dut):
        self.dut = dut
        self.events = []
        self.done_pulses = 0
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

    async def reset(self):
        d = self.dut
        d.rx_valid.value = 0
        d.rx_i.value = 0
        d.rx_q.value = 0
        d.rx_sat.value = 0
        d.rx_flush.value = 0
        d.agc_settled.value = 1
        d.access_address.value = cm_a_aa()
        d.crc_init.value = 0x555555
        d.dewhiten_en.value = 0
        d.chan.value = 0
        d.rst_n.value = 0
        await ClockCycles(d.clk, 4)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 2)

    async def drive(self, iq, flags, jitter_seed):
        """One rx_valid strobe per sample on a 4-clk grid with +/-1 clk jitter."""
        d = self.dut
        rng = random.Random(jitter_seed)
        await FallingEdge(d.clk)
        clk = 0
        for n in range(len(iq)):
            due = GAP * n + rng.choice((-1, 0, 0, 1))
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


def cm_a_aa():
    return 0x8E89BED6


def compare(name, rtl_records, model_records, negative):
    traces.compare_by_index(name, rtl_records, model_records, ignore=NOT_COMPARED, flip=('bit', 1) if negative else None)


load_case = traces.load_rx_case


@cocotb.test()
async def replay_matches_model(dut):
    """Every case: RTL trace equals the model trace by sample index."""
    vec = os.environ["LE1M_RX_VECTORS"]
    names = os.environ["LE1M_RX_CASES"].split(",")
    negative = os.environ.get("LE1M_RX_NEGATIVE") == "1"
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for n, name in enumerate(names):
        iq, flags, model = load_case(vec, name)
        h = Harness(dut)
        await h.reset()
        mon = cocotb.start_soon(h.monitor())
        await h.drive(iq, flags, jitter_seed=1000 + n)
        await h.flush()
        h.running = False
        await RisingEdge(dut.clk)
        out = Path(vec) / f"{name}.rtl.trace"
        traces.write_trace(out, sorted(h.events, key=lambda r: r[0]))
        assert int(dut.lag_overrun.value) == 0, f"{name}: packet engine overran the history window"
        compare(name, traces.read_trace(out), model, negative)
        dut._log.info("%s: %d records match (%d samples)", name, len(h.events), len(iq))
        mon.cancel()


@cocotb.test()
async def dewhitening_recovers_the_pdu(dut):
    """With dewhiten_en the RTL recovers the unwhitened PDU + CRC from an on-air
    stream whitened per the TX model, and the CRC check passes. The model has no
    whitening, so this compares against the transmitted bits, not a model trace."""
    import numpy as np
    channel = 37
    rng = np.random.Generator(np.random.PCG64(77))
    payload = bytes(rng.integers(0, 256, 40, dtype=np.uint8).tolist())
    plain, npdu = packet.build_frame_bits(payload, header0=0x42)
    body = plain[40:]
    on_air = plain[:40] + le1m_tx.whiten(body, channel)
    out = cm_a.generate_packet(on_air, cm_a.CmAParams(ebn0_db=18.0), rng)

    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    results = {}
    for enabled in (True, False):
        h = Harness(dut)
        await h.reset()
        dut.dewhiten_en.value = int(enabled)
        dut.chan.value = channel
        mon = cocotb.start_soon(h.monitor())
        await h.drive(out.iq, out.flags, jitter_seed=5)
        await h.flush()
        h.running = False
        await RisingEdge(dut.clk)
        mon.cancel()
        bits = [v for _, f, v in sorted(h.events, key=lambda r: r[0]) if f == "bit"]
        crc = [v for _, f, v in h.events if f == "crc"]
        results[enabled] = (bits, crc)
    bits, crc = results[True]
    assert bits == body, "de-whitened bits differ from the transmitted PDU + CRC"
    assert crc == [1], f"CRC check after de-whitening: {crc}"
    raw_bits, raw_crc = results[False]
    assert raw_bits != body and raw_crc != [1], "without de-whitening the whitened packet must not pass"
