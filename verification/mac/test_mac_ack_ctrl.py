"""15.4 auto-ACK: turnaround cycles vs the 0006 budget, eligibility, edges."""

import random

import cocotb

from mac_common import (LDIG_154, LRX_154, NEGATIVE, TURNAROUND, Cyc, report)

LTX_154 = LDIG_154 - LRX_154


async def setup(dut):
    c = Cyc(dut)
    for s in ("ack_enable", "fp_bit", "rx_end", "rx_fcs_ok", "rx_ack_req",
              "rx_is_ack", "rx_ack_eligible", "abort_req"):
        getattr(dut, s).value = 0
    dut.rx_seq.value = 0
    await c.reset()
    dut.ack_enable.value = 1
    return c


async def frame_end(c, dut, seq=0x5A, fcs=1, req=1, is_ack=0, elig=1):
    dut.rx_fcs_ok.value = fcs
    dut.rx_ack_req.value = req
    dut.rx_is_ack.value = is_ack
    dut.rx_ack_eligible.value = elig
    dut.rx_seq.value = seq
    return await c.pulse(dut.rx_end)


async def expect_no_tx(c, dut, cycles=TURNAROUND + 50):
    for _ in range(cycles):
        assert int(dut.ack_tx_req.value) == 0, "spurious ACK"
        await c.step()


@cocotb.test()
async def turnaround_lands_on_deadline(dut):
    c = await setup(dut)
    lat, e2e = [], []
    rnd = random.Random(7)
    for i in range(6):
        await c.step(rnd.randint(1, 9))
        s = await frame_end(c, dut, seq=i)
        seen = await c.wait_for(dut.ack_tx_req, TURNAROUND + 10)
        lat.append(seen - s)
        # Modelled digital path: last bit -> (L_rx) -> rx_end ... tx_req -> (L_tx) -> tx_valid.
        # L_rx / L_tx here are the section-3 bounds, a model, not this block.
        last_bit = s - LRX_154
        first_tx_valid = seen + LTX_154
        e2e.append(first_tx_valid - last_bit)
        assert int(dut.ack_seq.value) == i
        await c.step(TURNAROUND + 20)
    exp = TURNAROUND + (1 if NEGATIVE else 0)
    report(dut, "15.4 rx_end -> ack_tx_req", lat[0], TURNAROUND - LDIG_154)
    report(dut, "15.4 end-of-frame -> first tx_valid (L_rx/L_tx modelled at the bound)", e2e[0], TURNAROUND)
    report(dut, "15.4 turnaround jitter (max-min over frames)", max(lat) - min(lat), 0)
    assert set(e2e) == {exp}, f"turnaround {e2e} != expected={exp}"
    assert max(lat) == min(lat)
    assert min(e2e) >= TURNAROUND, "ACK must not start before the constant"


@cocotb.test()
async def ack_suppressed_cases(dut):
    c = await setup(dut)
    for kw in (dict(fcs=0), dict(elig=0), dict(req=0), dict(is_ack=1)):
        await frame_end(c, dut, **kw)
        await expect_no_tx(c, dut)
    dut.ack_enable.value = 0
    await frame_end(c, dut)
    await expect_no_tx(c, dut)


@cocotb.test()
async def frame_pending_from_register(dut):
    c = await setup(dut)
    for fp in (1, 0, 1):
        dut.fp_bit.value = fp
        await frame_end(c, dut)
        dut.fp_bit.value = 1 - fp       # changing it after rx_end must not matter
        await c.wait_for(dut.ack_tx_req, TURNAROUND + 10)
        assert int(dut.ack_fp.value) == fp
        await c.step(5)


@cocotb.test()
async def abort_during_turnaround(dut):
    c = await setup(dut)
    await frame_end(c, dut)
    await c.step(TURNAROUND // 2)
    assert int(dut.ack_pending.value) == 1
    await c.pulse(dut.abort_req)
    assert int(dut.ack_pending.value) == 0
    await expect_no_tx(c, dut)


@cocotb.test()
async def ack_enable_cleared_during_turnaround(dut):
    c = await setup(dut)
    await frame_end(c, dut)
    await c.step(100)
    dut.ack_enable.value = 0
    await expect_no_tx(c, dut)


@cocotb.test()
async def back_to_back_frames(dut):
    c = await setup(dut)
    for i in range(3):                  # next frame right after each ACK start
        s = await frame_end(c, dut, seq=0x10 + i)
        seen = await c.wait_for(dut.ack_tx_req, TURNAROUND + 10)
        assert seen - s == TURNAROUND - LDIG_154
        assert int(dut.ack_seq.value) == 0x10 + i
        await c.step()
    # second frame ends while the first ACK is pending: newer frame wins
    s1 = await frame_end(c, dut, seq=0x21)
    await c.step(200)
    s2 = await frame_end(c, dut, seq=0x22)
    seen = await c.wait_for(dut.ack_tx_req, TURNAROUND + 10)
    assert seen - s2 == TURNAROUND - LDIG_154 and int(dut.ack_seq.value) == 0x22
    await c.step(1)
    await expect_no_tx(c, dut)         # exactly one ACK for the pair
    # a later non-qualifying frame cancels a pending ACK
    await frame_end(c, dut, seq=0x30)
    await c.step(100)
    await frame_end(c, dut, seq=0x31, fcs=0)
    await expect_no_tx(c, dut)
