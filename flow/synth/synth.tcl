# Top-level synthesis (run as `yosys -c`), generalised from the old smoke script.
# Inputs from the environment:
#   SYNTH_TOP   top module name
#   SYNTH_LIST  RTL file list, one repo-relative path per line (rtl/baseband.f)
#   SYNTH_LIB   liberty file (pinned corner, flow/versions.mk)
#   SYNTH_OUT   run directory for the reports
#   SYNTH_NETLIST  path of the netlist to write
#   SYNTH_MODE  optional: `flat` (default, unset = flat) or `hier` (no -flatten,
#               per-module ABC; experimental, see flow/synth/README.md) or
#               `minmap` (synth -noabc; dfflibmap; abc -liberty -script
#               +strash;,map -- skips ABC's fraig sweep, which is where the
#               default script stalls on oqpsk_rx_corr and le1m_rx_sync; both
#               leaves finish under it, records/2026-11-21-routes/)
#   SYNTH_ABC_FAST  optional, hier only: `1` uses `abc -fast -liberty`
# Cell counts / area from this step are not timing claims (item 42 owns those).
set top  $::env(SYNTH_TOP)
set lib  $::env(SYNTH_LIB)
set out  $::env(SYNTH_OUT)
set net  $::env(SYNTH_NETLIST)
set fh [open $::env(SYNTH_LIST) r]
set files {}
foreach line [split [read $fh] "\n"] {
    set line [string trim $line]
    if {$line ne "" && [string index $line 0] ne "#"} { lappend files $line }
}
close $fh
foreach f $files { yosys read_verilog -sv $f }
yosys hierarchy -check -top $top
set mode flat
if {[info exists ::env(SYNTH_MODE)] && $::env(SYNTH_MODE) ne ""} { set mode $::env(SYNTH_MODE) }
if {$mode eq "flat"} {
    yosys synth -top $top -flatten
    yosys dfflibmap -liberty $lib
    yosys abc -liberty $lib
} elseif {$mode eq "hier"} {
    yosys synth -top $top
    yosys dfflibmap -liberty $lib
    if {[info exists ::env(SYNTH_ABC_FAST)] && $::env(SYNTH_ABC_FAST) eq "1"} {
        yosys abc -fast -liberty $lib
    } else {
        yosys abc -liberty $lib
    }
} elseif {$mode eq "minmap"} {
    # No -flatten: like hier, but the ABC call uses a minimal script
    # (`strash; map`; the brace keeps Tcl from splitting on the `;`, and
    # inside yosys the comma in a +script becomes a blank -- the ABC call
    # is equivalent to `abc -script 'strash; map'`)
    yosys synth -top $top -noabc
    yosys dfflibmap -liberty $lib
    yosys abc -liberty $lib -script {+strash;,map}
} else {
    error "SYNTH_MODE must be flat, hier or minmap, got '$mode'"
}
yosys opt_clean -purge
yosys tee -o $out/cell_count.rpt stat -liberty $lib
yosys write_verilog -noattr $net
