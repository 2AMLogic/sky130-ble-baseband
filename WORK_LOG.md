# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide
triage role. Newest first.

### 2026-11-20

- **Issue #38** (closed): T1 item 9 (testbenches shipped): 0007 trace-replay cocotb benches (RTL vs model, bit-exact) and a testbench inventory attested with klt signoff --attest 9

### 2026-11-19

- **PR #177**: fix(top): retune LE_L_DIG_CYCLES to the group-delay-corrected air end (139 -> 74)
- **Issue #145** (closed): Decide the LE air-end reference convention: LE_L_DIG_CYCLES=139 vs measured L_dig 69-78 clk

### 2026-11-18

- **PR #195**: fix: refuse shards missing provenance fields instead of silent fallbacks
- **Issue #143** (closed): ber_sweep --merge: provenance fields fall back silently instead of refusing (prng falsy, missing-key sentinel)
- **PR #194**: test: pin worst_packet_loss in the BER row summary and its absence in the PER one
- **PR #191**: feat: conjunctive packet-loss bound on the ratified LE 1M BER row
- **Issue #192** (closed): sim: no test pins worst_packet_loss in the BER row summary — dropping it is silent
- **Issue #156** (closed): Ratified LE criteria bound BER but not packet loss after decision 0009
- **PR #190**: fix: declare channel and model sys.path entries in test_per_sweep so it collects alone
- **PR #119**: refactor(sim): one copy of the sweep CLI, stop rule, row verdict and report envelope
- **Issue #188** (closed): sim/tests/test_per_sweep.py cannot be collected alone: it inherits sys.path from a sibling test module
- **Issue #116** (closed): Dedupe the BER/PER sweep drivers: one copy of the CLI, stop rule, row verdict and report envelope
- **PR #187**: ci: add merge_group trigger to the required-check workflows
- **PR #151**: fix(sim): LE BER charges only the bits the receiver returned (decision 0009)
- **Issue #186** (closed): Merge queue: add the merge_group trigger to the required-check workflow(s)
- **Issue #133** (closed): LE 1M RX: BER is worst at ZERO carrier offset and non-monotonic in Eb/N0, which is why le1m_cfo misses 1e-3

### 2026-11-17

- **PR #185**: test: add CI workflow YAML parse-validity check to parser-test
- **PR #184**: chore(loom): resync installed Loom to v0.19.1306
- **PR #183**: docs: note definition 1's stale §3 quotation in the latency record
- **Issue #181** (closed): latency_record.md definition 1 quotes section 3's pre-0010 rationale (`L_tx + T_settle`)
- **Issue #172** (closed): No CI check validates .github/workflows/*.yml, so a broken workflow presents as a required context that never reports

### 2026-11-16

- **PR #180**: ci: fail signoff envelope-list derivation errors instead of passing silently
- **PR #176**: docs(verification): call the 15.4 lead axis a second jitter alignment, not a timing phase
- **PR #175**: chore(loom): resync installed Loom to v0.19.1302
- **PR #174**: docs: retract the subadditivity justification in the latency record
- **PR #173**: lint: tie the runbook klayout-tools pin literals to signoff.yml's pin
- **PR #170**: build: convert test-top-latency-negative to the negative_control define
- **PR #169**: ci: fail signoff job when an envelope's provenance.klt_version mismatches the installed klt
- **PR #168**: spec: replace 0010's faulty T_IFS-tolerance aside with the ratified 1 µs bound
- **PR #167**: manifests: inventory rtl_sources.py and state the item-9 listing rule
- **PR #155**: docs: scope manifests README re-attest guidance by trigger
- **PR #120**: docs: roadmap as of 2026-11-13
- **Issue #179** (closed): signoff guard: envelope-list derivation failure exits 0 (silent pass) instead of failing the step
- **Issue #178** (closed): Tighten the latency-matrix axis wording: rewrap verification/README.md:58 and drop the shared "arrival-phase" umbrella
- **Issue #171** (closed): CI does not check manifests/README.md's klayout-tools pin against signoff.yml's
- **Issue #166** (closed): Follow-on: test-top-latency-negative still hand-rolls the negative-control guard (eighth bench, not using the negative_control define)
- **Issue #165** (closed): latency_record.md: the subadditivity justification for enforcing spread(L_dig) is wrong and contradicts ratified 0010
- **Issue #164** (closed): spec: 0010's subadditivity paragraph overstates the T_IFS comparison ("outside the whole T_IFS tolerance")
- **Issue #162** (closed): 15.4 latency matrix: modulate(lead=) is not a timing-phase axis; the record says it is
- **Issue #158** (closed): item-9 inventory: verification/rtl_sources.py is tracked-tree-present but unlisted — the inventory's 'every file except README' property is broken
- **Issue #148** (closed): Committed item-10 attestation was produced by an unpinned klt dev build (0.9.2.dev1029) while CI and manifests/README.md pin klayout-tools==0.8.0
- **Issue #136** (closed): manifests/README.md: say what to regenerate when a hygiene artifact changes (not the inventory)

