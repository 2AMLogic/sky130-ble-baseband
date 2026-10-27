"""Shared stimulus driver for the RX replay benches (decision 0007).

The LE 1M and O-QPSK RX benches drive the same interface (rx_valid/rx_i/rx_q/
rx_sat strobes at nominally one per 4 clk with +/-1 clk jitter, then rx_flush)
and collect the same ev_* trace tap. Keeping the driver in one place means a
jitter or flush timing fix cannot drift between the two benches. The jitter
RNG call order is part of the stimulus: do not reorder it.
"""

import random

from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge

GAP = 4           # nominal clk per sample (32 MHz clk, 8 Msps)
DRAIN = 40        # clk after the last strobe before rx_flush (pipeline is 16 / 18)
SETTLE = 600      # clk after rx_flush for the engine to finish and emit


class RxHarness:
    """`kind` maps ev_kind codes to trace field names. Subclasses add their own
    monitor taps (`on_cycle`) and input defaults (`reset_inputs`)."""

    def __init__(self, dut, kind):
        self.dut = dut
        self.kind = kind
        self.events = []
        self.done_pulses = 0
        self.running = True

    def on_cycle(self):
        """Extra per-clock sampling, called in the ReadOnly phase of each rising edge."""

    def reset_inputs(self):
        """Extra input defaults, driven before rst_n is asserted."""

    async def monitor(self):
        d = self.dut
        while self.running:
            await RisingEdge(d.clk)
            await ReadOnly()
            if int(d.ev_valid.value):
                self.events.append((int(d.ev_index.value), self.kind[int(d.ev_kind.value)],
                                    int(d.ev_value.value)))
            if int(d.pkt_done.value):
                self.done_pulses += 1
            self.on_cycle()

    async def reset(self):
        d = self.dut
        d.rx_valid.value = 0
        d.rx_i.value = 0
        d.rx_q.value = 0
        d.rx_sat.value = 0
        d.rx_flush.value = 0
        d.agc_settled.value = 1
        self.reset_inputs()
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
