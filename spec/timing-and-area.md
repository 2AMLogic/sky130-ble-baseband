# Timing, area and digital latency

Status: **RATIFIED with the target spec** (revision 1; see
[decision 0008](decisions/0008-ratification-and-amendment.md) for the scope,
the open items and the amendment rule). Parent #2, issue #9.

Nothing in this file is a measured or synthesized result. There is no RTL yet,
so every number is a **requirement** the flow must meet or an **estimate**
labelled as one. A result that misses a requirement is recorded as a miss; it
does not edit the requirement.

## 1. Library corners

All `sky130_fd_sc_hd` Liberty corners and the supply range they cover. The set
below was read from one host install of the PDK (open_pdks
`f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7`, `libs.ref/sky130_fd_sc_hd/lib`,
16 files plus `*_ccsnoise` variants). **#3 has not pinned the PDK yet**, so the
file list is **unverified against the pin**; re-check it when #3 lands (an
editorial amendment, decision 0008).

Operating supply: **1.8 V nominal, 1.62 V to 1.98 V** (±10 %), junction
temperature −40 °C to 100 °C. This is this repo's engineering choice for a
digital-only block, not a citation.

| Corner (file suffix) | Process | V | T (°C) | Used | Role |
|---|---|---|---|---|---|
| `ss_n40C_1v60` | slow | 1.60 | −40 | yes | **Setup, binding (a priori)** |
| `ss_100C_1v60` | slow | 1.60 | 100 | yes | Setup |
| `tt_025C_1v80` | typical | 1.80 | 25 | yes | Typical reference; nominal-power basis |
| `tt_100C_1v80` | typical | 1.80 | 100 | yes | Typical, hot |
| `ff_n40C_1v95` | fast | 1.95 | −40 | yes | Hold |
| `ff_100C_1v95` | fast | 1.95 | 100 | yes | **Hold, binding (a priori)** |
| `ss_n40C_1v76`, `ff_n40C_1v76` | slow, fast | 1.76 | −40 | no | Inside the supply range but dominated by the 1.60 V / 1.95 V corners above for the same process |
| `ss_n40C_1v44`, `ss_n40C_1v40`, `ss_n40C_1v35`, `ss_n40C_1v28`, `ss_100C_1v40` | slow | 1.28–1.44 | −40 / 100 | no | Supply below the stated operating range |
| `ff_n40C_1v56`, `ff_n40C_1v65`, `ff_100C_1v65` | fast | 1.56–1.65 | −40 / 100 | no | Supply below the stated operating range; the fast process is not the limit there |

"All corners" in the README clock row means every corner in the **Used**
column. Narrowing the operating range, or adding a corner, is a substantive
amendment (it changes what a timing claim covers).

**Binding corner (a priori, to be replaced by STA).** Declared before RTL
exists from a single-arc probe of the host library: `nand2_1` `cell_rise`, the
middle entry of the delay table (index 3,3), in each Liberty file. Results in
ns: `ss_n40C_1v60` 0.318, `ss_100C_1v60` 0.260, `tt_025C_1v80` 0.128,
`tt_100C_1v80` 0.119, `ff_n40C_1v95` 0.112, `ff_100C_1v95` 0.099. At 1.60 V the
cold corner is slower than the hot one (temperature inversion), hence
`ss_n40C_1v60` for setup, and `ff_100C_1v95` is the fastest, hence hold. One
arc of one cell is a prior, not a result: once an STA run exists the binding
corner is the corner with the least slack, and that name replaces this one by
editorial amendment. Hold violations are fixed by the flow, never by relaxing a
requirement.

## 2. Clock targets

| Item | Target | Fallback | Corner binding the claim | Verification |
|---|---|---|---|---|
| Core clock `clk` | 32 MHz (31.25 ns) | 16 MHz (62.5 ns) | **Setup: every Used corner; binding `ss_n40C_1v60`.** Hold: every Used corner; binding `ff_100C_1v95`. | OpenROAD STA on the placed-and-routed netlist, per Used corner, no negative setup or hold slack; report names the corner per path group |
| Clock uncertainty | 0.25 ns setup | same | each Used corner | STA constraints file, recorded with the result |
| Gate-level timing claim | none until a post-route STA report exists | same | n/a | An RTL-only or pre-route number is labelled so and names its corner |

Every timing statement anywhere in this repo names its corner or says
"unverified". A timing result is recorded (append-only) with: flow SHA, PDK pin,
Liberty file name, constraint file, corner, worst setup and hold slack.

Falling back from 32 MHz to 16 MHz is a recorded fallback outcome, not an
amendment. It changes cycle counts (the cycle columns in
[0006](decisions/0006-lower-mac-split.md) halve) but no wall-clock
requirement below.

## 3. Digital latency `L_dig` (resolves the symbol left open by #7)

`L_dig` is defined in [frontend-interface.md](frontend-interface.md) §5.1 as the
digital latency from the last on-air bit received to the first TX word. It is
split here, measured at the block's pins (the front-end group delay `D_fe` is
**not** included; it is the front end's):