### 2026-11-15

- **PR #161**: build: dedupe the seven negative-control recipes into one negative_control define
- **PR #160**: fix(manifests): regenerate item-9 attestation envelope (main signoff red since #127)
- **PR #159**: docs(manifests): record item-9 inventory scope decision for sim/ benches
- **PR #157**: test: cover every rtl_sources.py rejection path, fix --check traceback
- **PR #154**: docs(synth): document record-log scoping convention and measured footprint cost
- **PR #152**: spec: L_tx starts at the TX-command strobe, jitter column bounds spread(L_dig)
- **PR #149**: sim: measure the O-QPSK PER sensitivity budget (issue #137)
- **PR #144**: feat(verification): measure L_rx/L_tx/L_dig and spread at baseband_top vs section 3
- **PR #140**: rtl: share one rx_moving_sum between the LE 1M and O-QPSK RX chains
- **Issue #163** (closed): manifests/README.md item-9 scope record misattributes verification/rtl_sources.py to PR #141 (it was #127)
- **Issue #153** (closed): main: klt signoff CI red — item-9 attestation drifted when #127 merged (merge skew with #129)
- **Issue #147** (closed): verification/rtl_sources.py has no automated test: the one file-list parser's rejection paths are hand-run only
- **Issue #146** (closed): spec/timing-and-area.md section 3: name the L_tx reference point and the jitter column's quantity (editorial, decision 0008)
- **Issue #142** (closed): Item-9 inventory scope: sim/ reference-model and channel-model benches are not inventoried or in the attested cold start
- **Issue #137** (closed): 802.15.4 reference receiver is ~4 dB short of the ratified PER row (needs 9 dB for PER < 1 %, spec says 5 dB)
- **Issue #135** (closed): Bound the committed footprint of flow/synth records logs
- **Issue #128** (closed): Dedupe the seven negative-control recipes in the Makefile into one define
- **Issue #125** (closed): Dedupe the RX moving-sum integrator: le1m_rx_integ and oqpsk_rx_integ are one parameterized module written twice
- **Issue #122** (closed): Measure L_rx / L_tx and their spread over the shared stimulus at baseband_top, checked against spec section 3
- **PR #141**: docs: correct README maturity-ladder position and regenerate item-10 attestation
- **Issue #124** (closed): README "Current position" still says "No block RTL yet"; correct it and re-attest item 10
- **PR #138**: sim: commit the full-caps 802.15.4 PER sweep evidence and its run record
- **Issue #56** (closed): T1 item 6b: 802.15.4 CM-A source and seeded PER sweep with negative control
- **PR #134**: test(sim): commit the full LE 1M BER sweep, run as five Spot batch shards
- **Issue #55** (closed): T1 item 6a: committed full LE 1M BER sweeps (all rows, CM-A) with negative control
- **PR #129**: feat(manifests): attest T1 item 9 from the committed testbenches
- **Issue #121** (closed): T1 item 9a: testbench inventory and `klt signoff --attest 9` for the benches on main
- **PR #127**: build: derive every per-block RTL source list from rtl/baseband.f
- **Issue #118** (closed): Derive the per-block RTL source lists from rtl/baseband.f: five file lists are hand-kept in two places each

