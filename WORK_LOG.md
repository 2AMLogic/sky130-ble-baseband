# Work Log

Chronological record of merged PRs and closed issues, maintained by the Guide
triage role. Newest first.

### 2026-10-27

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
