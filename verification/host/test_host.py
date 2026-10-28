"""cocotb tests for the host interface (rtl/host/, spec/host-interface.md, rtl/host/REGMAP.md).

HOST_FIFO_DEPTH / HOST_CLK_PER_US mirror the parameters run_host.py built the DUT with.
HOST_NEGATIVE=1 flips one expectation (write-1 on a *disabled* INT_STATUS bit is
expected to clear it); the run must then fail with an `expected=` message.
"""

import os

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, Timer

DEPTH = int(os.environ.get("HOST_FIFO_DEPTH", "288"))
CPU = int(os.environ.get("HOST_CLK_PER_US", "32"))

CTRL, CMD, STATE = 0x000, 0x004, 0x008
INT_RAW, INT_ENABLE, INT_STATUS, ERR_STATUS = 0x040, 0x044, 0x048, 0x04C
ACCESS_ADDR, CRC_INIT, WHITEN_CH, OWN_LO, OWN_HI = 0x0C0, 0x0C4, 0x0C8, 0x0CC, 0x0D0
PAN_ID, SHORT_ADDR, EXT_LO, EXT_HI, FILT_CFG = 0x0D4, 0x0D8, 0x0DC, 0x0E0, 0x0E4
TX_DATA, TX_LENGTH, TX_LEVEL, RX_DATA, RX_LEVEL = 0x100, 0x104, 0x108, 0x10C, 0x110
DESC_COUNT, DESC_INFO, DESC_RSSI, DESC_TS_S, DESC_TS_E, DESC_TS_SUB, DESC_POP = (
    0x114, 0x118, 0x11C, 0x120, 0x124, 0x128, 0x12C)
TS_TICK, TS_SUB = 0x140, 0x144
TX_START_T, TX_START_S, TX_END_T, TX_END_S, TRIG_T, TRIG_S = 0x148, 0x14C, 0x150, 0x154, 0x158, 0x15C
RSSI, FE_STATUS, ID, VERSION = 0x180, 0x184, 0xFF0, 0xFF4

RX_SYNC, RX_OK, RX_BAD, RX_OVF, TX_DONE, TX_ERR, ACK_SENT, ACK_TO, RESP, TRIG = (1 << i for i in range(10))
EV_NAMES = ["rx_sync", "rx_done_ok", "rx_done_bad", "rx_overflow", "tx_done", "tx_error",
            "ack_sent", "ack_timeout", "response_sent", "trigger"]

INPUTS = ["psel", "penable", "pwrite", "paddr", "pwdata", "pstrb", "state_i", "tx_pop",
          "rx_push", "rx_wdata", "rx_commit", "rx_rollback", "desc_push", "desc_len_in", "desc_flags_in", "rx_sync",
          "rx_end", "rx_done_ok", "rx_done_bad", "rx_overflow", "tx_start", "tx_done",
          "tx_error", "ack_sent", "ack_timeout", "response_sent", "trigger", "fe_rssi",
          "fe_agc_settled"]


def check(name, got, exp):
    assert got == exp, f"{name}: got={got:#x} expected={exp:#x}"


async def setup(dut):
    cocotb.start_soon(Clock(dut.clk, 10, unit="ns").start())
    for n in INPUTS:
        getattr(dut, n).value = 0
    dut.fe_agc_settled.value = 1
    dut.rst_n_in.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n_in.value = 1
    await ClockCycles(dut.clk, 3)


async def xfer(dut, addr, write, data=0, strb=0xF, side=None):
    """One APB transfer; returns (prdata, pslverr) sampled in the access phase."""
    dut.paddr.value = addr
    dut.pwrite.value = int(write)
    dut.pwdata.value = data
    dut.pstrb.value = strb
    dut.psel.value = 1
    dut.penable.value = 0
    await RisingEdge(dut.clk)
    dut.penable.value = 1
    if side:
        side()
    await FallingEdge(dut.clk)
    rd, err = int(dut.prdata.value), int(dut.pslverr.value)
    assert int(dut.pready.value) == 1
    await RisingEdge(dut.clk)
    dut.psel.value = 0
    dut.penable.value = 0
    await Timer(1, "ns")                      # let post-edge register updates settle
    return rd, err


async def rd(dut, addr):
    v, err = await xfer(dut, addr, False)
    assert err == 0, f"read {addr:#x} unexpected PSLVERR"
    return v


async def wr(dut, addr, data, strb=0xF):
    _, err = await xfer(dut, addr, True, data, strb)
    assert err == 0, f"write {addr:#x} unexpected PSLVERR"


