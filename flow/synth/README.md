# flow/synth

`synth.tcl` synthesizes one top (default `baseband_top`, file list
`rtl/baseband.f`) with Yosys, flattened, mapped to `sky130_fd_sc_hd` at the
liberty corner pinned in `flow/versions.mk` (`PDK_REV`, `LIB_CORNER`). It reads
its inputs from the environment (`SYNTH_TOP`, `SYNTH_LIST`, `SYNTH_LIB`,
`SYNTH_OUT`, `SYNTH_NETLIST`); `make synth` sets them.

Intended artifacts (item 1 derived files; **not committed yet**):

- `baseband_top_netlist.v`: gate-level netlist (`write_verilog -noattr`, no
  timestamps).
- `liberty_record.txt`: PDK revision, corner, liberty file name, Yosys version.

`make synth` writes both; `make synth-check` regenerates them under
`flow/build/synth/fresh/` and fails if either differs from the committed copy.
Run with the pinned tools and PDK (`make check-tools check-pdk`). CI has no PDK, so
the check would be `local_only` in the item-1 inventory.

## Status: no netlist yet

A full flat run of `baseband_top` did not finish: on loom-worker-4 (one core) Yosys
was still in its first ABC pass (`synth`, step 39.24, a ~22 MB gate netlist) after
45 minutes and was stopped. `oqpsk_rx_corr` alone (57,787 generic cells) takes 8 min
in `synth -flatten`, before liberty mapping. The RTL was written for bit-exactness,
not area (`rtl/README.md`), so the item-1 netlist, its inventory and the
attestation are open; see the issue linked from the PR. The cell counts of any
finished run are not timing claims; timing belongs to the STA item.

## Profile and hierarchical mode (issue 101)

`profile.sh [-t SECONDS] [-o DIR] [module ...]` runs generic `synth -top <m>` (no
`-flatten`, no liberty) on each module of `rtl/baseband.f`, one at a time, each under
a hard `timeout`, and writes `records/<date>/profile.json` (wall time, peak RSS,
generic cell and flop counts; status `ok`, `timeout` or `error`). Cell counts are
not timing claims. A parent row includes its children (`synth -top` synthesizes
them too), so parent and child rows must not be added together.

`SYNTH_MODE=hier` (unset or `flat`: the flat commands are unchanged) runs
`synth -top` without `-flatten`, then `dfflibmap` and `abc -liberty` per module
(`SYNTH_ABC_FAST=1` switches to `abc -fast -liberty`).

Recorded 2026-11-05 in `records/2026-11-05/` (120 s timeout per module, Yosys 0.67):

- 32 of 37 rows finish in under 10 s each; `le1m_rx_pkt` takes 103 s (22,307
  generic cells). Peak RSS is about 175 MB for every small module.
- 5 rows time out at 120 s: leaves `oqpsk_rx_corr` and `le1m_rx_sync`, and the
  parents `le1m_rx`, `oqpsk_rx`, `baseband_top` (which contain them). Those two
  leaves dominate; `oqpsk_rx_corr` alone is 8 min and 57,787 generic cells in the
  flat run (above), and `le1m_rx_pkt` is the next largest leaf. Everything else is
  small: `host_top` 19,811, `bb_tx_path` 5,774, `le1m_rx_cordic` 4,701,
  `oqpsk_rx_pkt` 4,212 generic cells.
- `SYNTH_MODE=hier` on `baseband_top` (liberty tt_025C_1v80) did **not** finish in
  300 s (peak RSS 943 MB). It stalled in generic `synth`'s own ABC pass on
  `oqpsk_rx_corr`, before liberty mapping (`records/2026-11-05/hier_top.txt`).
  Dropping `-flatten` alone therefore does not remove the cost; the two timing-out
  leaves do. `hier + abc -fast` was not run, since `-fast` only affects the later
  liberty ABC pass. No RTL rewrite is made here.

### `oqpsk_rx_corr` with 8 correlators plus negation (issue 106)

`oqpsk_rx_corr` now sums correlators 0..7 and sets `corr[m+8] = -corr[m]` (the chip
table gives `W[m+8] = -W[m]`, checked by `sim/tests/test_oqpsk_corr_symmetry.py`;
outputs bit-identical, oqpsk and top benches and negative controls pass). Before /
after, generic `synth -top oqpsk_rx_corr`, Yosys 0.67:

| | status | wall | generic cells |
|---|---|---|---|
| before (2026-11-05, 120 s) | timeout | 120 s | not finished (57,787 in the flat run) |
| after (`records/2026-11-06/`, 120 s) | timeout | 120 s | not finished |
| after (`records/2026-11-06-t300/`, 300 s) | timeout | 300 s | not finished |

Halving the adders did **not** bring the leaf under 300 s, so this change alone does
not unblock #72. The reduction in cell count is unmeasured because no run finished.
