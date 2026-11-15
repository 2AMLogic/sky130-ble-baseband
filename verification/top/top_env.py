"""Shared harness for the verification/top benches (test_top.py, test_latency.py).

Extracted from test_top.py so the latency bench (issue #122) drives
`baseband_top` through the same pins with the same conventions. Every
stimulus and every expected value comes from the reference models, as in
the per-block benches (decision 0007); nothing is hand-written.

Env records, on one grid — `cycle` is incremented on FallingEdge(clk)
before every sample in `monitor`, so all reference points below are
directly comparable:
  - `sample_cycle[i]`  cycle the i-th sample's `rx_valid` strobe is high
  - `end_cycle`        first cycle of the adapter's `ev_end`
  - `first_tx`         first cycle of `tx_valid`
  - `cmd_cycle`        first cycle of each TX-command strobe:
                       `resp` (mac_le_resp.resp_tx_req), `ack`
                       (mac_ack_ctrl.ack_tx_req), `host` (the APB CMD=TX
                       pulse `cmd_tx_start`)
`words` accumulates `tx_dev` values at every `tx_valid`.

`monitor` also drives the front-end model: `fe_ready` drops for 20 clk
after any change of fe_rx_en / fe_tx_en / fe_chan_we and rises again only
while a mode is requested. `reset()` clears the per-packet records between
packets (they otherwise accumulate across `drive()` calls, which
top_oqpsk_filter_reject_dropped relies on).
"""

import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge

CTRL, CMD, STATE = 0x000, 0x004, 0x008
INT_RAW, INT_ENABLE, INT_STATUS = 0x040, 0x044, 0x048
TIMING_CTRL = 0x080
ACCESS_ADDR, CRC_INIT, WHITEN_CH = 0x0C0, 0x0C4, 0x0C8
TX_DATA, TX_LENGTH, TX_LEVEL, RX_DATA, RX_LEVEL = 0x100, 0x104, 0x108, 0x10C, 0x110
DESC_COUNT, DESC_INFO, DESC_POP = 0x114, 0x118, 0x12C
RX_SYNC, RX_OK, RX_BAD, RX_OVF, TX_DONE, TX_ERR = 1, 2, 4, 8, 16, 32
CMD_TX, CMD_RX, CMD_ABORT = 1, 2, 4
AA, CRC = 0x8E89BED6, 0x555555


