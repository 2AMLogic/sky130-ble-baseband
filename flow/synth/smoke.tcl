# Synthesis smoke for the placeholder LFSR (run as `yosys -c`).
# Inputs from the environment: SMOKE_LIB (liberty file), SMOKE_OUT (run dir).
set lib $::env(SMOKE_LIB)
set out $::env(SMOKE_OUT)
yosys read_verilog -sv rtl/smoke/lfsr8.v
yosys hierarchy -check -top lfsr8
yosys synth -top lfsr8 -flatten
yosys dfflibmap -liberty $lib
yosys abc -liberty $lib
yosys opt_clean -purge
yosys tee -o $out/cell_count.rpt stat -liberty $lib
yosys write_verilog -noattr $out/lfsr8_netlist.v
