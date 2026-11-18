"""cocotb integration bench for rtl/top/baseband_top.v.

Every stimulus and every expected value comes from the reference models, as in
the per-block benches (decision 0007); nothing is hand-written:
  - TX: the PDU / PSDU is written through APB (TX_DATA, TX_LENGTH, CMD) and the
    tx_dev words are compared with sim/model/le1m_tx.py / oqpsk_tx.py, in order.
  - RX: a sample stream is replayed on rx_i / rx_q / rx_valid (LE: CM-A channel
    model, whitened as on air; 15.4: the model's loopback) and the octets read
    back through RX_DATA, the descriptor and INT_RAW are compared with the packet
    that was sent.
A front-end model drives fe_ready: it drops fe_ready for 20 clk after any change of
fe_rx_en / fe_tx_en / fe_chan_we and raises it again only while a mode is requested.
The shared harness (registers, `Env`, `expect`, `configure`, `frame_154`) lives in
top_env.py, imported here and by test_latency.py.

Covered: LE 1M and 15.4 TX and RX through the top, the STATE register, interrupt
bits, descriptor length / flags, fe_* handshake. Not covered here: BER / PER (no
claim is made), AGC (placeholder), back-to-back packets, the 16 MHz fallback.
TOP_NEGATIVE=1 perturbs one expected value per test (message carries `expected=`).
"""

import os
import sys
from pathlib import Path

import numpy as np

import cocotb
from cocotb.triggers import ClockCycles

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sim" / "channel"), str(ROOT / "sim" / "model"),
                str(ROOT / "verification" / "oqpsk")]
import cm_a  # noqa: E402
import le1m_tx  # noqa: E402
import oqpsk_tx  # noqa: E402
import packet  # noqa: E402
import cases as oq_cases  # noqa: E402
from top_env import (CMD, CMD_ABORT, CMD_RX, CMD_TX, DESC_COUNT, DESC_INFO,  # noqa: E402
                    INT_ENABLE, INT_RAW, RX_BAD, RX_DATA, RX_LEVEL, RX_OK, RX_SYNC,
                    STATE, TIMING_CTRL, TX_DATA, TX_DONE, TX_ERR, TX_LENGTH, TX_LEVEL,
                    Env, configure, expect, frame_154)

NEGATIVE = os.environ.get("TOP_NEGATIVE") == "1"


async def tx_case(env, pdu, phy, expected_words, limit=20000):
    await env.wr(TX_LENGTH, len(pdu))
    for b in pdu:
        await env.wr(TX_DATA, b)
    expect("TX_LEVEL", await env.rd(TX_LEVEL), len(pdu))
    env.words.clear()
    await env.wr(CMD, CMD_TX)
    await env.wait_int(TX_DONE, limit)
    exp = list(expected_words)
    if NEGATIVE:
        exp[100] += 1
    expect("tx_dev word count", len(env.words), len(exp))
    for i, (g, e) in enumerate(zip(env.words, exp)):
        assert g == e, f"tx_dev word {i}: got={g} expected={e}"
    expect("STATE after TX", await env.rd(STATE), 0)
    expect("TX_LEVEL after TX", await env.rd(TX_LEVEL), 0)
    assert not int(env.dut.tx_active.value), "tx_active still high"
    assert not (int(env.dut.fe_rx_en.value) or int(env.dut.fe_tx_en.value)), "front end not released"


@cocotb.test()
async def top_le1m_tx(dut):
    env = Env(dut)
    await env.start()
    pdu = bytes.fromhex("4209010203040506020106")        # sim/model/README.md golden PDU
    await configure(env, 0, 37, whiten=37)
    await tx_case(env, pdu, 0, le1m_tx.tx_dev_words(pdu, 37))
    # fe handshake: TX mode requested, then released
    assert env.fe_log and env.fe_log[0][2] == 1 and env.fe_log[-1][1:] == (0, 0), env.fe_log
    expect("INT_RAW has no TX_ERROR", await env.rd(INT_RAW) & TX_ERR, 0)


@cocotb.test()
async def top_oqpsk_tx(dut):
    env = Env(dut)
    await env.start()
    payload = bytes(range(1, 19))                        # the golden 18-octet payload
    await configure(env, 1, 11)
    await tx_case(env, payload, 1, oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(payload)))


