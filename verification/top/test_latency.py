"""cocotb latency bench for rtl/top/baseband_top.v (spec/timing-and-area.md section 3).

Measures, per PHY and over a matrix of model-generated packets (issue #122),
in clk cycles at 32 MHz, simulated at RTL level, cycle counts only:

  L_rx  : the `rx_valid` strobe carrying the last sample of the final
          bit/chip, to the cycle the end-of-packet decision (`ev_end`) fires.
  L_tx  : the TX-command strobe to the first `tx_valid` word.
  L_dig : L_rx + L_tx.

and records min / max / max-minus-min over the matrix (section 3's jitter
column is max minus min over all packets and offsets). The bench fails if a
component maximum, the `L_dig` maximum or spread(`L_dig`) exceeds the
section 3 bounds converted at 32 MHz (LE 192/128/320/32 clk, 15.4
512/512/1024/128 clk). All four reference points are top-level wires of
`baseband_top`: `ev_end`, `resp_tx_req`, `ack_tx_req`, `cmd_tx_start`.

Two readings of section 3 are ambiguous; this bench records the readings it
uses (also in verification/top/latency_record.md), without editing section 3:

  1. `L_tx` is measured from the TX-command strobe (`resp_tx_req` /
     `ack_tx_req`, and `cmd_tx_start` on the host-commanded path), not from
     the literal "decision cycle": on the timed paths the interval
     `ev_end` -> first word is the whole programmed turnaround (4800 clk LE,
     6144 clk 15.4) that the MAC timer deliberately spends waiting, which
     exceeds the `L_tx` bound by construction. Section 3's own rationale
     bounds the quantity the timer compensates for: "the timer fires the TX
     command early by `L_tx + T_settle`".
  2. The spread bound applies to spread(`L_dig`); spread(`L_rx`) and
     spread(`L_tx`) are recorded as evidence. `L_dig = L_rx + L_tx` makes
     spread(`L_dig`) <= spread(`L_rx`) + spread(`L_tx`), so the enforced
     bound is the binding one.

Air-end reference ("the rx_valid strobe that carries the last sample of the
final received bit/chip"): LE 1M uses receiver-grid index
`packet_stop - 16` of the CM-A output — `packet_stop` is the deterministic,
timing/clock-corrected end of the shaped waveform, 16 samples is the group
delay of its 33-tap Gaussian filter (GAUSS_SPAN=4, SPS=8), and the index the
integration bench prints (`packet_start + 8*nbits`) sits ~16 samples (~64
clk) before the group-delay-corrected end of the final bit. 15.4 uses the
last frame word's sample, `lead + len(words) - 1` (each tx_dev word is one
sample of the ideal loopback; it has no filter tail).

Matrix (6 packets per PHY, sized for CI): at the short length, 2 strobe-jitter
seeds x 2 arrival-phase variants; then a mid length and the maximum length.
The two variants differ per PHY: LE 1M gets 2 timing phases (the CM-A channel
model draws sub-sample `timing` per seed); 802.15.4 gets 2 strobe-jitter
alignments (its ideal loopback has no sub-sample phase knob — see the
OQ_MATRIX comment). Spread is driven by jitter (and, for LE, phase), not by
length, so length varies separately.
LE 1M drives the timed response (TIMING_CTRL.RESP_EN) on PDUs of 2 / 22 / 257
octets; 802.15.4 drives the automatic ACK (TIMING_CTRL.ACK_EN) on PSDUs of
12 / 20 / 127 octets (the maximum, and the golden 20-octet shape; the 9-octet
MPDU header plus FCS set the floor). Only CRC-good, accepted packets are driven, so no packet
is excluded for yielding no response (a CRC-bad or filter-rejected packet
earns none). One host-commanded TX per PHY adds the `L_tx` of the
`cmd_tx_start` path, where no `L_rx` exists. The front end's `D_fe` and its
20-clk `fe_ready` model are excluded by construction: the mode switch to TX
happens at `ev_end`, 4800 / 6144 clk before the TX command fires.

Per packet the records of `Env` are reset (`Env.reset()`), the packet's FIFO
octets are drained and its descriptor popped, and the receiver is re-armed
with CMD_ABORT (CMD_RX only lands from idle), so each packet is measured on
its own. Results land in `<build_dir>/latency.json` (gitignored); the
committed evidence is verification/top/latency_record.md.

LATENCY_NEGATIVE=1 tightens the LE `L_dig` bound to the measured minimum
minus 1, so the run must fail with an `expected=` message (the Makefile
`test-top-latency-negative` target inverts the exit status and greps for it).
"""

import json
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
from top_env import (CMD, CMD_ABORT, CMD_RX, CMD_TX, DESC_COUNT,  # noqa: E402
                    DESC_POP, INT_ENABLE, INT_RAW, RX_DATA, RX_LEVEL, STATE,
                    TIMING_CTRL, TX_DATA, TX_DONE, TX_LENGTH, Env, configure,
                    expect, frame_154)

NEGATIVE = os.environ.get("LATENCY_NEGATIVE") == "1"
JSON_PATH = os.environ.get("LATENCY_JSON", "latency.json")

