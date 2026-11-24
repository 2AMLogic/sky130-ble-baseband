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

Two more shapes, both added for issue 201 (see the section below): `-r ROUTE`
runs a liberty mapping route (`noabc_map`, `noabc_mapfast`, `noabc_abc9`,
`noabc_minmap`; `-n` is `-r noabc`), and `-d` runs the ABC-stall diagnostics
instead of a synth variant (env probe, kept ABC temp dir, standalone
`yosys-abc` single-session per-command timing with `stdcells.genlib` and
completion verification), writing `diag.json` + `diag/<module>/`. Both `-d`
and `-r noabc_*` default to the two leaves (`oqpsk_rx_corr le1m_rx_sync`) and
a 300 s cap (override with `-t` and explicit module names); plain profiling
and `-n` / `-r noabc` preserve the legacy defaults (600 s, full filelist).
`routes-batch.sh` runs the whole matrix sequentially inside one `repo-script`
batch shard, off-worker (issue 201 / operator ruling of 2026-10-29).

`SYNTH_MODE=hier` (unset or `flat`: the flat commands are unchanged) runs
`synth -top` without `-flatten`, then `dfflibmap` and `abc -liberty` per module
(`SYNTH_ABC_FAST=1` switches to `abc -fast -liberty`).

### Record-log footprint convention

`profile.sh` writes one `-t -d` log for **every** module it runs, so a default
(no-argument) invocation sweeps the whole 37-module filelist of
`rtl/baseband.f` and stages 37 logs under `records/<date>/logs/` in one go.
`.gitignore:15` (`!flow/*/records/**/*.log`) deliberately makes all of them
committable — it does not, and cannot, enforce a footprint bound (below). The
bound is what gets `git add`-ed, so the convention is:

**Commit logs only for the modules a record is about** — the leaves or parents
under investigation — not a full-filelist sweep. Pass explicit module arguments
to `profile.sh`, or stage selectively, when recording. Both `2026-11-14`
records follow this.

Measured cost of a record's logs, so the next agent need not re-derive it
(checked against `origin/main` @ `4fe5b03`, 2026-11-15; content bytes from
`git ls-tree -r --long`, on-disk bytes from
`git cat-file --batch-check='%(objectsize:disk)'`):

- A scoped two-leaf record like the committed `2026-11-14` ones: 1,097,780
  bytes (≈1.1 MB) of log content, 151,530 bytes (≈148 KiB) on disk.
- An unscoped 37-module record would be ≈10 MB of content — **extrapolated**,
  not measured (no such sweep has been run), to ≈1.3 MiB on disk using the
  ratio below, recurring once per unscoped sweep.

That ratio is measured, on the four committed log blobs: 1,097,780 bytes of
content occupy 151,530 bytes on disk — **13.8 %**. The blobs are loose in the
measured checkout, so the figure is standalone zlib with no cross-object
delta: a conservative upper bound on packed cost, not an estimate of it.

`.gitignore` does not enforce the scoping on purpose. No maintainable glob
can: requiring a `logs/` path component still matches the same 37 files,
because `profile.sh` writes every log under `$OUT/logs/`; enumerating module
names would bound the set, but would silently drop a newly added module's log
from this append-only record trail.

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

## Where the ABC stall is, and a mapping route that finishes (issue 201)

Recorded in `records/2026-11-21-routes/`. Not run on a worker: one `repo-script`
Spot batch shard (`rs-20261121T000212Z-0f3552e8-s00`, `m7i.4xlarge`, wall
2052 s, no reclaim), operator ruling of 2026-10-29 via #72; provenance in
`run-meta.txt` (job id, instance, image, source tarball and liberty sha256s).
**Caveat: that image's Yosys is `0.68+` (OpenROAD fork `a5af9d690`), not the
repo pin `0.67`** — the rows are wall-time evidence for "does a route finish
at all", not reproducible pin-flow numbers. Per-run cap 300 s, one `yosys` at
a time, produced by `routes-batch.sh` + `profile.sh -d` / `-r` (this issue).
Cell counts are not timing claims.

### Stall diagnostics (step 1): observed timings, BLIF sizes and caveats

The diagnostics (`diag.json`, `diag/<leaf>/`) recorded the following on the
batch image (Yosys `0.68+` OpenROAD fork, 300 s cap):

- **Case A (env probe: `COLUMNS=1000 TMPDIR=/tmp stdbuf`)**: `oqpsk_rx_corr`
  finished in **199.4 s** (`ok`, peak RSS 214,956 kB); `le1m_rx_sync` hit the
  cap at **300.0 s** (`timeout`, peak RSS 397,552 kB). This establishes that
  `oqpsk_rx_corr` completes in 199.4 s in the batch fork under the probe
  environment, whereas the older `2026-11-14` pinned-`0.67+post` run ended at
  its 120 s timeout with the extraction banner as its last log line. Because
  Case A changed the Yosys binary (`0.68+` fork vs pinned `0.67+post`), the
  environment, and the cap (300 s vs 120 s) together, it does not isolate
  those variables for the older pinned run; it is consistent with the 120 s
  cap interrupting active ABC work on `oqpsk_rx_corr`, while `le1m_rx_sync`
  still exceeded 300 s under the probe environment.