async def rx_case(env, iq, flags, expected, phy, name):
    await env.wr(INT_ENABLE, RX_SYNC | RX_OK | RX_BAD)
    await env.wr(CMD, CMD_RX)
    for _ in range(200):
        if await env.rd(STATE) == 1:
            break
        await ClockCycles(env.dut.clk, 5)
    expect(f"{name}: STATE while receiving", await env.rd(STATE), 1)
    assert int(env.dut.fe_rx_en.value) and not int(env.dut.fe_tx_en.value)
    await env.drive(iq, flags)
    await env.wait_int(RX_OK | RX_BAD, 400)
    raw = await env.rd(INT_RAW)
    expect(f"{name}: INT_RAW", raw & (RX_SYNC | RX_OK | RX_BAD), RX_SYNC | RX_OK)
    assert int(env.dut.irq.value), "irq not asserted"
    expect(f"{name}: descriptors", await env.rd(DESC_COUNT), 1)
    info = await env.rd(DESC_INFO)
    expect(f"{name}: descriptor length", info & 0x1FF, len(expected))
    expect(f"{name}: descriptor crc_ok", (info >> 16) & 1, 1)
    expect(f"{name}: descriptor truncated", (info >> 17) & 1, 0)
    expect(f"{name}: descriptor phy", (info >> 20) & 1, phy)
    expect(f"{name}: RX_LEVEL", await env.rd(RX_LEVEL), len(expected))
    got = bytes([await env.rd(RX_DATA) for _ in range(len(expected))])
    exp = bytearray(expected)
    if NEGATIVE:
        exp[0] ^= 0x01
    expect(f"{name}: RX_DATA octets", got.hex(), bytes(exp).hex())
    expect(f"{name}: RX_LEVEL after drain", await env.rd(RX_LEVEL), 0)
    expect(f"{name}: STATE after RX", await env.rd(STATE), 0)


@cocotb.test()
async def top_le1m_rx(dut):
    env = Env(dut)
    await env.start()
    rng = np.random.Generator(np.random.PCG64(7))
    payload = bytes(rng.integers(0, 256, 20, dtype=np.uint8).tolist())
    header0 = 0x42
    bits, _ = packet.build_frame_bits(payload, header0=header0)
    bits = bits[:40] + le1m_tx.whiten(bits[40:], 37)     # whitened on air from the PDU on
    out = cm_a.generate_packet(bits, cm_a.CmAParams(), rng)
    await configure(env, 0, 37, whiten=37)
    await rx_case(env, out.iq, out.flags, bytes([header0, len(payload)]) + payload, 0, "le1m")


@cocotb.test()
async def top_oqpsk_rx(dut):
    env = Env(dut)
    await env.start()
    payload = bytes(range(1, 19))
    iq, flags, _gain = oq_cases._loopback(oqpsk_tx.with_fcs(payload))
    await configure(env, 1, 11)
    await rx_case(env, iq, flags, payload, 1, "oqpsk")


@cocotb.test()
async def top_oqpsk_auto_ack(dut):
    """A frame addressed to this device with the ACK request set is acknowledged at
    192 us (6144 clk) after its last sample; the ACK words are the model's."""
    env = Env(dut)
    await env.start()
    pan, me = 0x1234, 0x0042
    mpdu = frame_154(0x5A, pan, me, 0x0001, b"hello")
    words = oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(mpdu))
    lead = 37
    iq = oq_cases.modulate(words, lead=lead, tail=7000 // 4)
    flags = np.zeros(len(iq), dtype=np.uint8)
    await configure(env, 1, 11)
    await env.wr(0x0D4, pan)
    await env.wr(0x0D8, me)
    await env.wr(TIMING_CTRL, 1 | 4)                    # ACK_EN
    await env.wr(INT_ENABLE, 0x3FF)
    await env.wr(CMD, CMD_RX)
    for _ in range(100):
        if await env.rd(STATE) == 1:
            break
        await ClockCycles(dut.clk, 5)
    await env.drive(iq, flags)
    await env.wait_int(0x40, 200)                        # ACK_SENT
    await env.wait_int(TX_DONE, 400)
    ack = oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(bytes([0x02, 0x00, 0x5A])))
    exp = list(ack)
    if NEGATIVE:
        exp[200] += 1
    expect("ACK word count", len(env.words), len(exp))
    for i, (g, e) in enumerate(zip(env.words, exp)):
        assert g == e, f"ACK tx_dev word {i}: got={g} expected={e}"
    end_air = env.sample_cycle[lead + len(words)]       # first sample after the last frame word
    print(f"MEASURED 15.4 end of frame (air) to rx_end {env.end_cycle - end_air} clk; "
          f"to first ACK word {env.first_tx - end_air} clk (deadline 6144 clk at 32 MHz)")
    late = env.first_tx - end_air - 6144
    assert abs(late) <= 8, f"ACK start vs the 192 us deadline: got={late} expected=0 (+/-8 clk)"
    info = await env.rd(DESC_INFO)
    expect("descriptor ack_sent flag", (info >> 19) & 1, 1)
    expect("descriptor addr_match flag", (info >> 18) & 1, 1)
    expect("STATE after ACK", await env.rd(STATE), 0)


