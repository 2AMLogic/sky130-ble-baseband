# verification

cocotb testbenches, and the flow that runs them with lint and synthesis.

## Cold start

From a fresh clone, with the pinned tools on `PATH` (below):

```
make venv   # once: .venv with the pinned cocotb
make        # every bench, negative control, lint, synth; exit 0 = all pass
```

Individual steps: `make test`, `make test-negative`, `make test-le1m-rx`,
`make test-le1m-rx-negative`, `make test-oqpsk`, `make test-oqpsk-negative`,
`make test-top`, `make test-top-negative`, `make lint`, `make synth`, `make synth-check`.

- `test-le1m-rx` replays the shared RX stimulus of `verification/le1m_rx/cases.py`
  (CM-A noiseless and noisy, offset/drift/clock corners, bad CRC, missed detect,
  access-address errors, clipping, truncation) through `rtl/le1m_rx` and compares
  the RTL trace with the model trace exactly, by `rx_valid` sample index. Vectors
  are regenerated into `flow/build/le1m_rx/sim/vectors/` from the seeds in
  `cases.py`; they are simulated stimulus, not measurements. The `gain` records
  (stimulus echo) are not compared.
- `test-le1m-rx-negative` flips one expected `bit` record and fails unless the
  replay rejects it with an `expected=` mismatch.

- `test-oqpsk` replays `verification/oqpsk/cases.py` through `rtl/oqpsk`: TX payloads
  of 0, 1, 3, 18 (golden), 60 and 125 octets (127-octet PSDU) against
  `oqpsk_tx` words and `tx_active` edges, and RX loopback (PSDU 0..127, idle leads
  including one shorter than the filter/CORDIC latency, bad FCS, SFD miss, noise,
  silence, truncation, Gaussian noise, sample-clock drift with timing steps)
  against `oqpsk_rx` trace taps, by sample index, exactly. The committed
  `sim/model/golden/{tx_154_psdu20,rx_154_loopback_psdu20}.trace` are compared
  directly. The RX half is also run with `rx_valid` on every clk. Vectors land in
  `flow/build/oqpsk/sim/{tx,rx}/vectors/`; they are simulated stimulus, not measurements.
- `test-oqpsk-negative` flips one expected record in each half and fails unless
  each replay rejects it with a `first mismatch ... expected=` report.

- `test-top` drives `baseband_top` (every sub-block, `rtl/baseband.f`) through its
  pins only: APB for registers and FIFOs, `rx_i`/`rx_q`/`rx_valid` for samples,
  `tx_dev`/`tx_valid` for the modulator words, and a front-end model for
  `fe_ready`. Six tests: LE 1M TX and RX, 15.4 TX and RX, the 15.4 automatic ACK
  and the LE timed response. Every stimulus and expected value comes from the
  models (`sim/model/le1m_tx.py`, `oqpsk_tx.py`, the CM-A channel model, the
  15.4 loopback), none is hand-written. It prints `MEASURED` lines with the
  end-of-packet to rx_end / first-TX-word latencies that set `L_DIG_CYCLES`
  (rtl/top/README.md). It makes no error-rate claim: the stimulus is noiseless
  and one packet per test. `test-top-negative` perturbs one expected value in
  each test and fails unless every test is rejected with an `expected=` report.
- `test-negative` runs the host and lower-MAC negative controls.
- `lint` is Verilator `--lint-only -Wall`: each block, then `baseband_top` over
  `rtl/baseband.f`; any warning fails.
- `synth` maps `baseband_top` (flattened) to `sky130_fd_sc_hd` with Yosys at the
  `tt_025C_1v80` Liberty corner into `flow/synth/baseband_top_netlist.v` and
  `flow/synth/liberty_record.txt`; `synth-check` regenerates both and fails on any
  byte of difference. The full run has not completed yet (`flow/synth/README.md`,
  "Status"), so no netlist is committed. Neither sets a clock or area target.

Run outputs land under `flow/build/<block>/` (gitignored, never committed):
`sim/` and `sim_neg/` (simulator build and `results.xml`), `negative.log`;
synthesis reports (`cell_count.rpt`, `yosys.log`) under `flow/build/synth/`.

## Pins

| What | Pin | Where |
|---|---|---|
| cocotb | 2.0.1 | `requirements.txt` |
| Icarus Verilog | 13.0 | `flow/versions.mk` |
| Verilator | 5.050 | `flow/versions.mk` |
| Yosys | 0.67 | `flow/versions.mk` |
| OpenROAD (later P&R only; recorded, not run) | 26Q3-1510-g6cb3f2b704 | `flow/versions.mk` |
| sky130 PDK (`sky130_fd_sc_hd`) | `f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7` | `flow/versions.mk` |

`make` fails with a message naming the tool on a missing tool or version
mismatch. The PDK is read from `$CIEL_HOME/ciel/sky130/versions/<rev>/`
(default `~/.ciel`); `make synth` fails if that pinned revision's Liberty file
is absent rather than using any other. Fetch it with
`pip install ciel && ciel enable --pdk-family sky130 <rev>`.

## CI

`.github/workflows/flow.yml` runs `make test test-negative test-le1m-rx test-le1m-rx-negative test-le1m-tx test-le1m-tx-negative test-oqpsk test-oqpsk-negative test-top test-top-negative lint ALLOW_TOOL_DRIFT=1` (apt tool versions differ
from the pins, so mismatches are warnings there; local runs must match). Synthesis is
not run in CI: it needs the full PDK fetch, which this workflow does not
perform. Run `make synth-check` locally.

## LE 1M TX replay

`verification/le1m_tx/` replays reference-model traces against `rtl/le1m_tx/`
(decision 0007: shared traces, exact equality, first mismatch reported with
file, record number and field). `make test-le1m-tx` replays the committed
golden trace plus packets generated by `sim/model/le1m_tx.py --out` into
`flow/build/le1m_tx/` (channels 37/38/39 and a data channel, header-only and
empty PDUs, the 257-octet maximum, access addresses with LSB 0 and 1, a
non-default CRC init). `make test-le1m-tx-negative` corrupts one expected
`txdev` record and fails unless the replay rejects it with the
`tx trace mismatch` message. `make lint` also lints the new RTL. The model is
not run inside the simulator. The `txact` fall is recorded at the 4-clock slot
index (last word index + 2), since no strobe occurs in the trailing slot.
