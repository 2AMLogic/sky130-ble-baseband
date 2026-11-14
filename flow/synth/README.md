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

`profile.sh [-t SECONDS] [-o DIR] [-n] [module ...]` runs generic `synth -top <m>`
(no `-flatten`, no liberty) on each module of `rtl/baseband.f`, one at a time, each
under a hard `timeout`, and writes `records/<date>/profile.json` (wall time, peak RSS,
generic cell and flop counts; status `ok`, `timeout` or `error`). Cell counts are
not timing claims. A parent row includes its children (`synth -top` synthesizes
them too), so parent and child rows must not be added together.

`-n` appends `-noabc` to `synth -top <m>` and writes to `records/<date>-noabc/`, so
a baseline and a no-ABC record of the same date do not overwrite each other; every
row records which variant it was (`"noabc"`). Yosys runs with `-t` and `-d`, so the
per-module logs under `records/<date>/logs/` (committed as evidence) carry a
timestamp on every line and a run killed by the timeout still shows which pass it
was in; the `-d` ranked per-pass table is printed at exit only, so a killed run has
none. Peak RSS is recorded for timed-out rows too, because `/usr/bin/time` wraps
`timeout` rather than the reverse — the earlier `2026-11-06` records have a 0-byte
`.time` and `"peak_rss_kb": null` for exactly that reason.

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

### Where the time goes, per leaf (issue 123)

Recorded in `records/2026-11-14/` (baseline, 120 s timeout) and
`records/2026-11-14-noabc/` (`profile.sh -n`, 300 s timeout), Yosys 0.67+post
(`b8e7da6`), one `yosys` at a time on loom-worker-4. Generic post-`synth` cell
counts are **not** timing claims.

**Generic `synth`'s own ABC pass dominates both leaves, and skipping it lets both
finish.** In the baseline each leaf reaches step `39.22. Executing ABC pass` and is
still inside it when the timeout fires:

| leaf | reaches ABC (39.22) | killed at | inside ABC | peak RSS |
|---|---|---|---|---|
| `oqpsk_rx_corr` | 5.5 s | 120 s | ~114 s (95 % of the budget) | 181,304 kB |
| `le1m_rx_sync` | 45.2 s | 120 s | ~75 s (62 % of the budget) | 393,656 kB |

The last line of each baseline log is `39.22.1. Extracting gate netlist of module
... to <abc-temp-dir>/input.blif` — the same pass the hierarchical `baseband_top`
run stalled in on 2026-11-05 (`records/2026-11-05/hier_top.txt`, step 39.22.26).
Neither run emits a `-d` table, so those timestamped pass headers are the only
evidence available for a timeout.

With `synth -top <m> -noabc` both finish well inside a bounded run:

| leaf | status | wall | generic cells | flops | peak RSS | residual dominant pass (`-d`) |
|---|---|---|---|---|---|---|
| `oqpsk_rx_corr` | ok | 5.0 s | 42,009 | 5,956 | 185,604 kB | `read_verilog` 43 % (2.5 s) |
| `le1m_rx_sync` | ok | 41.5 s | 46,726 | 9,256 | 393,784 kB | `opt_clean` 37 % (16.0 s), `opt_expr` 24 % (10.5 s) |

`read_verilog` is the whole `rtl/baseband.f` filelist parse, so every `profile.sh`
row carries a ~2.5 s floor whatever the module; for `oqpsk_rx_corr` that floor is
half the no-ABC run, i.e. the leaf itself is cheap once ABC is skipped. Only
`le1m_rx_sync` has residual cost of its own, in the `opt_*` passes.

`-noabc` is a diagnostic, not a route to item 1: a netlist without ABC is not the
item-1 artifact, and `synth.tcl` / `make synth` are unchanged here. Whether
`SYNTH_MODE=hier`, a restructured leaf, or something else closes #72 is that
issue's call; this record is its input.
