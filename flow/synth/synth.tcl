# Top-level synthesis (run as `yosys -c`), generalised from the old smoke script.
# Inputs from the environment:
#   SYNTH_TOP   top module name
#   SYNTH_LIST  RTL file list, one repo-relative path per line (rtl/baseband.f)
#   SYNTH_LIB   liberty file (pinned corner, flow/versions.mk)
#   SYNTH_OUT   run directory for the reports
#   SYNTH_NETLIST  path of the netlist to write
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
yosys synth -top $top -flatten
yosys dfflibmap -liberty $lib
yosys abc -liberty $lib
yosys opt_clean -purge
yosys tee -o $out/cell_count.rpt stat -liberty $lib
yosys write_verilog -noattr $net