### 2026-11-14

- **PR #131**: feat(synth): timestamp profile.sh logs and record the dominant pass per leaf
- **Issue #123** (closed): Record per-pass Yosys timing for oqpsk_rx_corr and le1m_rx_sync, with and without the generic ABC pass
- **PR #115**: refactor(sim): share CM-A stages 4/6/7 between both channel models
- **Issue #114** (closed): Share the CM-A resample/noise/AGC/quantize tail between cm_a.py and cm_a_oqpsk.py (one copy of the declared channel model)

### 2026-11-12

- **PR #111**: Bump Repo Skills 0.25.10 -> 0.26.1

### 2026-11-07

- **PR #109**: Bump Repo Skills 0.25.1 -> 0.25.10

### 2026-11-06

- **PR #107**: perf(oqpsk): compute 8 correlators and negate for m+8 in oqpsk_rx_corr
- **Issue #106** (closed): oqpsk_rx_corr: compute 8 correlators and negate for m+8, bit-exact, and re-profile

### 2026-11-05

- **PR #103**: feat(synth): add bounded per-module Yosys profile and SYNTH_MODE=hier
- **Issue #101** (closed): Add a hierarchical synthesis mode and record per-module Yosys cost to shrink #72

### 2026-11-01

- **PR #98**: Bump Repo Skills 0.24.7 -> 0.25.1

### 2026-10-31

- **PR #96**: feat(sim): 802.15.4 CM-A source and seeded PER sweep

### 2026-10-28

- **PR #93**: feat(sim): shard the LE 1M BER sweep by row and add a validating merge
- **Issue #92** (closed): BER sweep: shard-ready harness and merge step for Spot runs (#55)
- **PR #90**: feat(host): drop address-filter-rejected RX packets via FIFO rollback
- **Issue #73** (closed): Spec decision: RX packets rejected by the address filter cannot be dropped from the FIFO

### 2026-10-27

- **PR #88**: refactor: share vector materialisation and noise-only stimulus across the RX case modules
- **Issue #87** (closed): Dedupe write_vectors and noise-only stimulus across LE 1M and O-QPSK cases.py
- **PR #86**: refactor: share the cocotb build/run/verdict sequence across verification runners
- **Issue #85** (closed): Simplify: share cocotb runner boilerplate across verification run_*.py
- **PR #84**: refactor: share the cocotb RX stimulus driver between LE 1M and O-QPSK benches
- **Issue #80** (closed): Dedupe the cocotb RX Harness shared by LE 1M and O-QPSK replay testbenches
- **PR #79**: refactor: share the ideal O-QPSK modulator via sim/model/oqpsk_tx
- **Issue #77** (closed): Dedupe the ideal-modulator stimulus generator shared by O-QPSK model tests and RTL replay
- **PR #78**: refactor: share cocotb trace compare and RX load_case in traces.py
- **Issue #71** (closed): Dedupe cocotb trace compare across replay testbenches
- **PR #74**: feat(top): baseband_top integration, glue and top-level bench
- **PR #68**: ci: run LE 1M TX replay and negative control in flow.yml
- **Issue #67** (closed): ci: run test-le1m-tx and its negative control in flow.yml
- **PR #66**: feat: 802.15.4 O-QPSK TX and RX RTL with bit-exact trace replay
- **Issue #54** (closed): T1 item 1c: 802.15.4 O-QPSK TX/RX RTL (spread, shape, despread, SFD, FCS) bit-exact with the model
- **PR #63**: feat(rtl): add APB host interface with FIFOs, interrupts and timestamps
- **Issue #50** (closed): T1 item 1d: host interface RTL (APB4 register map, TX/RX FIFOs, descriptor FIFO, interrupts, timestamp)
- **PR #64**: feat(rtl): bit-exact LE 1M TX path with cocotb trace replay
- **Issue #48** (closed): T1 item 1a: LE 1M TX RTL (whitening, CRC-24, framing, Gaussian shaping to tx_dev) bit-exact with le1m_tx.py
- **PR #62**: docs: refresh README status, add reproduce section, attest repo hygiene
- **Issue #46** (closed): T1 item 10 (repo hygiene): README status, reproduction steps for every result, hygiene inventory attested with klt signoff --attest 10
- **PR #61**: feat(rtl): LE 1M RX path bit-exact with the integer reference receiver
- **Issue #53** (closed): T1 item 1b: LE 1M RX RTL (non-coherent demod, AA correlation, de-whitening, CRC-24 check) bit-exact with le1m_rx.py
- **PR #59**: feat(sim): integer 802.15.4 O-QPSK TX/RX reference models and golden traces
- **Issue #49** (closed): sim: fixed-point 802.15.4 O-QPSK TX/RX reference model, golden traces and loopback tests
- **PR #58**: feat(mac): add lower-MAC timers, trigger, auto-ACK and address filters
- **Issue #51** (closed): T1 item 1e: hardware timers (T_IFS, 15.4 turnaround/ACK-wait), timed trigger, auto-ACK and address filtering RTL