@cocotb.test()
async def top_oqpsk_filter_reject_dropped(dut):
    """A CRC-good frame the address filter rejects raises RX_DONE_BAD but leaves no octets
    and no descriptor; the accepted frame after it is the only thing the host sees."""
    env = Env(dut)
    await env.start()
    pan, me = 0x1234, 0x0042
    await configure(env, 1, 11)
    await env.wr(0x0D4, pan)
    await env.wr(0x0D8, me)
    await env.wr(INT_ENABLE, RX_SYNC | RX_OK | RX_BAD)

    async def receive(mpdu, seed):
        words = oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(mpdu))
        iq = oq_cases.modulate(words, lead=37, tail=200)
        await env.wr(INT_RAW, RX_SYNC | RX_OK | RX_BAD)
        await env.wr(CMD, CMD_RX)
        for _ in range(100):
            if await env.rd(STATE) == 1:
                break
            await ClockCycles(dut.clk, 5)
        await env.drive(iq, np.zeros(len(iq), dtype=np.uint8), seed=seed)
        await env.wait_int(RX_OK | RX_BAD, 400)
        return await env.rd(INT_RAW)

    rejected = frame_154(0x11, pan, me + 1, 0x0001, b"not for me")
    raw = await receive(rejected, 1)
    expect("reject: INT_RAW", raw & (RX_OK | RX_BAD), RX_BAD)
    expect("reject: descriptors", await env.rd(DESC_COUNT), 0)
    expect("reject: RX_LEVEL", await env.rd(RX_LEVEL), 0)

    accepted = frame_154(0x22, pan, me, 0x0001, b"for me")
    raw = await receive(accepted, 2)
    expect("accept: INT_RAW", raw & (RX_OK | RX_BAD), RX_OK)
    expect("accept: descriptors", await env.rd(DESC_COUNT), 1)
    info = await env.rd(DESC_INFO)
    expect("accept: length", info & 0x1FF, len(accepted))
    expect("accept: addr_match", (info >> 18) & 1, 1)
    expect("accept: RX_LEVEL", await env.rd(RX_LEVEL), len(accepted))
    got = bytes([await env.rd(RX_DATA) for _ in range(len(accepted))])
    exp = bytearray(accepted)
    if NEGATIVE:
        exp[0] ^= 0x01
    expect("accept: RX_DATA octets", got.hex(), bytes(exp).hex())


@cocotb.test()
async def top_le1m_response(dut):
    """An accepted LE packet is answered from the TX FIFO at T_IFS (4800 clk at
    32 MHz) after its last bit; the response words are the model's."""
    env = Env(dut)
    await env.start()
    rng = np.random.Generator(np.random.PCG64(11))
    payload = bytes(rng.integers(0, 256, 12, dtype=np.uint8).tolist())
    bits, _ = packet.build_frame_bits(payload, header0=0x42)
    nbits = len(bits)
    bits = bits[:40] + le1m_tx.whiten(bits[40:], 37)
    out = cm_a.generate_packet(bits, cm_a.CmAParams(), rng)
    resp = bytes.fromhex("4206") + bytes(range(0xA0, 0xA6))
    await configure(env, 0, 37, whiten=37)
    await env.wr(TIMING_CTRL, 2 | 4)                    # RESP_EN, CRC_GATE
    await env.wr(INT_ENABLE, 0x3FF)
    await env.wr(TX_LENGTH, len(resp))
    for b in resp:
        await env.wr(TX_DATA, b)
    await env.wr(CMD, CMD_RX)
    for _ in range(100):
        if await env.rd(STATE) == 1:
            break
        await ClockCycles(dut.clk, 5)
    await env.drive(out.iq, out.flags)
    await env.wait_int(0x100, 200)                       # RESPONSE_SENT
    await env.wait_int(TX_DONE, 200)
    exp = list(le1m_tx.tx_dev_words(resp, 37))
    if NEGATIVE:
        exp[100] += 1
    expect("response word count", len(env.words), len(exp))
    for i, (g, e) in enumerate(zip(env.words, exp)):
        assert g == e, f"response tx_dev word {i}: got={g} expected={e}"
    end_air = env.sample_cycle[out.packet_start + 8 * nbits]
    print(f"MEASURED LE 1M end of packet (air, +/-4 clk) to rx_end {env.end_cycle - end_air} clk; "
          f"to first response word {env.first_tx - end_air} clk (T_IFS 4800 clk at 32 MHz)")
    late = env.first_tx - end_air - 4800
    assert abs(late) <= 16, f"response start vs T_IFS: got={late} expected=0 (+/-16 clk)"
    info = await env.rd(DESC_INFO)
    expect("descriptor crc_ok", (info >> 16) & 1, 1)
    await env.wr(CMD, CMD_ABORT)
    await ClockCycles(dut.clk, 20)
    expect("STATE after abort", await env.rd(STATE), 0)
