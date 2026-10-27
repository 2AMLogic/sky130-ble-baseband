"""15.4 ACK-wait: timeout at the constant, cancel on ACK reception."""

import cocotb

from mac_common import ACKWAIT, NEGATIVE, Cyc, report


async def setup(dut):
    c = Cyc(dut)
    for s in ("tx_frame_end", "tx_expect_ack", "ack_rx", "abort_req"):
        getattr(dut, s).value = 0
    await c.reset()
    dut.tx_expect_ack.value = 1
    return c


@cocotb.test()
async def timeout_when_no_ack(dut):
    c = await setup(dut)
    s = await c.pulse(dut.tx_frame_end)
    seen = await c.wait_for(dut.ev_ack_timeout, ACKWAIT + 10)
    report(dut, "15.4 ACK-wait timeout", seen - s, ACKWAIT)
    want = ACKWAIT + (1 if NEGATIVE else 0)
    assert seen - s == want, f"timeout at {seen - s} expected={want}"
    assert seen - s >= ACKWAIT, "must not fire before the constant"
    await c.step()
    assert int(dut.ev_ack_timeout.value) == 0 and int(dut.ackwait_busy.value) == 0


@cocotb.test()
async def cancelled_by_ack(dut):
    c = await setup(dut)
    await c.pulse(dut.tx_frame_end)
    await c.step(1000)
    assert int(dut.ackwait_busy.value) == 1
    dut.ack_rx.value = 1
    await c.step()
    dut.ack_rx.value = 0
    assert int(dut.ackwait_busy.value) == 0
    for _ in range(ACKWAIT + 20):
        assert int(dut.ev_ack_timeout.value) == 0, "timeout after ACK reception"
        await c.step()


@cocotb.test()
async def ack_on_expiry_edge_wins(dut):
    c = await setup(dut)
    s = await c.pulse(dut.tx_frame_end)
    while c.n < s + ACKWAIT - 1:
        await c.step()
    dut.ack_rx.value = 1               # sampled on the expiry edge
    await c.step()
    dut.ack_rx.value = 0
    for _ in range(20):
        assert int(dut.ev_ack_timeout.value) == 0
        await c.step()


@cocotb.test()
async def no_wait_unless_ack_expected_and_abort(dut):
    c = await setup(dut)
    dut.tx_expect_ack.value = 0
    await c.pulse(dut.tx_frame_end)
    assert int(dut.ackwait_busy.value) == 0
    dut.tx_expect_ack.value = 1
    await c.pulse(dut.tx_frame_end)
    await c.step(50)
    await c.pulse(dut.abort_req)
    for _ in range(ACKWAIT + 20):
        assert int(dut.ev_ack_timeout.value) == 0
        await c.step()
    # stray ACK with no wait running raises no ack event
    dut.ack_rx.value = 1
    await c.step()
    assert int(dut.ev_ack_received.value) == 0
    dut.ack_rx.value = 0


@cocotb.test()
async def back_to_back_tx_restarts_wait(dut):
    c = await setup(dut)
    await c.pulse(dut.tx_frame_end)
    await c.step(5000)
    s2 = await c.pulse(dut.tx_frame_end)
    seen = await c.wait_for(dut.ev_ack_timeout, ACKWAIT + 10)
    assert seen - s2 == ACKWAIT
