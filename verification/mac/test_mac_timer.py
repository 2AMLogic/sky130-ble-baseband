"""mac_timer core: exact latency, cancel, re-arm, priority (CYCLES=7 build)."""

import cocotb

from mac_common import Cyc

N = 7


async def setup(dut):
    c = Cyc(dut)
    dut.start.value = 0
    dut.cancel.value = 0
    await c.reset()
    return c


@cocotb.test()
async def latency_is_exactly_n(dut):
    c = await setup(dut)
    for _ in range(3):
        s = await c.pulse(dut.start)
        seen = await c.wait_for(dut.fire, 50)
        assert seen - s == N, f"latency {seen - s} != {N}"
        await c.step()
        assert int(dut.fire.value) == 0, "fire must be a one-cycle strobe"
        assert int(dut.busy.value) == 0
        await c.step(3)


@cocotb.test()
async def cancel_before_expiry(dut):
    c = await setup(dut)
    await c.pulse(dut.start)
    await c.step(3)
    assert int(dut.busy.value) == 1
    await c.pulse(dut.cancel)
    await c.step(N + 5)
    assert int(dut.fire.value) == 0 and int(dut.busy.value) == 0


@cocotb.test()
async def cancel_on_expiry_edge_wins(dut):
    c = await setup(dut)
    s = await c.pulse(dut.start)
    # expiry edge is s+N; cancel must be sampled on exactly that edge
    while c.n < s + N - 1:
        assert int(dut.fire.value) == 0
        await c.step()
    dut.cancel.value = 1          # sampled on edge s+N
    await c.step()
    dut.cancel.value = 0
    await c.step(5)
    assert int(dut.fire.value) == 0, "cancel on the expiry edge must suppress fire"


@cocotb.test()
async def rearm_same_edge_as_expiry(dut):
    c = await setup(dut)
    s = await c.pulse(dut.start)
    while c.n < s + N - 1:
        await c.step()
    dut.start.value = 1           # sampled on the expiry edge s+N
    e2 = c.n + 1
    await c.step()
    dut.start.value = 0
    assert e2 == s + N
    assert int(dut.fire.value) == 1, "old expiry still fires"
    assert int(dut.busy.value) == 1, "timer is running again"
    await c.step()
    seen = await c.wait_for(dut.fire, 50)
    assert seen - e2 == N, f"re-armed latency {seen - e2} != {N}"


@cocotb.test()
async def restart_midway_reloads(dut):
    c = await setup(dut)
    await c.pulse(dut.start)
    await c.step(3)
    s2 = await c.pulse(dut.start)
    seen = await c.wait_for(dut.fire, 50)
    assert seen - s2 == N
