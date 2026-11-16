# L_rx / L_tx / L_dig measured at baseband_top — record

Append-only evidence for the timing-and-area section 3 latency bounds
(issue #122). Every number below is **simulated at RTL level, 32 MHz
(31.25 ns/cycle), cycle counts only** — no wall-clock or post-route claim,
front-end group delay `D_fe` excluded (section 3). Produced by
`make test-top-latency` (`verification/top/test_latency.py` through
`verification/top/run_latency.py`, full-top Icarus build from
`rtl/baseband.f`); the raw per-packet numbers of each run land in the
gitignored `<build dir>/latency.json`. Do not edit recorded sections; append
a new dated section per run.

## Definitions used (readings of section 3, stated per issue #122)

1. **`L_tx` reference point.** Measured from the **TX-command strobe**
   (`resp_tx_req` for the LE timed response, `ack_tx_req` for the 15.4
   automatic ACK, `cmd_tx_start` for the host-commanded path) to the first
   `tx_valid` word. The literal "decision cycle" reading — `ev_end` to the
   first word — is the whole programmed turnaround on the timed paths
   (4800 clk LE, 6144 clk 15.4) and exceeds the `L_tx` bound by
   construction; section 3's own rationale bounds the quantity the timer
   compensates for ("the timer fires the TX command early by
   `L_tx + T_settle`"). All four reference points (`ev_end`, `resp_tx_req`,
   `ack_tx_req`, `cmd_tx_start`) are top-level wires of `baseband_top`.
2. **Spread bound.** Enforced on **spread(`L_dig`)** (max − min over the
   matrix); spread(`L_rx`) and spread(`L_tx`) are recorded as evidence.
   `L_dig = L_rx + L_tx` makes spread(`L_dig`) ≤ spread(`L_rx`) +
   spread(`L_tx`), so the enforced bound is the binding one.
3. **Air-end reference** ("the rx_valid strobe that carries the last sample
   of the final received bit/chip"). LE 1M: receiver-grid index
   `packet_stop − 16` of the CM-A output — `packet_stop` is the
   deterministic, timing/clock-corrected end of the shaped waveform, 16
   samples is the group delay of its 33-tap Gaussian filter (GAUSS_SPAN=4,
   SPS=8); the index the integration bench prints
   (`packet_start + 8*nbits`) sits ~16 samples (~64 clk) before the
   group-delay-corrected end of the final bit. 15.4: the last frame word's
   sample, `lead + len(words) − 1` (each tx_dev word is one sample of the
   ideal loopback; no filter tail).

## Bounds checked (section 3 converted at 32 MHz)

| PHY | `L_rx` ≤ | `L_tx` ≤ | `L_dig` ≤ | spread(`L_dig`) ≤ |
|---|---|---|---|---|
| LE 1M | 192 clk | 128 clk | 320 clk | 32 clk |
| 802.15.4 | 512 clk | 512 clk | 1024 clk | 128 clk |

The bench fails if any component maximum, the `L_dig` maximum or
spread(`L_dig`) exceeds these, and the host-commanded `L_tx` against the
`L_tx` bound. `LATENCY_NEGATIVE=1` tightens the LE `L_dig` bound below the
measurement and must fail with `expected=` (negative control below).

## 2026-11-15 — first recorded run (issue #122)

- Base: `origin/main` @ `978fa3f17e49`; bench, runner and harness as
  introduced by the commit that carries this record (the only diff:
  `verification/top/{top_env,test_latency,run_latency,test_top}.py`,
  `Makefile`, `.github/workflows/flow.yml`, READMEs, this file).
- Tools: Icarus Verilog 13.0 (v13_0), cocotb 2.0.1, numpy 1.26.4,
  Python 3.12.4. Noiseless stimulus (CM-A `ebn0_db = inf`, `clock_ppm = 0`;
  the 15.4 ideal loopback).
- Matrix, 6 packets per PHY over the shared stimulus: at the short length,
  2 strobe-jitter seeds (`env.drive` seed 1, 2: ±1 clk per strobe on the
  4-clk grid) × 2 timing phases; then the mid length and the maximum.
  - LE 1M timed response (`TIMING_CTRL.RESP_EN|CRC_GATE`), PDU = 2 header +
    payload: `(pdu 2, cm seed 11, j 1) (2, 12, 1) (2, 11, 2) (2, 12, 2)
    (22, 11, 1) (257, 11, 1)`; the CM seed draws the timing phase
    (`cm_a.generate_packet`, `timing = rng.uniform(0, SPS)`); response PDU
    `4206 A0..A5`; channel 37, whitened as on air.
  - 15.4 automatic ACK (`TIMING_CTRL.ACK_EN|CRC_GATE`), PSDU = MPDU
    (`frame_154`, 9 header octets + payload) + FCS:
    `(payload 1, lead 37, j 1) (1, 41, 1) (1, 37, 2) (1, 41, 2)
    (9, 37, 1) (116, 37, 1)` → PSDU 12 / 20 / 127 octets (the 20 is the
    golden PSDU size; the 127 the maximum); PAN 0x1234, short addr 0x0042,
    channel 11.
  - One host-commanded TX per PHY (LE golden 11-octet PDU; 15.4 18-octet
    payload) for the `cmd_tx_start` path's `L_tx`.
- Measured, clk at 32 MHz (min/max/spread over the 6 packets per PHY):

| PHY | `L_rx` min/max | spread | `L_tx` min/max | spread | `L_dig` min/max | spread | host-TX `L_tx` |
|---|---|---|---|---|---|---|---|
| LE 1M | 64 / 73 | 9 | 5 / 5 | 0 | 69 / 78 | 9 | 25 |
| 802.15.4 | 37 / 38 | 1 | 5 / 6 | 1 | 42 / 43 | 1 | 45 |

- **Verdict: pass.** Every component maximum and spread(`L_dig`) is inside
  the section 3 bounds with wide margin (LE `L_dig` 78 of 320; 15.4 43 of
  1024; spreads 9 and 1 of 32 and 128).
- Negative control: `LATENCY_NEGATIVE=1` (LE test only) tightened the LE
  `L_dig` bound to `min − 1 = 68`; the run failed with
  `le1m L_dig max: got=78 expected=<=68` and the Makefile target reported
  the rejection — the bound check fires.
- Runtime, this host (8 vCPU, one job): `make test-top-latency` sim 158 s
  (LE 31.7 s, 15.4 125.9 s, cocotb REAL TIME) plus the ~2.5 min Icarus
  build; `test-top-latency-negative` runs the LE test only (~2 min total).

### Observations (no bound breached; recorded, not acted on)

- The committed `LE_L_DIG_CYCLES = 139` (`rtl/top/README.md`) was derived
  from the ~64-clk-early air-end reference; the measured true
  `L_dig` is 69–78. The timer therefore fires the LE response
  `139 − L_dig = 61–70 clk` earlier than T_IFS when T_IFS is referenced to
  the group-delay-corrected end of the final bit — at the top of the
  measured range this straddles the ±64-cycle T_IFS tolerance quoted in
  `mac_le_resp.v`. The integration bench's ±16 clk deadline assert passes
  against its own (early) reference. `OQ_L_DIG_CYCLES = 41` matches the
  measured 15.4 `L_dig` (42–43) within 2 clk. Changing `L_DIG_CYCLES` or
  the air-end convention is out of scope for #122 (no section 3 bound
  moves); a follow-up issue should decide whether the LE reference in
  `test_top.py` should move to the group-delay-corrected end and whether
  139 should be retuned to match.
- 2026-11-16, resolved by issue #145 (simulated at RTL level, 32 MHz): the
  LE air-end reference in `verification/top/test_top.py` moved to the
  group-delay-corrected end (`packet_stop - 16`, the same index this bench
  uses) and `LE_L_DIG_CYCLES` was retuned 139 → 74, the `make test-top`
  one-packet `L_dig` under the new reference (68 `L_rx` + 6 `L_tx`),
  inside the 69–78 window above. The relation is
  `late = L_dig − LE_L_DIG_CYCLES`: the bench run prints the first response
  word 4800 clk after the corrected air end, i.e. `late = 74 − 74 = 0`;
  across this matrix `max|L_dig − 74| ≤ spread(L_dig) = 9 clk`
  (|74 − 69| = 5, |74 − 78| = 4), inside decision 0006's ratified
  ±64-cycle (±2 µs) LE T_IFS tolerance. The `rtl/top/README.md` table now
  carries 68/6/74 and its prose no longer says "nothing retuned"; the
  bullet above is left intact as the record of the pre-#145 state.
- Spread is dominated by the strobe-grid phase, not by length: the LE
  `L_rx` range (64–73) spans the 4 short packets and the 257-octet maximum
  alike, and the 15.4 spread is 1 clk. This matches section 3's rationale
  (latency must be repeatable; the jitter column guards the timer's
  early-fire margin).