async def strobe(dut, name, cycles=1):
    getattr(dut, name).value = 1
    await ClockCycles(dut.clk, cycles)
    getattr(dut, name).value = 0
    await Timer(1, "ns")


async def rx_push(dut, byte, commit=True):
    """Push one octet; by default publish it at once (a one-octet packet)."""
    dut.rx_wdata.value = byte
    await strobe(dut, "rx_push")
    if commit:
        await strobe(dut, "rx_commit")


@cocotb.test()
async def reset_and_id(dut):
    await setup(dut)
    check("ID", await rd(dut, ID), 0x48494631)
    check("VERSION", await rd(dut, VERSION), 1)
    for a in (CTRL, INT_RAW, INT_ENABLE, ERR_STATUS, ACCESS_ADDR, CRC_INIT, OWN_LO, OWN_HI,
              EXT_LO, EXT_HI, FILT_CFG, TX_LENGTH, TX_LEVEL, RX_LEVEL, DESC_COUNT, STATE):
        check(f"reset value {a:#x}", await rd(dut, a), 0)
    assert int(dut.irq.value) == 0
    check("agc_settled", await rd(dut, FE_STATUS), 1)
    dut.fe_rssi.value = 0xA5
    check("rssi", await rd(dut, RSSI), 0xA5)
    dut.state_i.value = 3
    check("state", await rd(dut, STATE), 3)


@cocotb.test()
async def pslverr_and_strobes(dut):
    await setup(dut)
    for a in (0x00C, 0x020, 0x050, 0x0C, 0x0EC, 0x130, 0x14C + 0x20, 0x188, 0x200, 0x800, 0xFF8):
        _, e = await xfer(dut, a, False)
        check(f"PSLVERR read unmapped {a:#x}", e, 1)
        _, e = await xfer(dut, a, True, 1)
        check(f"PSLVERR write unmapped {a:#x}", e, 1)
    _, e = await xfer(dut, CTRL + 1, False)
    check("PSLVERR unaligned", e, 1)
    for a in (STATE, TX_LEVEL, RX_DATA, RX_LEVEL, DESC_COUNT, TS_TICK, RSSI, ID, VERSION):
        _, e = await xfer(dut, a, True, 0xFFFFFFFF)
        check(f"PSLVERR write RO {a:#x}", e, 1)
    check("RO write had no effect", await rd(dut, ID), 0x48494631)
    # reserved timing window: reads 0, writes ignored, no error
    for a in (0x080, 0x084, 0x0BC):
        await wr(dut, a, 0xFFFFFFFF)
        check(f"reserved {a:#x}", await rd(dut, a), 0)
    # byte-lane strobes
    await wr(dut, ACCESS_ADDR, 0xAABBCCDD)
    await wr(dut, ACCESS_ADDR, 0x11223344, strb=0b0101)
    check("PSTRB lanes", await rd(dut, ACCESS_ADDR), 0xAA22CC44)
    await wr(dut, ACCESS_ADDR, 0xFFFFFFFF, strb=0)
    check("PSTRB none", await rd(dut, ACCESS_ADDR), 0xAA22CC44)
    # write-only reads return 0 without error
    check("TX_DATA read", await rd(dut, TX_DATA), 0)
    check("CMD read", await rd(dut, CMD), 0)


@cocotb.test()
async def config_registers(dut):
    await setup(dut)
    await wr(dut, CTRL, 0xFFFFFFFF)
    check("CTRL mask", await rd(dut, CTRL), 0x7F03)
    assert int(dut.ctrl_enable.value) == 1 and int(dut.ctrl_phy.value) == 1
    check("chan", int(dut.ctrl_chan.value), 0x7F)
    await wr(dut, CTRL, 0x00000100)
    check("CTRL lane 1", await rd(dut, CTRL), 0x0100)
    await wr(dut, CRC_INIT, 0xFFFFFFFF)
    check("crc_init 24b", await rd(dut, CRC_INIT), 0xFFFFFF)
    await wr(dut, WHITEN_CH, 0xFFFFFFFF)
    check("whiten 6b", await rd(dut, WHITEN_CH), 0x3F)
    await wr(dut, OWN_LO, 0x01234567)
    await wr(dut, OWN_HI, 0xFFFFFFFF)
    check("own hi", await rd(dut, OWN_HI), 0x3FFFF)
    check("own addr", int(dut.cfg_own_addr.value), 0xFFFF01234567)
    check("own type", int(dut.cfg_own_addr_type.value), 3)
    await wr(dut, EXT_LO, 0xDEADBEEF)
    await wr(dut, EXT_HI, 0xCAFEF00D)
    check("ext addr", int(dut.cfg_ext_addr.value), 0xCAFEF00DDEADBEEF)
    await wr(dut, PAN_ID, 0xFFFF1234)
    check("pan", int(dut.cfg_pan_id.value), 0x1234)
    await wr(dut, SHORT_ADDR, 0xBEEF)
    check("short", int(dut.cfg_short_addr.value), 0xBEEF)
    await wr(dut, FILT_CFG, 0xFF)
    check("filt", await rd(dut, FILT_CFG), 3)
    await wr(dut, TX_LENGTH, 0xFFFFFFFF)
    check("tx_length 9b", await rd(dut, TX_LENGTH), 0x1FF)


