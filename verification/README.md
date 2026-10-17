# verification

cocotb testbenches, and the flow that runs them with lint and synthesis.
`verification/smoke/` tests the **placeholder** LFSR in `rtl/smoke/`; it proves
the flow works and verifies nothing about the baseband.

## Cold start

From a fresh clone, with the pinned tools on `PATH` (below):

```
make venv   # once: .venv with the pinned cocotb
make        # check-tools, test, test-negative, lint, synth; exit 0 = all pass
```

Individual steps: `make test`, `make test-negative`, `make lint`, `make synth`.

- `test-negative` runs the same test with one expected value deliberately
  wrong (`LFSR_NEGATIVE=1`) and fails if the test does *not* fail, so a broken
  expectation can never pass silently.
- `lint` is Verilator `--lint-only -Wall` over `rtl/smoke/`; any warning fails.
- `synth` maps the placeholder to `sky130_fd_sc_hd` with Yosys at the
  `tt_025C_1v80` Liberty corner. It sets no clock or area target.

Run outputs land under `flow/build/smoke/` (gitignored, never committed):
`sim/` and `sim_neg/` (simulator build and `results.xml`), `negative.log`,
`lfsr8_netlist.v` (gate-level netlist), `cell_count.rpt`, `yosys.log`, and
`liberty_record.txt` (PDK revision and the exact Liberty file used).

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

`.github/workflows/flow.yml` runs `make test test-negative lint ALLOW_TOOL_DRIFT=1` (apt tool versions differ
from the pins, so mismatches are warnings there; local runs must match). Synthesis is
not run in CI: it needs the full PDK fetch, which this workflow does not
perform. Run `make synth` locally.