### 2026-10-23

- **PR #32**: feat(sim): integer LE 1M TX reference model, trace format, model-test
- **Issue #30** (closed): sim: fixed-point LE 1M TX reference model (PDU to whitened, CRC'd, Gaussian-shaped tx_dev words) and the golden-trace file format of decision 0007
- **PR #33**: feat(sim): CM-A channel, integer LE 1M receiver and seeded BER sweep
- **Issue #31** (closed): sim: CM-A channel model and a fixed-point non-coherent LE 1M receiver with a seeded BER sweep harness (Clopper-Pearson stop rule)

### 2026-10-21

- **PR #27**: Bump Repo Skills 0.24.3 -> 0.24.7
- **PR #13**: ci: add T1 block manifest and klt signoff freshness workflow
- **Issue #4** (closed): Commit a T1 block manifest and a klt signoff CI job (T1 item 10)

### 2026-10-20

- **PR #26**: build: point package.json test/lint/check scripts at Makefile targets
- **Issue #22** (closed): Make package.json placeholder scripts honest: test/lint/check:ci always exit 0
- **PR #17**: feat(flow): pinned cocotb, lint and Yosys smoke flow on a placeholder LFSR
- **Issue #3** (closed): Bring up the digital flow on a placeholder: cocotb + Icarus, lint, Yosys to sky130_fd_sc_hd (T1 item 9 groundwork)

### 2026-10-18

- **PR #21**: docs(spec): ratify spec revision 1 with timing, L_dig, area and bit-exactness
- **PR #20**: docs(spec): clarify host-interface interrupt gating, add ERR_STATUS and TX_LENGTH
- **PR #19**: docs(spec): renumber decision records into one 0001-0006 sequence
- **Issue #2** (closed): Draft and ratify the target spec
- **Issue #9** (closed): Spec: timing/area across corners, bit-exactness decision, ratification
- **Issue #15** (closed): spec: host-interface interrupt masking wording and unlisted status bits
- **Issue #18** (closed): Simplify spec decisions: colliding 0001/0002 numbers and split indexes

### 2026-10-17

- **PR #16**: docs(spec): add 4 Msps RX fallback to modelling-choices table
- **PR #10**: docs(spec): lower-MAC split decision record and host interface
- **PR #12**: docs(spec): add front-end interface tables and turnaround budget
- **PR #11**: docs(spec): add target spec table, channel model and decision records
- **PR #1**: chore(loom): Install Loom 0.19.1180
- **Issue #14** (closed): spec: RX input sample-rate fallback (4 Msps) in decision 0001 has no row in target-spec
- **Issue #8** (closed): Spec: lower-MAC hardware/software split decision and host interface
- **Issue #7** (closed): Spec: RX/TX front-end interface signal tables and turnaround budget
- **Issue #6** (closed): Spec: PHYs, demodulator targets, channel model and demod architecture
