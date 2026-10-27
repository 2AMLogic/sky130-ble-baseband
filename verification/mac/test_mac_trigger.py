"""mac_trigger: 1 us compare resolution, fire jitter, modes, cancel."""

import random

import cocotb

from mac_common import CLK_PER_US, Cyc, report


async def setup(dut):
    c = Cyc(dut)
    dut.trig_arm.value = 0
    dut.trig_cancel.value = 0
    dut.trig_cmp.value = 0
    dut.trig_mode_tx.value = 0
    dut.rst_n.value = 0
    await c.step(3)
    dut.rst_n.value = 1
    c.rel = c.n          # reset released: first cycle after is counter == 0
    await c.step()
    return c


async def arm(c, dut, cmp, tx):
    dut.trig_cmp.value = cmp
    dut.trig_mode_tx.value = tx
    await c.pulse(dut.trig_arm)


@cocotb.test()
async def fire_offset_constant_across_compare_values(dut):
    offsets = []
    for cmp in (3, 4, 17, 40, 101):
        c = await setup(dut)
        await arm(c, dut, cmp, 1)
        seen = await c.wait_for(dut.trig_fire, (cmp + 3) * CLK_PER_US)
        # cycles from reset release to fire, minus the compare instant
        offsets.append(seen - c.rel - cmp * CLK_PER_US)
    jitter = max(offsets) - min(offsets)
    report(dut, "trigger fire offset after compare instant (per cmp)", offsets)
    report(dut, "trigger jitter (max-min)", jitter, "<= 1")
    assert jitter <= 1
    assert jitter == 0


@cocotb.test()
async def tick_is_one_microsecond(dut):
    c = await setup(dut)
    t0 = int(dut.ts_tick.value)
    await c.step(CLK_PER_US * 5)
    assert int(dut.ts_tick.value) - t0 == 5, "tick advances once per CLK_PER_US cycles"


@cocotb.test()
async def tx_and_rx_modes_and_disarm(dut):
    for tx in (1, 0):
        c = await setup(dut)
        await arm(c, dut, 5, tx)
        assert int(dut.trig_armed.value) == 1
        seen_tx = seen_rx = 0
        for _ in range(8 * CLK_PER_US):
            seen_tx |= int(dut.trig_start_tx.value)
            seen_rx |= int(dut.trig_start_rx.value)
            await c.step()
        assert (seen_tx, seen_rx) == (tx, 1 - tx)
        assert int(dut.trig_armed.value) == 0, "a fire disarms"


@cocotb.test()
async def cancel_wins_and_no_fire(dut):
    c = await setup(dut)
    await arm(c, dut, 6, 1)
    await c.step(CLK_PER_US * 2)
    await c.pulse(dut.trig_cancel)
    fired = 0
    for _ in range(10 * CLK_PER_US):
        fired |= int(dut.trig_fire.value)
        await c.step()
    assert fired == 0 and int(dut.trig_armed.value) == 0


@cocotb.test()
async def random_compares(dut):
    rnd = random.Random(51)
    for _ in range(5):
        cmp = rnd.randint(3, 60)
        c = await setup(dut)
        await arm(c, dut, cmp, rnd.randint(0, 1))
        seen = await c.wait_for(dut.trig_fire, (cmp + 3) * CLK_PER_US)
        assert seen - c.rel - cmp * CLK_PER_US == 1