- **Case B (kept ABC temp dir: `synth -noabc; abc -nocleanup -showtmp`)**:
  after Yosys exited or timed out, `input.blif` was present on disk for both
  leaves — **4,051,560 B** for `oqpsk_rx_corr` (`ok`, 198.4 s wall, peak RSS
  186,512 kB; sha256 prefix `4f4c08bccb891cb8`) and **4,743,384 B** for
  `le1m_rx_sync` (`timeout`, 300.0 s wall, peak RSS 396,844 kB; sha256 prefix
  `364cddca6f5024d4`). Because `profile.sh` checks `input.blif` only after
  Yosys exits or times out, the exact timestamp when `input.blif` was created
  is not directly measured; what is established is that extraction produced
  both BLIFs before exit/kill. In the finishing `oqpsk_rx_corr` log
  (`caseB.log` lines 2815–2840), the extraction banner is stamped
  `00003.551663` and every `ABC:` line shares `00198.1249xx`, showing ABC's
  output stayed pipe-buffered until child exit — so a killed log ending at
  the extraction banner does not by itself show Yosys stalled in extraction.
- **Case C (standalone `yosys-abc` on the kept `input.blif`)**:
  - `oqpsk_rx_corr`: `strash` took **0.2 s** (`ok`), `&get -n; &fraig -x; &put`
    took **189.8 s** (`ok`), and `scorr` took **0.1 s** (`ok`, combinational
    network warning). Steps 4–7 (`dc2`, `dretime`, `strash`,
    `&get -n; &dch -f; &nf; &put`) **failed** in the recorded `2026-11-21`
    run (`diag.json` corrected on 2026-11-23 from `ok` to `error`; raw
    `diag/oqpsk_rx_corr/caseC.log:5–12` unmodified): the pre-fix harness
    reloaded a BLIF per invocation, which lost ABC's strashed network state
    so `dc2` errored and steps 5–7 could not open their missing input BLIFs,
    while `yosys-abc` still exited 0. Those four later commands were **not**
    validly measured in the `2026-11-21` Case C run (for coarse context only,
    full in-session `caseB` took 198.4 s total vs 3.55 s before ABC and
    189.8 s for standalone `&fraig -x`, leaving ~5 s combined for extraction,
    the remaining ABC commands, and re-integration).
  - `le1m_rx_sync`: `strash` took **0.2 s** (`ok`) and
    `&get -n; &fraig -x; &put` hit the budget at **299.0 s** (`timeout`,
    overall 299.2 s `timeout`). That timeout in the fraig group is valid
    evidence; its later commands were never reached.
  - `profile.sh -d` has since been updated to keep the default ABC script and
    `stdcells.genlib` in a single `yosys-abc` session and verify completion
    before recording `ok`, for any future off-worker rerun.

### Trial routes (step 2), both leaves, 300 s cap

| route (`profile.sh -r`) | `oqpsk_rx_corr` | `le1m_rx_sync` |
|---|---|---|
| `noabc_map` — `synth -noabc; dfflibmap; abc -liberty` (default ABC script) | ok, 176.7 s, 36,560 cells, 5,956 flops | **timeout** at 300 s |
| `noabc_mapfast` — same with `abc -fast` | error (3.6 s): the image's 0.68+ `abc` rejects `-fast` (`abc -fast` exists on pin 0.67) | error (33.9 s), same cause |
| `noabc_abc9` — `read_liberty -lib; synth -abc9` | error (1.9 s): `ABC9 flow only supported for FPGA synthesis (using '-lut' option)` — abc9 has no liberty standard-cell mode on 0.67 or 0.68+ | error (1.8 s), same |
| `noabc_minmap` — `synth -noabc; dfflibmap; abc -liberty -script {+strash;,map}` | **ok, 6.8 s**, 45,399 cells, 5,956 flops | **ok, 38.4 s**, 50,965 cells, 9,256 flops |

Flop totals cross-check the `2026-11-14-noabc` generic counts exactly (5,956 /
9,256). The `noabc_minmap` and `noabc_map` rows' flops were corrected after
collection from the recorded `.stat` files — the batch's flop parser missed
the enable-flop `edfxtp` family (see `run-meta.txt`); the fix is in
`profile.sh`.

### Conclusion

**`SYNTH_MODE=minmap` finishes on both leaves** (6.8 s, 45,399 cells, 5,956
flops on `oqpsk_rx_corr`; 38.4 s, 50,965 cells, 9,256 flops on `le1m_rx_sync`,
300 s cap on the batch image's Yosys `0.68+`) and is selectable in `synth.tcl`
(`SYNTH_MODE=minmap`): `synth -noabc`, `dfflibmap`, then `abc -liberty` with
the minimal `strash; map` script. The default (`flat`) and `hier` modes are
unchanged; `SYNTH_MODE` unset still means `flat`. Compared to the default
`noabc_map` script recorded in `routes/noabc_map/logs/oqpsk_rx_corr.log:2864–2876`
(`strash; &get -n; &fraig -x; &put; scorr; dc2; dretime; strash; &get -n; &dch -f; &nf; &put`,
which finished `oqpsk_rx_corr` in 176.7 s at 36,560 cells / 5,956 flops and
timed out on `le1m_rx_sync`), `noabc_minmap` (`routes/noabc_minmap/logs/oqpsk_rx_corr.log:2865–2866`,
`strash; map`) omits the entire optimization sequence (`&fraig -x`, `scorr`,
`dc2`, `dretime`, `&dch -f`) and maps with `map` instead of `&nf`. The higher
cell count on `oqpsk_rx_corr` (45,399 vs 36,560 cells; flops unchanged at
5,956) therefore reflects dropping that whole pipeline and changing the mapper
rather than the isolated contribution of `&fraig -x`, and is a cell-count
observation rather than an area or timing claim. The batch runner wiring
(`run-batch.sh`) lives on `feature/issue-72`, not `main`; selecting the mode
there is #72's to wire. No `baseband_top` run was made here; the full-top run
stays with #72, which can now take `SYNTH_MODE=minmap` as its route.