@cocotb.test()
async def command_pulses(dut):
    await setup(dut)
    seen = []

    async def watch():
        for _ in range(8):
            await RisingEdge(dut.clk)
            seen.append((int(dut.cmd_tx_start.value), int(dut.cmd_rx_start.value),
                         int(dut.cmd_abort.value)))
    cocotb.start_soon(watch())
    await wr(dut, CMD, 0b101)
    await ClockCycles(dut.clk, 8)
    assert sum(s[0] for s in seen) == 1 and sum(s[2] for s in seen) == 1 and sum(s[1] for s in seen) == 0, seen
    assert (int(dut.cmd_tx_start.value), int(dut.cmd_rx_start.value), int(dut.cmd_abort.value)) == (0, 0, 0)


@cocotb.test()
async def tx_fifo(dut):
    await setup(dut)
    for i in range(DEPTH):
        await wr(dut, TX_DATA, 0xFFFFFF00 | (i & 0xFF))     # bits 31:8 ignored
    check("TX_LEVEL full", await rd(dut, TX_LEVEL), DEPTH)
    check("no overflow yet", await rd(dut, ERR_STATUS), 0)
    await wr(dut, TX_DATA, 0x55)                            # write when full
    check("TX_OVERFLOW", await rd(dut, ERR_STATUS), 2)
    assert int(dut.irq.value) == 0, "ERR_STATUS must not drive irq"
    check("level unchanged", await rd(dut, TX_LEVEL), DEPTH)
    await wr(dut, ERR_STATUS, 2)
    check("err W1C", await rd(dut, ERR_STATUS), 0)
    await wr(dut, TX_DATA, 0x66, strb=0b0010)               # byte 0 not strobed: no push
    check("PSTRB[0]=0 no push", await rd(dut, TX_LEVEL), DEPTH)
    # drain through the consumer port, FIFO order, also across a wrap
    for rounds in range(2):
        got = []
        for _ in range(DEPTH):
            await FallingEdge(dut.clk)
            got.append(int(dut.tx_rdata.value))
            dut.tx_pop.value = 1
            await RisingEdge(dut.clk)
            dut.tx_pop.value = 0
        await Timer(1, "ns")
        base = 0 if rounds == 0 else 0x80
        check("drained order", got[0], base)
        assert got == [(base + i) & 0xFF for i in range(DEPTH)], got
        assert int(dut.tx_empty.value) == 1
        for i in range(DEPTH):
            await wr(dut, TX_DATA, (0x80 + i) & 0xFF)
    await wr(dut, CMD, 1 << 3)                              # TX FIFO reset
    await ClockCycles(dut.clk, 2)
    check("flush", await rd(dut, TX_LEVEL), 0)