- `L_rx`: the `rx_valid` strobe that carries the last sample of the final
  received bit/chip to the cycle the baseband's end-of-packet decision (CRC
  result final, TX decision allowed) is made.
- `L_tx`: that decision cycle to the first `tx_valid` word of the response
  (preamble/SHR).

| PHY | `L_rx` ≤ | `L_tx` ≤ | `L_dig` ≤ | Cycles @ 32 MHz (@ 16 MHz) | Jitter (max − min over all packets and offsets) ≤ |
|---|---|---|---|---|---|
| LE 1M | 6 µs | 4 µs | **10 µs** | 320 (160) | 1 µs |
| 802.15.4 | 16 µs | 16 µs | **32 µs** | 1024 (512) | 4 µs |

Reasoning. The LE bound is the binding one ([frontend-interface.md](frontend-interface.md)
§5.2) and 10 µs is the figure already used in that document's worked
illustration; it spends 6.7 % of `T_IFS` = 150 µs. The LE response is a
pre-loaded packet and the Gaussian pulse-shaping pipeline must be primed ahead
of the TX start, so `L_tx` is short. 802.15.4 decides on whole 16 µs symbols
(despreading is per symbol), so `L_rx` is up to one symbol and `L_tx` up to one
symbol; the interval, 192 µs, is far looser. The
timer fires the TX command early by `L_tx + T_settle` (0006), which only works
if latency is **repeatable**: that is the jitter column. 2 µs of LE `T_IFS`
tolerance (0006, §4.1.1, unverified) is the reason the LE jitter bound is 1 µs.

Substituting into the front-end budget (§5.2 of the front-end document), with
the 10 % margin already stated there:

| PHY | `T_settle` ≤ |
|---|---|
| LE 1M | 135 µs − 10 µs − `D_fe` = **125 µs − `D_fe`** |
| 802.15.4 | 172.8 µs − 32 µs − `D_fe` = **140.8 µs − `D_fe`** |

Verification: a cocotb testbench measures `L_rx`, `L_tx` and their spread over
the shared stimulus ([0007](decisions/0007-bit-exactness.md)) in cycles of
`clk`; the µs figures above divide by the clock period at the claimed
frequency. **Simulated at RTL level, so the claim is on cycle counts, not on
post-route timing**; the cycle counts hold at either clock, the wall-clock
conversion names the clock used.

## 4. Area budget

**Everything in this section is an estimate.** Method: count the registers and
storage each function needs from the specs already ratified (not synthesized),
price flip-flops and muxes at the `sky130_fd_sc_hd` cell areas read from the
`tt_025C_1v80` Liberty file of the host install (`dfxtp_1` 20.02 µm²,
`mux2_1` 11.26 µm², `nand2_1` 3.75 µm²), and take combinational logic as roughly
equal to the register area. The multiplier of 1 for logic is a guess to be
replaced by the first synthesis result.

| Block | Registers/storage assumed | Estimate (µm²) |
|---|---|---|
| RX datapath: DC removal, channel filters, LE discriminator and timing recovery, 802.15.4 despreader (16 sequences of 32 chips) and tracker, sync correlators, AGC/RSSI | ~1500 flops + logic | 90 000 |
| TX path: Gaussian filter, O-QPSK half-sine, spreader | ~400 flops + logic | 25 000 |
| CRC-24, FCS-16, whitening, framing | ~300 flops + logic | 15 000 |
| Timers, ACK, trigger, address filter, timestamp counter | ~400 flops + logic | 25 000 |
| Host registers and interrupt logic | ~500 flops + logic | 30 000 |
| Two FIFOs, 128 octets each, flop-based (2048 bits: flops + read mux, no SRAM macro) | 2048 × (20.02 + 11.26) | 64 000 |
| **Total estimate** | | **≈ 249 000 (0.25 mm²)** |

| Budget | Value | Basis |
|---|---|---|
| Standard-cell area (post-synthesis) | ≤ 0.40 mm² | the estimate plus 60 % headroom for a method that has not met a synthesizer |
| Core area (post-placement) | ≤ 0.80 mm² | the cell budget at 50 % utilization |
| Verification | Yosys `stat` area on the synthesized netlist against the cell budget, OpenROAD report against the core budget; both at `tt_025C_1v80`, as area is not corner-dependent beyond sizing | |

No SRAM macro is assumed; moving the FIFOs to a macro, or an estimate that
exceeds the budget, is recorded as a result and the decision of what to do
(drop the fallback PHY, shrink FIFOs) is a decision record, not an edit of
this budget. Area is the tiebreaker named in [0006](decisions/0006-lower-mac-split.md)
and the input to the coherent-vs-non-coherent comparison in
[0003](decisions/0003-demod-architecture.md).

## 5. Out of scope here

Running STA or synthesis (no RTL), Monte Carlo pass/fail numbers, and the
tooling pin (#3, #4).
