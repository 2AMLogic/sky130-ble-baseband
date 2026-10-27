"""LE T_IFS timer and timed response."""

import cocotb

from mac_common import (LDIG_LE, LRX_LE, NEGATIVE, TIFS, TIFS_TOL, Cyc, report)

LTX_LE = LDIG_LE - LRX_LE
N = TIFS - LDIG_LE


async def setup(dut):
    c = Cyc(dut)
    for s in ("resp_enable", "crc_gate_en", "rx_end", "rx_crc_ok", "rx_accept",
              "tx_end", "abort_req"):
        getattr(dut, s).value = 0
    await c.reset()
    dut.resp_enable.value = 1
    dut.crc_gate_en.value = 1
    dut.rx_accept.value = 1
    return c


async def rx_end(c, dut, crc=1, accept=1):
    dut.rx_crc_ok.value = crc
    dut.rx_accept.value = accept
    return await c.pulse(dut.rx_end)


async def none_for(c, sig, cycles=TIFS + 50):
    for _ in range(cycles):
        assert int(sig.value) == 0
        await c.step()


@cocotb.test()
async def tifs_lands_on_150us_count(dut):
    c = await setup(dut)
    e2e, lat = [], []
    for _ in range(4):
        s = await rx_end(c, dut)
        seen = await c.wait_for(dut.resp_tx_req, TIFS + 10)
        lat.append(seen - s)
        e2e.append((seen + LTX_LE) - (s - LRX_LE))
        await c.step(TIFS + 10)
    want = TIFS + (1 if NEGATIVE else 0)
    report(dut, "LE rx_end -> resp_tx_req", lat[0], N)
    report(dut, "LE end-of-packet -> first tx_valid (L_rx/L_tx modelled at the bound)", e2e[0], TIFS)
    report(dut, "LE T_IFS jitter (max-min)", max(lat) - min(lat), 0)
    assert set(e2e) == {want}, f"T_IFS {e2e} expected={want}"
    assert all(abs(x - TIFS) <= TIFS_TOL for x in e2e)
    assert max(lat) == min(lat)


@cocotb.test()
async def crc_fail_suppresses_response(dut):
    c = await setup(dut)
    await rx_end(c, dut, crc=0)
    await none_for(c, dut.resp_tx_req)
    dut.crc_gate_en.value = 0                  # R1: gating is configurable
    s = await rx_end(c, dut, crc=0)
    seen = await c.wait_for(dut.resp_tx_req, TIFS + 10)
    assert seen - s == N


@cocotb.test()
async def filter_reject_and_disable(dut):
    c = await setup(dut)
    await rx_end(c, dut, accept=0)
    await none_for(c, dut.resp_tx_req)
    dut.resp_enable.value = 0
    await rx_end(c, dut)
    await none_for(c, dut.resp_tx_req)


@cocotb.test()
async def abort_and_disable_during_ifs(dut):
    c = await setup(dut)
    await rx_end(c, dut)
    await c.step(N // 2)
    await c.pulse(dut.abort_req)
    await none_for(c, dut.resp_tx_req)
    await rx_end(c, dut)
    await c.step(N // 2)
    dut.resp_enable.value = 0
    await none_for(c, dut.resp_tx_req)


@cocotb.test()
async def own_tx_end_gives_ifs_after_tx(dut):
    c = await setup(dut)
    s = await c.pulse(dut.tx_end)
    seen = await c.wait_for(dut.ifs_after_tx, TIFS + 10)
    assert seen - s == N
    assert int(dut.resp_tx_req.value) == 0
    # tx_end path is not gated by CRC / filter / enable
    dut.resp_enable.value = 0
    dut.rx_accept.value = 0
    s = await c.pulse(dut.tx_end)
    seen = await c.wait_for(dut.ifs_after_tx, TIFS + 10)
    assert seen - s == N


@cocotb.test()
async def back_to_back_and_rearm_at_expiry(dut):
    c = await setup(dut)
    for _ in range(3):
        s = await rx_end(c, dut)
        seen = await c.wait_for(dut.resp_tx_req, TIFS + 10)
        assert seen - s == N
        await c.step()
    s = await rx_end(c, dut)
    while c.n < s + N - 1:
        await c.step()
    s2 = await rx_end(c, dut)                  # sampled on the expiry edge
    assert s2 == s + N
    assert int(dut.resp_tx_req.value) == 1     # old expiry fires
    await c.step()
    seen = await c.wait_for(dut.resp_tx_req, TIFS + 10)
    assert seen - s2 == N