@cocotb.test()
async def rx_fifo_and_overflow(dut):
    await setup(dut)
    data = [(0x30 + i) & 0xFF for i in range(DEPTH)]
    for b in data[:3]:
        await rx_push(dut, b)
    check("RX_LEVEL", await rd(dut, RX_LEVEL), 3)
    for b in data[:3]:
        check("RX_DATA pop", await rd(dut, RX_DATA), b)
    check("RX empty level", await rd(dut, RX_LEVEL), 0)
    check("no underflow yet", await rd(dut, ERR_STATUS), 0)
    check("empty read returns 0", await rd(dut, RX_DATA), 0)
    check("RX_UNDERFLOW", await rd(dut, ERR_STATUS), 1)
    assert int(dut.irq.value) == 0
    await wr(dut, ERR_STATUS, 1)
    check("RX_UNDERFLOW cleared", await rd(dut, ERR_STATUS), 0)
    # fill, then push one more: dropped, RX_OVERFLOW raw set, older data intact
    for b in data:
        await rx_push(dut, b)
    assert int(dut.rx_full.value) == 1
    check("raw before overflow", await rd(dut, INT_RAW), 0)
    await rx_push(dut, 0xEE)
    check("RX_OVERFLOW raw", await rd(dut, INT_RAW), RX_OVF)
    check("level at depth", await rd(dut, RX_LEVEL), DEPTH)
    for b in data:
        check("older data kept", await rd(dut, RX_DATA), b)
    check("empty after", await rd(dut, RX_LEVEL), 0)
    # simultaneous push + APB pop at level 1 keeps FIFO order
    await rx_push(dut, 0x11)
    dut.rx_wdata.value = 0x22
    dut.rx_push.value = 1
    v, _ = await xfer(dut, RX_DATA, False)
    dut.rx_push.value = 0
    await strobe(dut, "rx_commit")
    check("simul pop", v, 0x11)
    check("simul remaining", await rd(dut, RX_DATA), 0x22)
    await rx_push(dut, 0x77)
    await wr(dut, CMD, 1 << 4)
    await ClockCycles(dut.clk, 2)
    check("RX flush", await rd(dut, RX_LEVEL), 0)


async def rx_packet(dut, octets, end):
    """Push a packet's octets provisionally, then end it with 'commit' or 'rollback'."""
    for b in octets:
        await rx_push(dut, b, commit=False)
    await strobe(dut, end)


@cocotb.test()
async def rx_fifo_rollback(dut):
    """A rejected packet leaves no octets; the accepted one after it reads back intact."""
    await setup(dut)
    a, b, c = [0xA0, 0xA1, 0xA2], [0xB0, 0xB1, 0xB2, 0xB3], [0xC0, 0xC1]
    await rx_packet(dut, a, "rx_commit")
    # provisional octets take space but are invisible to the host
    for x in b:
        await rx_push(dut, x, commit=False)
    check("level hides provisional", await rd(dut, RX_LEVEL), len(a))
    await strobe(dut, "rx_rollback")
    check("level after rollback", await rd(dut, RX_LEVEL), len(a))
    await rx_packet(dut, c, "rx_commit")
    check("level a+c", await rd(dut, RX_LEVEL), len(a) + len(c))
    for x in a + c:
        check("only accepted octets", await rd(dut, RX_DATA), x)
    check("empty", await rd(dut, RX_LEVEL), 0)
    check("no error", await rd(dut, ERR_STATUS), 0)
    # rollback of a packet that wraps the write pointer
    for i in range(DEPTH - 1):
        await rx_push(dut, i & 0xFF)
        await rd(dut, RX_DATA)
    await rx_packet(dut, [0x51], "rx_commit")
    await rx_packet(dut, [0x61, 0x62, 0x63], "rx_rollback")
    await rx_packet(dut, [0x71, 0x72], "rx_commit")
    for x in (0x51, 0x71, 0x72):
        check("wrap rollback", await rd(dut, RX_DATA), x)
    check("empty after wrap", await rd(dut, RX_LEVEL), 0)


@cocotb.test()
async def rx_fifo_rollback_near_full(dut):
    """A reject while the FIFO is nearly full (overflowing) frees exactly its own space."""
    await setup(dut)
    a = [(0x40 + i) & 0xFF for i in range(DEPTH - 2)]
    await rx_packet(dut, a, "rx_commit")
    # five octets offered, two fit, three are refused and raise RX_OVERFLOW
    await rx_packet(dut, [0xE0 + i for i in range(5)], "rx_rollback")
    check("RX_OVERFLOW from refused octets", await rd(dut, INT_RAW) & RX_OVF, RX_OVF)
    check("level back to a", await rd(dut, RX_LEVEL), len(a))
    assert int(dut.rx_full.value) == 0
    await rx_packet(dut, [0x01, 0x02], "rx_commit")     # the freed space is usable
    check("full again", await rd(dut, RX_LEVEL), DEPTH)
    for x in a + [0x01, 0x02]:
        check("data intact", await rd(dut, RX_DATA), x)
    check("empty", await rd(dut, RX_LEVEL), 0)
    # a pop in the cycle of the rollback does not corrupt the count
    await rx_packet(dut, [0x10, 0x11], "rx_commit")
    for x in (0x90, 0x91):
        await rx_push(dut, x, commit=False)
    dut.rx_rollback.value = 1
    v, _ = await xfer(dut, RX_DATA, False)
    dut.rx_rollback.value = 0
    check("pop beside rollback", v, 0x10)
    check("level after", await rd(dut, RX_LEVEL), 1)
    check("remaining", await rd(dut, RX_DATA), 0x11)


