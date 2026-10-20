"""PLACEHOLDER smoke test for rtl/smoke/lfsr8.v (flow bring-up only).

Setting LFSR_NEGATIVE=1 flips one expected value so the test must fail; the
`make test-negative` target relies on that to prove failures are not swallowed.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge


def lfsr8_model(state: int) -> int:
    fb = ((state >> 7) ^ (state >> 5) ^ (state >> 4) ^ (state >> 3)) & 1
    return ((state << 1) | fb) & 0xFF


@cocotb.test()
async def lfsr8_matches_model(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    dut.en.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 2)
    dut.rst_n.value = 1
    await RisingEdge(dut.clk)
    assert dut.q.value == 0x01

    dut.en.value = 1
    expected = 0x01
    seen = {expected}
    for _ in range(255):
        await RisingEdge(dut.clk)
        await cocotb.triggers.ReadOnly()
        expected = lfsr8_model(expected)
        if os.environ.get("LFSR_NEGATIVE") == "1" and len(seen) == 3:
            expected ^= 0x01  # deliberately wrong expectation
        assert dut.q.value == expected, f"q={int(dut.q.value):#04x} expected={expected:#04x}"
        seen.add(expected)
        await cocotb.triggers.NextTimeStep()
    # Maximal length: 255 distinct nonzero states, back at the seed.
    assert len(seen) == 255 and expected == 0x01
