# Pinned flow versions. The Makefile fails loudly when the installed tools or
# the resolved PDK differ from these. Bump deliberately, in its own commit.

# Python dependencies are pinned in requirements.txt (cocotb).
PYTHON_MIN       := 3.10
ICARUS_VERSION   := 13.0
VERILATOR_VERSION:= 5.050
YOSYS_VERSION    := 0.67
# Recorded for the later place-and-route step; not invoked by this flow.
OPENROAD_VERSION := 26Q3-1510-g6cb3f2b704

# sky130 PDK revision (open_pdks commit as distributed by ciel).
PDK_REV          := f6eeac7dad085ffcc829ccfd721f7b4ce39edcf7
PDK_FAMILY       := sky130
PDK_VARIANT      := sky130A
STD_CELL_LIB     := sky130_fd_sc_hd
# Typical liberty corner used for every synthesis record.
LIB_CORNER       := tt_025C_1v80