async def push_desc(dut, length, flags, rssi, sync_gap=3):
    dut.rx_sync.value = 1
    await RisingEdge(dut.clk)
    dut.rx_sync.value = 0
    await ClockCycles(dut.clk, sync_gap)
    dut.rx_end.value = 1
    await RisingEdge(dut.clk)
    dut.rx_end.value = 0
    await ClockCycles(dut.clk, 2)
    dut.fe_rssi.value = rssi
    dut.desc_len_in.value = length
    dut.desc_flags_in.value = flags
    dut.desc_push.value = 1
    await RisingEdge(dut.clk)
    dut.desc_push.value = 0
    await ClockCycles(dut.clk, 1)


@cocotb.test()
async def descriptor_fifo(dut):
    await setup(dut)
    check("empty", await rd(dut, DESC_COUNT), 0)
    check("empty head len", await rd(dut, DESC_INFO), 0)
    await wr(dut, DESC_POP, 1)                       # pop on empty: harmless
    check("pop empty", await rd(dut, DESC_COUNT), 0)
    entries = [(100 + i, (1 << (i % 5)), 0x10 + i) for i in range(4)]
    for ln, fl, rs in entries:
        await push_desc(dut, ln, fl, rs)
    check("count 4", await rd(dut, DESC_COUNT), 4)
    check("no overflow", await rd(dut, INT_RAW) & RX_OVF, 0)
    await push_desc(dut, 300, 0x1F, 0x99)            # fifth: dropped
    check("RX_OVERFLOW from descriptor", await rd(dut, INT_RAW) & RX_OVF, RX_OVF)
    check("still 4", await rd(dut, DESC_COUNT), 4)
    prev_end = -1
    for ln, fl, rs in entries:
        check("len", await rd(dut, DESC_INFO) & 0x1FF, ln)
        check("flags", (await rd(dut, DESC_INFO) >> 16) & 0x1F, fl)
        check("rssi", await rd(dut, DESC_RSSI), rs)
        ts_s = await rd(dut, DESC_TS_S)
        ts_e = await rd(dut, DESC_TS_E)
        sub = await rd(dut, DESC_TS_SUB)
        assert (ts_e, sub >> 8 & 0x1F) > (ts_s, sub & 0x1F), "end must be after start"
        assert ts_s > prev_end - 1
        prev_end = ts_e
        await wr(dut, DESC_POP, 1)
    check("drained", await rd(dut, DESC_COUNT), 0)
    check("drained head", await rd(dut, DESC_RSSI), 0)


