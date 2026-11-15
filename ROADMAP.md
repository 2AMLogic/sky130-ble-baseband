# Roadmap

A digital baseband (LE 1M GFSK and IEEE 802.15.4 O-QPSK modems plus the
time-critical lower MAC) on sky130 `sky130_fd_sc_hd`, taken through the
klayout-tools T1 checklist with every claim tied to a recorded result.

Status as of 2026-11-15, `main` @ `4fe5b03`. The per-item ledger is issue #5;
the verdict of record is `manifests/sky130-ble-baseband.signoff.json`.
`WORK_PLAN.md` is the generated label view and `WORK_LOG.md` the merge history.

## Where it stands

On the README's maturity ladder:

| Step | State | Evidence |
|---|---|---|
| Spec ratified | done, revision 1 | `spec/`, decisions 0001-0008 |
| Reference receiver meets error-rate targets | partial — committed, misses cited | full LE 1M BER sweep committed (`sim/results/2026-11-14-88245d69b74d/ber.json`, PR #134): the uniform and clock rows meet the 1e-3 ceiling at 16 dB, the cfo (worst CP upper 1.1e-2) and drift (1.7e-3) rows miss; the O-QPSK PER sweep misses the ratified ≤ 5 dB row (`sim/results/2026-11-14-1564a0ec0cfb/per.json`, PR #138), with the crossing measured in (7.5, 8] dB and the shortfall attributed (`sim/results/oqpsk-sensitivity-budget-2026-11-15.md`, #137) |
| RTL bit-exact against the reference | done per block, in simulation | trace-replay benches with negative controls for LE 1M TX/RX and O-QPSK TX/RX (`verification/`, PRs #61, #64, #66); `baseband_top` integrated (PR #74) |
| Turnaround timing verified | measurement in review | the spread bench over the shared stimulus is open as PR #144 (#122); its early numbers sit inside the `spec/timing-and-area.md` section 3 bounds (LE `L_dig` 69-78 clk vs 320, O-QPSK 42-43 vs 1024, at 32 MHz, simulated), with the LE reference convention awaiting a decision (#145) |
| Layout DRC/LVS clean, timing closed | not started | `layout/` is empty; no netlist exists to place |

On the T1 checklist (`klt signoff`, klayout-tools 0.8.0): 2 of 11 items met
(items 9 and 10). Two caveats are tracked, not hidden: the item-10 attestation
was produced by an unpinned klt dev build (#148), and `klt signoff` is red on
`main` since the item-9 attestation drifted when #127 merged (#153, fix in
flight).

| Item | Verdict | What is missing | Issue |
|---|---|---|---|
| 1 Design sources | unmet | RTL is complete (#48, #50, #51, #53, #54 closed); the gate-level netlist and the item-1 attestation are not | #37, #52, #72 |
| 2 Layout | unmet | P&R flow and routed GDS | #39 |
| 3 DRC, 4 LVS | unmet | need item 2 | #40, #41 |
| 5 Corner verification | unmet | STA at the six Used corners; functional-verification report | #42 |
| 6 Monte Carlo | unmet | the committed LE 1M BER and O-QPSK PER rows (#55, #56 closed) miss on cfo/drift and on PER respectively; `klt yield` evidence and the campaign rows remain | #57, #43 |
| 7 Post-layout | unmet | SDF-annotated re-run | #44 |
| 8 Characterization | unmet | needs items 5-7 | #45 |
| 9 Testbenches shipped | **met** | 28/28 checks (`manifests/item9-attestation.json`, #121); sim/ reference-model benches are outside the attested inventory (#142) | #38's child #121 (closed) |
| 10 Repo hygiene | **met** | `manifests/item10-attestation.json`; produced by an unpinned klt build (#148) | #46 (closed) |
| 11 Power delivery | unmet | needs item 2 | #47 |

The one hard blocker is synthesis (#72). A flat Yosys run of `baseband_top` was
stopped after 45 minutes; `SYNTH_MODE=hier` did not finish in 300 s; two leaves,
`oqpsk_rx_corr` and `le1m_rx_sync`, time out in generic `synth` on their own
(`flow/synth/README.md`, `flow/synth/records/`). Halving the correlator adders
(#106, PR #107) did not bring `oqpsk_rx_corr` under 300 s. The #123 profile
names the cost: generic `synth`'s own ABC pass dominates both leaves (about 95 %
and 62 % of a 120 s budget), and both finish bounded with `-noabc`
(`records/2026-11-14-noabc/`). Items 2, 3, 4, 5, 7, 8 and 11 all wait behind
the netlist.

## Now

1. **Fix the LE 1M cfo BER anomaly** (#133, building). The reference receiver
   is worst at zero carrier offset and non-monotonic in Eb/N0, which is why the
   cfo row misses. Done when the model change is understood and committed, the
   affected rows are re-run from the fixed model, and either they meet the
   1e-3 ceiling or the miss is attributed as a receiver limitation with the
   spec row told so. No spec change to hide it.
2. **File the O-QPSK RX rework from #137's attribution** (no issue yet). The
   sensitivity budget maps where the roughly 3 dB against the ≤ 5 dB row goes.
   Done when the follow-up issue is filed with done-criteria tied to that row,
   so the rework competes for the queue on evidence.
3. **Merge the latency-spread bench** (#122, PR #144 in review) and settle the
   LE reference convention (#145, triage). Done when `make test-top-latency`
   is on `main` and fails on any packet outside the section 3 bounds, and the
   convention decision is recorded.
4. **Dedupe the BER/PER sweep drivers** (#116, building). Done when one shared
   module beside `sim/sweep/` holds the CLI, stop rule, row verdict and report
   envelope, both drivers import it, and `make sim-test sim-quick` pass with
   the `<=` (BER) and `<` (PER) row verdicts unchanged.
5. **Dedupe the RX moving-sum integrator** (#125, building). One parameterized
   module replaces `le1m_rx_integ` and `oqpsk_rx_integ`; done when the replay
   benches and negative controls pass bit-exactly and the synthesis profile
   rows are re-recorded, feeding #72 with less logic to place.
6. **Restore `klt signoff` green on `main`** (#153, in flight). The item-9
   attestation drifted when #127 merged. Done when the attestation matches the
   tree, CI is green, and the follow-up queue (#136, #142, #147) is
   scheduled after it.

## Next

- **A netlist-producing synthesis route** (#72). Unblocked by the #123
  profile: the dominant cost is generic `synth`'s ABC pass, `-noabc` lets both
  slow leaves finish, so the candidates are a `hier` route with per-module
  liberty mapping (`SYNTH_ABC_FAST=1`), narrowing `le1m_rx_sync`'s 32-bit
  metric arithmetic, and the #125 dedupe. Done when `make synth` finishes on
  the pinned Yosys and `make synth-check` reproduces the committed netlist.
  Open points from the #72 batch attempt: the batch image carried Yosys 0.68,
  not the pinned 0.67, so a netlist from it may not reproduce under
  `synth-check`; and on-demand capacity needs an authorization only a human
  can grant (see Blocked and waiting).
- **Item 6 evidence** (#57, then #43). The committed rows exist (#55, #56
  closed); remaining is `klt yield` evidence for them, `spec_rows` declared in
  the manifest, and the campaign rows — after the #133 re-run and the O-QPSK
  rework change the numbers being attested. #57 carries `loom:operator`.
- **Item 1 closed** (#52, then #37). After the netlist: item-1 inventory,
  `klt signoff --attest 1`, record regenerated with item 1 `met`.
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
- **Packet-loss criterion for LE** (#156, triage): the ratified LE row bounds
  BER but not packet loss; deciding whether the row needs a PER criterion is a
  spec question, not a fix.

## Blocked and waiting

- **#72** carries `loom:operator`: it needs either batch capacity long enough
  for a flat run or a ruling on the synthesis strategy and on whether a
  multi-megabyte committed netlist is acceptable. The batch runner is pushed
  on `feature/issue-72`; the Spot image's Yosys is 0.68 against the repo pin
  0.67, and `--capacity on-demand` is refused for lack of an `ec2:RunInstances`
  grant — both need a human, not another attempt.
- **#57** carries `loom:operator`: attesting the committed rows as T1 item 6
  evidence is a ruling away once the re-run rows land.
- **#43** is parked behind item 6's evidence and carries `loom:operator`.
- **#148** (triage): the committed item-10 attestation came from an unpinned
  klt dev build while CI pins 0.8.0 — regenerate under the pin or widen it.

Dispatchable today: #128 on the tracker; the O-QPSK rework issue once filed
(Now 2). Everything else open is building, in review, or held on `loom:operator`
/ triage.

## Not planned

- An RF front end, ADC, DAC or synthesizer; this repo stops at the digital
  interface (`spec/frontend-interface.md`).
- The upper link layer and protocol stacks.
- LE 2M and coded PHY before the LE 1M + 802.15.4 target closes.
- Any qualification, certification or standards-compliance claim (`CLAUDE.md`).