# spec/timing-and-area.md section 3, converted to clk at 32 MHz: the µs bounds
# divided by the 31.25 ns clock period.
BOUNDS = {
    "le1m":  {"rx": 192, "tx": 128, "dig": 320, "spread": 32},
    "oqpsk": {"rx": 512, "tx": 512, "dig": 1024, "spread": 128},
}

# (pdu_octets, cm_seed, drive_seed): the PDU is the 2 header octets plus the
# payload; the cm seed draws the timing phase (cm_a.generate_packet draws
# timing = rng.uniform(0, SPS)), the drive seed the +/-1 clk strobe jitter.
LE_MATRIX = [
    (2, 11, 1), (2, 12, 1), (2, 11, 2), (2, 12, 2),
    (22, 11, 1),
    (257, 11, 1),
]

# (payload_octets, lead, drive_seed): PSDU = MPDU (frame_154: 9 header octets
# + payload) + FCS, so the shapes are PSDU 12 / 20 / 127 octets - the 20 is
# the golden PSDU size (payload 9), the 127 the maximum (payload 116). The
# two leads (37, 41) are NOT a timing-phase axis: they differ by 4 samples =
# one chip (SPS_CHIP) = 16 clk = 4x the 4-clk strobe period, so the frame's
# alignment to both the chip grid and the strobe grid is unchanged across the
# pair. modulate(lead=) prepends whole zero samples and every sample strobes
# on the same 4-clk grid, so no integer lead can vary sub-sample arrival
# phase. What differs is which +/-1 clk jitter draws land on which frame
# samples (drive() indexes the jitter sequence by absolute sample number),
# so the pair is a second strobe-jitter alignment; the ideal loopback offers
# no sub-sample timing phase.
OQ_MATRIX = [
    (1, 37, 1), (1, 41, 1), (1, 37, 2), (1, 41, 2),
    (9, 37, 1),
    (116, 37, 1),
]

RESPONSE_PDU = bytes.fromhex("4206") + bytes(range(0xA0, 0xA6))   # as test_top
RESULTS = {"le1m": None, "oqpsk": None}


def stats(values):
    return {"min": min(values), "max": max(values),
            "spread": max(values) - min(values)}


def check_bound(name, got, bound):
    assert got <= bound, f"{name}: got={got} expected=<={bound}"


def write_json():
    with open(JSON_PATH, "w") as f:
        json.dump({"clock_mhz": 32, "level": "RTL simulation, cycle counts only",
                   "negative": NEGATIVE, "le1m": RESULTS["le1m"],
                   "oqpsk": RESULTS["oqpsk"]}, f, indent=1)


async def wait_state(env, want, limit):
    for _ in range(limit):
        if await env.rd(STATE) == want:
            return
        await ClockCycles(env.dut.clk, 40)
    raise AssertionError(f"timeout waiting for STATE == {want}")


async def start_rx(env):
    await env.wr(INT_RAW, 0x3FF)                     # clear the latched events
    await env.wr(CMD, CMD_RX)                        # only lands from idle
    await wait_state(env, 1, 100)
    assert int(env.dut.fe_rx_en.value) and not int(env.dut.fe_tx_en.value)


async def stop_rx(env):
    await env.wr(CMD, CMD_ABORT)                     # cancels the MAC windows too
    await ClockCycles(env.dut.clk, 20)
    await wait_state(env, 0, 100)


async def drain(env, n_octets, name):
    got = bytes([await env.rd(RX_DATA) for _ in range(n_octets)])
    expect(f"{name}: RX_LEVEL after drain", await env.rd(RX_LEVEL), 0)
    await env.wr(DESC_POP, 1)
    expect(f"{name}: descriptors after pop", await env.rd(DESC_COUNT), 0)
    return got


async def host_tx(env, pdu):
    """Host-commanded TX: returns L_tx of the cmd_tx_start path (no L_rx).

    With the timed-response / auto-ACK enables set, the state machine
    re-arms RX after the TX (rtl/top/README.md item 5), so the flow ends
    with CMD_ABORT to return to idle, exactly like the timed flows.
    """
    await env.wr(TX_LENGTH, len(pdu))
    for b in pdu:
        await env.wr(TX_DATA, b)
    env.reset()
    await env.wr(CMD, CMD_TX)
    await env.wait_int(TX_DONE, 20000)               # a max-length frame is ~150k clk
    l_tx = env.first_tx - env.cmd_cycle["host"]
    await env.wr(CMD, CMD_ABORT)
    await ClockCycles(env.dut.clk, 20)
    await wait_state(env, 0, 200)
    return l_tx