@cocotb.test()
async def interrupts(dut):
    await setup(dut)
    # each event sets exactly its raw bit; nothing reaches irq until enabled
    for i, n in enumerate(EV_NAMES):
        await strobe(dut, n)
        await ClockCycles(dut.clk, 1)
        check(f"raw after {n}", await rd(dut, INT_RAW), 1 << i)
        assert int(dut.irq.value) == 0, "irq must be gated by INT_ENABLE"
        await wr(dut, INT_RAW, 1 << i)
        check(f"raw cleared {n}", await rd(dut, INT_RAW), 0)
    # enable gating of status and irq
    await wr(dut, INT_ENABLE, TX_DONE | ACK_SENT)
    check("enable readback", await rd(dut, INT_ENABLE), TX_DONE | ACK_SENT)
    await strobe(dut, "tx_done")
    await strobe(dut, "response_sent")
    await ClockCycles(dut.clk, 1)
    check("raw", await rd(dut, INT_RAW), TX_DONE | RESP)
    check("status = raw & enable", await rd(dut, INT_STATUS), TX_DONE)
    assert int(dut.irq.value) == 1
    # sticky: stays after the strobe is gone, no read-to-clear
    await ClockCycles(dut.clk, 5)
    check("sticky", await rd(dut, INT_RAW), TX_DONE | RESP)
    check("no read-to-clear", await rd(dut, INT_STATUS), TX_DONE)
    # W1C on INT_STATUS: clears an enabled bit, does nothing to a disabled one
    await wr(dut, INT_STATUS, TX_DONE | RESP)
    exp_raw = 0 if os.environ.get("HOST_NEGATIVE") == "1" else RESP   # negative control: wrong polarity
    check("W1C status: enabled cleared, disabled kept", await rd(dut, INT_RAW), exp_raw)
    assert int(dut.irq.value) == 0
    # W1C on INT_RAW clears disabled bits; byte lanes honoured
    await wr(dut, INT_RAW, RESP, strb=0b0001)
    check("raw bit 8 not in lane 0", await rd(dut, INT_RAW), RESP)
    await wr(dut, INT_RAW, RESP, strb=0b0010)
    check("raw cleared via lane 1", await rd(dut, INT_RAW), 0)
    # same-cycle event wins over the clear (both register paths)
    await wr(dut, INT_ENABLE, TX_DONE)
    await strobe(dut, "tx_done")
    await xfer(dut, INT_RAW, True, TX_DONE, side=lambda: setattr(dut.tx_done, "value", 1))
    dut.tx_done.value = 0
    check("event wins vs INT_RAW clear", await rd(dut, INT_RAW), TX_DONE)
    await xfer(dut, INT_STATUS, True, TX_DONE, side=lambda: setattr(dut.tx_done, "value", 1))
    dut.tx_done.value = 0
    check("event wins vs INT_STATUS clear", await rd(dut, INT_RAW), TX_DONE)
    await wr(dut, INT_RAW, TX_DONE)
    check("then clears", await rd(dut, INT_RAW), 0)
    # RX_OVERFLOW from the external strobe and irq asserts/deasserts level-wise
    await wr(dut, INT_ENABLE, RX_OVF)
    await strobe(dut, "rx_overflow")
    await ClockCycles(dut.clk, 1)
    assert int(dut.irq.value) == 1
    await wr(dut, INT_ENABLE, 0)
    assert int(dut.irq.value) == 0
    await wr(dut, INT_RAW, 0x3FF)
    check("clear all", await rd(dut, INT_RAW), 0)


@cocotb.test()
async def timestamps(dut):
    await setup(dut)
    # counter model: sub counts 0..CPU-1, tick increments on wrap
    prev = None
    wraps = 0
    for _ in range(3 * CPU + 5):
        await FallingEdge(dut.clk)
        cur = (int(dut.u_ts.tick.value), int(dut.u_ts.sub.value))
        if prev is not None:
            if prev[1] == CPU - 1:
                check("wrap", cur[1], 0)
                check("tick inc", cur[0], prev[0] + 1)
                wraps += 1
            else:
                check("sub inc", cur[1], prev[1] + 1)
                check("tick hold", cur[0], prev[0])
        prev = cur
    assert wraps >= 3
    # coherent read: reading TS_SUB (low word) latches the tick of that same cycle for TS_TICK
    for gap in (0, 1, 3, 7):
        await ClockCycles(dut.clk, gap)
        dut.paddr.value = TS_SUB
        dut.pwrite.value = 0
        dut.psel.value = 1
        dut.penable.value = 0
        await RisingEdge(dut.clk)
        dut.penable.value = 1
        await FallingEdge(dut.clk)
        s, t = int(dut.prdata.value), int(dut.u_ts.tick.value)
        check("sub read matches counter", s, int(dut.u_ts.sub.value))
        await RisingEdge(dut.clk)
        dut.psel.value = 0
        dut.penable.value = 0
        await ClockCycles(dut.clk, 5)                      # counter has moved on
        check("tick latched", await rd(dut, TS_TICK), t)
    # event capture registers
    for name, rt, rs in (("tx_start", TX_START_T, TX_START_S), ("tx_done", TX_END_T, TX_END_S),
                         ("trigger", TRIG_T, TRIG_S)):
        await ClockCycles(dut.clk, 7)
        getattr(dut, name).value = 1
        await FallingEdge(dut.clk)
        exp = (int(dut.u_ts.tick.value), int(dut.u_ts.sub.value))
        await RisingEdge(dut.clk)
        getattr(dut, name).value = 0
        await ClockCycles(dut.clk, 40)
        check(f"{name} tick", await rd(dut, rt), exp[0])
        check(f"{name} sub", await rd(dut, rs), exp[1])
    # tx_done/trigger also raised interrupts; the capture stays put afterwards
    await ClockCycles(dut.clk, 3 * CPU)
    t1 = await rd(dut, TX_START_T)
    t2 = await rd(dut, TX_START_T)
    check("capture holds", t1, t2)
