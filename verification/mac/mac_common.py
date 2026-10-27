"""Shared helpers for the lower-MAC benches (rtl/mac/).

All cycle counts are *simulated at RTL level, on cycle counts*. A count is
converted to time only with a named clock: MAC_CLK_MHZ=32 (target) or 16
(fallback). Budgets come from spec/decisions/0006-lower-mac-split.md and the
L_dig split from spec/timing-and-area.md section 3.

Cycle convention: `Cyc.step()` waits for a falling edge; `Cyc.n` then counts
the rising edges seen so far. A strobe driven after `step()` with `Cyc.n == k`
is sampled by the DUT on rising edge k+1 (its "sample edge"). An output that
is visible at a `step()` with `Cyc.n == m` became visible after edge m.
Latency = m - sample_edge, the N of mac_timer.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge

CLK_MHZ = int(os.environ.get("MAC_CLK_MHZ", "32"))
NEGATIVE = os.environ.get("MAC_NEGATIVE") == "1"

# 0006 deadline table (32 MHz) and timing-and-area section 3 L_dig bounds.
# At 16 MHz every count halves (timing-and-area section 2).
_SCALE = {32: 1, 16: 2}[CLK_MHZ]
TIFS = 4800 // _SCALE            # LE T_IFS, +/- 64 // _SCALE
TIFS_TOL = 64 // _SCALE
TURNAROUND = 6144 // _SCALE      # 15.4 turnaround (ACK start)
ACKWAIT = 27648 // _SCALE        # 15.4 macAckWaitDuration
LDIG_LE = 320 // _SCALE          # LE 1M L_dig bound
LDIG_154 = 1024 // _SCALE        # 15.4 L_dig bound
LRX_LE, LRX_154 = 6 * 32 // _SCALE, 16 * 32 // _SCALE   # L_rx bounds (6 us, 16 us)
CLK_PER_US = 32 // _SCALE


class Cyc:
    def __init__(self, dut):
        self.dut = dut
        self.n = 0
        cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())

    async def step(self, k=1):
        for _ in range(k):
            await FallingEdge(self.dut.clk)
            self.n += 1

    async def reset(self, **zero):
        d = self.dut
        d.rst_n.value = 0
        for name, v in zero.items():
            getattr(d, name).value = v
        await self.step(3)
        d.rst_n.value = 1
        await self.step(2)

    async def pulse(self, sig):
        """Strobe `sig` for exactly one cycle; return its sample edge."""
        sig.value = 1
        edge = self.n + 1
        await self.step()
        sig.value = 0
        return edge

    async def wait_for(self, sig, limit):
        """Step until `sig` is 1; return the edge after which it was seen."""
        for _ in range(limit):
            if int(sig.value) == 1:
                return self.n
            await self.step()
        raise AssertionError(f"{sig._name} not seen within {limit} cycles")


def report(dut, what, measured, expected=None):
    exp = "" if expected is None else f" expected={expected}"
    msg = (f"MEASURED {what}: {measured} cycles{exp} "
           f"(clk={CLK_MHZ} MHz; simulated at RTL level, on cycle counts)")
    dut._log.info(msg)
    print(msg)