def report(phy, host_l_tx, packets):
    rx = stats([p["L_rx"] for p in packets])
    tx = stats([p["L_tx"] for p in packets])
    dig = stats([p["L_dig"] for p in packets])
    print(f"MEASURED {phy} over {len(packets)} packets, clk @ 32 MHz: "
          f"L_rx min/max/spread {rx['min']}/{rx['max']}/{rx['spread']}, "
          f"L_tx {tx['min']}/{tx['max']}/{tx['spread']}, "
          f"L_dig {dig['min']}/{dig['max']}/{dig['spread']}; "
          f"host-TX L_tx {host_l_tx}")
    RESULTS[phy] = {"packets": packets, "stats": {"rx": rx, "tx": tx, "dig": dig},
                    "host_tx_L_tx": host_l_tx}
    bound = dict(BOUNDS[phy])
    if NEGATIVE and phy == "le1m":                   # tightened below the measurement
        bound["dig"] = dig["min"] - 1
    check_bound(f"{phy} L_rx max", rx["max"], bound["rx"])
    check_bound(f"{phy} L_tx max", tx["max"], bound["tx"])
    check_bound(f"{phy} host-TX L_tx", host_l_tx, bound["tx"])
    check_bound(f"{phy} L_dig max", dig["max"], bound["dig"])
    check_bound(f"{phy} spread(L_dig)", dig["spread"], bound["spread"])


@cocotb.test()
async def latency_le1m(dut):
    """LE 1M: L_rx / L_tx / L_dig over the matrix, against the section 3 bounds."""
    env = Env(dut)
    await env.start()
    await configure(env, 0, 37, whiten=37)
    await env.wr(TIMING_CTRL, 2 | 4)                 # RESP_EN, CRC_GATE
    await env.wr(INT_ENABLE, 0x3FF)
    host_l_tx = await host_tx(env, bytes.fromhex("4209010203040506020106"))

    packets = []
    for pdu_len, cm_seed, drive_seed in LE_MATRIX:
        name = f"le1m pdu={pdu_len} cm={cm_seed} jitter={drive_seed}"
        rng = np.random.Generator(np.random.PCG64(cm_seed))
        payload = bytes(rng.integers(0, 256, pdu_len - 2, dtype=np.uint8).tolist())
        bits, _ = packet.build_frame_bits(payload, header0=0x42)
        bits = bits[:40] + le1m_tx.whiten(bits[40:], 37)   # whitened on air from the PDU on
        out = cm_a.generate_packet(bits, cm_a.CmAParams(), rng)
        await env.wr(TX_LENGTH, len(RESPONSE_PDU))
        for b in RESPONSE_PDU:
            await env.wr(TX_DATA, b)
        env.reset()
        await start_rx(env)
        await env.drive(out.iq, out.flags, seed=drive_seed)
        await env.wait_int(0x100, 200)               # RESPONSE_SENT
        await env.wait_int(TX_DONE, 200)
        l_rx = env.end_cycle - env.sample_cycle[out.packet_stop - 16]
        l_tx = env.first_tx - env.cmd_cycle["resp"]
        got = await drain(env, pdu_len, name)
        expect(f"{name}: octets", got.hex(), (bytes([0x42, pdu_len - 2]) + payload).hex())
        await stop_rx(env)
        packets.append({"pdu_octets": pdu_len, "cm_seed": cm_seed, "drive_seed": drive_seed,
                        "L_rx": l_rx, "L_tx": l_tx, "L_dig": l_rx + l_tx})
    report("le1m", host_l_tx, packets)
    write_json()


@cocotb.test()
async def latency_oqpsk(dut):
    """802.15.4: L_rx / L_tx / L_dig over the matrix, against the section 3 bounds."""
    env = Env(dut)
    await env.start()
    pan, me = 0x1234, 0x0042
    await configure(env, 1, 11)
    await env.wr(0x0D4, pan)
    await env.wr(0x0D8, me)
    await env.wr(TIMING_CTRL, 1 | 4)                 # ACK_EN, CRC_GATE
    await env.wr(INT_ENABLE, 0x3FF)
    host_l_tx = await host_tx(env, bytes(range(1, 19)))

    packets = []
    for payload_len, lead, drive_seed in OQ_MATRIX:
        name = f"oqpsk psdu={payload_len + 11} lead={lead} jitter={drive_seed}"
        rng = np.random.Generator(np.random.PCG64(200 + payload_len))
        payload = bytes(rng.integers(0, 256, payload_len, dtype=np.uint8).tolist())
        mpdu = frame_154(0x5A, pan, me, 0x0001, payload)
        words = oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(mpdu))
        iq = oq_cases.modulate(words, lead=lead)
        flags = np.zeros(len(iq), dtype=np.uint8)
        env.reset()
        await start_rx(env)
        await env.drive(iq, flags, seed=drive_seed)
        await env.wait_int(0x40, 200)                # ACK_SENT
        await env.wait_int(TX_DONE, 400)
        l_rx = env.end_cycle - env.sample_cycle[lead + len(words) - 1]
        l_tx = env.first_tx - env.cmd_cycle["ack"]
        got = await drain(env, len(mpdu), name)
        expect(f"{name}: octets", got.hex(), mpdu.hex())
        await stop_rx(env)
        packets.append({"psdu_octets": payload_len + 11, "lead": lead,
                        "drive_seed": drive_seed,
                        "L_rx": l_rx, "L_tx": l_tx, "L_dig": l_rx + l_tx})
    report("oqpsk", host_l_tx, packets)
    write_json()