class Env:
    def __init__(self, dut):
        self.dut = dut
        self.words = []                 # tx_dev values with tx_valid
        self.fe_log = []                # (cycle, rx_en, tx_en) changes
        self.cycle = 0
        self.ready_at = 0
        self.sample_cycle = []          # env.cycle at each rx_valid strobe
        self.first_tx = None            # cycle of the first tx_valid
        self.end_cycle = None           # cycle of the adapter's rx_end
        self.cmd_cycle = {"resp": None, "ack": None, "host": None}

    def reset(self):
        """Clear the per-packet records (they accumulate across packets)."""
        self.words.clear()
        self.sample_cycle.clear()
        self.first_tx = None
        self.end_cycle = None
        self.cmd_cycle = {"resp": None, "ack": None, "host": None}

    async def start(self):
        d = self.dut
        cocotb.start_soon(Clock(d.clk, 10, unit="ns").start())
        for n in ("rx_i", "rx_q", "rx_valid", "rx_sat", "PSEL", "PENABLE", "PWRITE", "PADDR",
                  "PWDATA", "PSTRB", "fe_ready"):
            getattr(d, n).value = 0
        d.agc_settled.value = 1
        d.PSTRB.value = 0xF
        d.rst_n.value = 0
        await ClockCycles(d.clk, 4)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 4)
        cocotb.start_soon(self.monitor())

    async def monitor(self):
        d = self.dut
        prev = (0, 0, 0)
        while True:
            await FallingEdge(d.clk)
            self.cycle += 1
            if int(d.tx_valid.value):
                if self.first_tx is None:
                    self.first_tx = self.cycle
                v = int(d.tx_dev.value)
                self.words.append(v - 256 if v > 127 else v)
            if int(d.u_rxa.ev_end.value) and self.end_cycle is None:
                self.end_cycle = self.cycle
            if int(d.resp_tx_req.value) and self.cmd_cycle["resp"] is None:
                self.cmd_cycle["resp"] = self.cycle
            if int(d.ack_tx_req.value) and self.cmd_cycle["ack"] is None:
                self.cmd_cycle["ack"] = self.cycle
            if int(d.cmd_tx_start.value) and self.cmd_cycle["host"] is None:
                self.cmd_cycle["host"] = self.cycle
            cur = (int(d.fe_rx_en.value), int(d.fe_tx_en.value), int(d.fe_chan_we.value))
            if cur != prev:
                self.ready_at = self.cycle + 20
                if cur[:2] != prev[:2]:
                    self.fe_log.append((self.cycle, cur[0], cur[1]))
                assert not (cur[0] and cur[1]), "fe_rx_en and fe_tx_en both set"
            prev = cur
            on = cur[0] or cur[1]
            d.fe_ready.value = int(on and self.cycle >= self.ready_at)

    async def wr(self, addr, data, strb=0xF):
        d = self.dut
        await FallingEdge(d.clk)
        d.PADDR.value, d.PWDATA.value, d.PSTRB.value, d.PWRITE.value, d.PSEL.value = addr, data, strb, 1, 1
        d.PENABLE.value = 0
        await FallingEdge(d.clk)
        d.PENABLE.value = 1
        await FallingEdge(d.clk)
        d.PSEL.value = d.PENABLE.value = d.PWRITE.value = 0

    async def rd(self, addr):
        d = self.dut
        await FallingEdge(d.clk)
        d.PADDR.value, d.PWRITE.value, d.PSEL.value, d.PENABLE.value = addr, 0, 1, 0
        await FallingEdge(d.clk)
        d.PENABLE.value = 1
        await RisingEdge(d.clk)
        val = int(d.PRDATA.value)
        await FallingEdge(d.clk)
        d.PSEL.value = d.PENABLE.value = 0
        return val

    async def wait_int(self, mask, limit):
        for _ in range(limit):
            if await self.rd(INT_RAW) & mask:
                return
            await ClockCycles(self.dut.clk, 40)
        raise AssertionError(f"timeout waiting for INT_RAW & {mask:#x}")

    async def drive(self, iq, flags, seed=1, tail=0):
        """One rx_valid per sample on a 4-clk grid, +/-1 clk jitter (frontend-interface 2.1)."""
        d = self.dut
        rng = random.Random(seed)
        await FallingEdge(d.clk)
        clk = 0
        for n in range(len(iq)):
            due = max(4 * n + rng.choice((-1, 0, 0, 1)), clk)
            while clk < due:
                d.rx_valid.value = 0
                await FallingEdge(d.clk)
                clk += 1
            d.rx_valid.value = 1
            self.sample_cycle.append(self.cycle + 1)
            d.rx_i.value = int(iq[n][0])
            d.rx_q.value = int(iq[n][1])
            d.rx_sat.value = int(flags[n]) & 1
            await FallingEdge(d.clk)
            clk += 1
        d.rx_valid.value = 0


def expect(name, got, exp):
    assert got == exp, f"{name}: got={got!r} expected={exp!r}"


async def configure(env, phy, chan, whiten=0):
    await env.wr(ACCESS_ADDR, AA)
    await env.wr(CRC_INIT, CRC)
    await env.wr(WHITEN_CH, whiten)
    await env.wr(CTRL, 1 | (phy << 1) | (chan << 8))


def frame_154(seq, dst_pan, dst, src, payload):
    """Data frame, ACK requested, PAN compression, short addresses (MPDU without FCS)."""
    return (bytes([0x61, 0x88, seq]) + dst_pan.to_bytes(2, "little") + dst.to_bytes(2, "little")
            + src.to_bytes(2, "little") + payload)
