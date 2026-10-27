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
