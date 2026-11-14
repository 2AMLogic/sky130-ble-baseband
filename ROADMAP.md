# Roadmap

A digital baseband (LE 1M GFSK and IEEE 802.15.4 O-QPSK modems plus the
time-critical lower MAC) on sky130 `sky130_fd_sc_hd`, taken through the
klayout-tools T1 checklist with every claim tied to a recorded result.

Status as of 2026-11-13, `main` @ `23a22bc`. The per-item ledger is issue #5;
the verdict of record is `manifests/sky130-ble-baseband.signoff.json`.
`WORK_PLAN.md` is the generated label view and `WORK_LOG.md` the merge history.

## Where it stands

On the README's maturity ladder:

| Step | State | Evidence |
|---|---|---|
| Spec ratified | done, revision 1 | `spec/`, decisions 0001-0008 |
| Reference receiver meets error-rate targets | **not shown** | models, CM-A channel and both sweep drivers exist (`sim/`); no full sweep result is committed (`sim/results/` does not exist) |
| RTL bit-exact against the reference | done per block, in simulation | trace-replay benches with negative controls for LE 1M TX/RX and O-QPSK TX/RX (`verification/`, PRs #61, #64, #66); `baseband_top` integrated (PR #74) |
| Turnaround timing verified | partial | `make test-top` measures the latencies behind `L_DIG_CYCLES` on one noiseless packet per test (`rtl/top/README.md`); the spread over the shared stimulus that `spec/timing-and-area.md` section 3 asks for is not measured |
| Layout DRC/LVS clean, timing closed | not started | `layout/` is empty; no netlist exists to place |

On the T1 checklist (`klt signoff`, klayout-tools 0.8.0): 1 of 11 items met.

| Item | Verdict | What is missing | Issue |
|---|---|---|---|
| 1 Design sources | unmet | RTL is complete (#48, #50, #51, #53, #54 closed); the gate-level netlist and the item-1 attestation are not | #37, #52, #72 |
| 2 Layout | unmet | P&R flow and routed GDS | #39 |
| 3 DRC, 4 LVS | unmet | need item 2 | #40, #41 |
| 5 Corner verification | unmet | STA at the six Used corners; functional-verification report | #42 |
| 6 Monte Carlo | unmet | full BER and PER sweeps, then `klt yield` evidence | #43, #55, #56, #57 |
| 7 Post-layout | unmet | SDF-annotated re-run | #44 |
| 8 Characterization | unmet | needs items 5-7 | #45 |
| 9 Testbenches shipped | unmet | benches are on `main`; no inventory, no attestation | #38 |
| 10 Repo hygiene | **met** | `manifests/item10-attestation.json` | #46 (closed) |
| 11 Power delivery | unmet | needs item 2 | #47 |

The one hard blocker is synthesis (#72). A flat Yosys run of `baseband_top` was
stopped after 45 minutes; `SYNTH_MODE=hier` did not finish in 300 s; two leaves,
`oqpsk_rx_corr` and `le1m_rx_sync`, time out in generic `synth` on their own
(`flow/synth/README.md`, `flow/synth/records/`). Halving the correlator adders
(#106, PR #107) did not bring `oqpsk_rx_corr` under 300 s. Items 2, 3, 4, 5, 7,
8 and 11 all wait behind the netlist.

## Now

1. **Dedupe the BER/PER sweep drivers** (#116, ready). Done when one shared
   module beside `sim/sweep/` holds the CLI, stop rule, row verdict and report
   envelope, both drivers import it, and `make sim-test sim-quick` pass with
   the `<=` (BER) and `<` (PER) row verdicts unchanged.
2. **Full 802.15.4 PER sweep committed** (#56, in progress). Done when
   `sim/results/<date>-<sha>/per.json` is committed from a non-quick run with
   the negative control's `fails_row` true. Needs a batch job, not a shared
   worker (`sim/README.md`).
3. **Item 9 inventory and attestation for the benches on `main`** (no issue;
   child of #38). Done when an item-9 inventory lists every committed bench
   with its cold-start command and pins, `klt signoff --attest 9` passes, CI
   runs `--check`, and the signoff record reads item 9 `met`. #38 is parked on
   #37, but the RTL it waited for has landed.
4. **Measure the turnaround latency spread** (no issue). Done when a top-level
   bench records `L_rx`, `L_tx` and max-minus-min in `clk` cycles over the
   shared stimulus set for both PHYs and fails if any exceeds the bounds in
   `spec/timing-and-area.md` section 3 (LE 320 cycles, 802.15.4 1024 cycles at
   32 MHz, plus the jitter column), with a negative control.
5. **Record where Yosys spends its time in the two slow leaves** (no issue;
   feeds #72). Done when `flow/synth/records/<date>/` holds per-pass timing
   logs for `oqpsk_rx_corr` and `le1m_rx_sync`, plus one bounded run of each
   with the generic ABC pass skipped, and `flow/synth/README.md` names the
   pass that dominates. No RTL change.
6. **Correct the README's "Current position" sentence** (no issue). It still
   says "No block RTL yet", contradicting the status line above it. Done when
   the sentence matches the ladder table here and item 10 is re-attested
   (the attestation pins the README hash).

## Next

- **A netlist-producing synthesis route** (#72). Unblocked by Now 5 or by a
  completed batch run. Done when `make synth` finishes on the pinned Yosys and
  `make synth-check` reproduces the committed netlist. Open point from the
  #72 batch attempt: the batch image carried Yosys 0.68, not the pinned 0.67,
  so a netlist from it may not reproduce under `synth-check`.
- **Restructure `le1m_rx_sync` and, if still needed, `oqpsk_rx_corr`,
  bit-exactly** (no issue). After Now 5 names the cost. Done when both profile
  rows read `ok` at the 120 s timeout and the replay benches and negative
  controls pass unchanged. `le1m_rx_sync` carries its 40-tap metric in 32-bit
  arithmetic on 19-bit samples; narrowing is the first candidate.
- **Item 1 closed** (#52, then #37). After the netlist: item-1 inventory,
  `klt signoff --attest 1`, record regenerated with item 1 `met`.
- **Full LE 1M BER sweeps committed** (#55). Parked on batch capacity with a
  retry record. Done when `ber.json` is merged from the five shards
  (`le1m_cfo`, `le1m_drift`, `le1m_clock`, `le1m_uniform`, `negative_control`)
  at the ratified packet caps.
- **Item 6 evidence** (#57, then #43). After #55 and #56: `klt yield` reports
  for the BER and PER rows, `spec_rows` declared in the manifest.
- **Place and route** (#39). After item 1. Done when a committed OpenROAD flow
  regenerates a routed GDS of `baseband_top`.

## Later

- **DRC, LVS, power delivery** (#40, #41, #47). Question first: does the
  routed block fit the area budget in `spec/timing-and-area.md` section 4,
  which is an estimate made before any synthesis result?
- **Corner STA at 32 MHz** (#42). Question first: does RTL written for
  bit-exactness close at `ss_n40C_1v60`, or is the 16 MHz fallback the honest
  claim?
- **Post-layout re-run and characterization report** (#44, #45). Question
  first: can the replay benches take a netlist and SDF without a second
  harness (#38 asked for the cold-start command to stay parameterizable)?
- **Deferred RTL features**: AGC (`agc_gain` is fixed mid-scale), the RSSI dB
  mapping and the 4 Msps fallback (`rtl/README.md`). Question first for each:
  does the ratified spec require it for the target row, or only for a fallback?

## Blocked and waiting

- **#72** carries `loom:operator`: it needs either batch capacity long enough
  for a flat run or a ruling on the synthesis strategy and on whether a
  multi-megabyte committed netlist is acceptable. Now 5 narrows that choice
  without waiting for it.
- **#55** and **#56** depend on batch compute outside this repo; earlier
  submissions were refused before any sweep ran.

Dispatchable today: #116 and #56 on the tracker; Now 3-6 once filed.

## Not planned

- An RF front end, ADC, DAC or synthesizer; this repo stops at the digital
  interface (`spec/frontend-interface.md`).
- The upper link layer and protocol stacks.
- LE 2M and coded PHY before the LE 1M + 802.15.4 target closes.
- Any qualification, certification or standards-compliance claim (`CLAUDE.md`).
