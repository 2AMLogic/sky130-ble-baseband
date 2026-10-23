# Single entry point for the verification / lint / synthesis flow.
#   make            -> all: check-tools, test, test-negative, lint, synth
# Cold start: see verification/README.md. ALLOW_TOOL_DRIFT=1 downgrades tool
# version mismatches to warnings (CI only; local runs must match the pins).

include flow/versions.mk

BUILD    := flow/build/smoke
VENV     := .venv
PYTHON   ?= $(VENV)/bin/python
CIEL_HOME?= $(HOME)/.ciel
PDK_ROOT ?= $(CIEL_HOME)/ciel/$(PDK_FAMILY)/versions/$(PDK_REV)
LIB_FILE := $(PDK_ROOT)/$(PDK_VARIANT)/libs.ref/$(STD_CELL_LIB)/lib/$(STD_CELL_LIB)__$(LIB_CORNER).lib

.PHONY: all venv check-tools check-pdk test test-negative lint synth clean

all: check-tools test test-negative lint synth

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

# need_tool <exe> <expected version prefix> <version command>
define need_tool
@command -v $(1) >/dev/null || { echo "ERROR: required tool '$(1)' not found on PATH"; exit 1; }
@v="$$($(3) 2>&1 | grep -o -m1 '$(2)[0-9.]*' | head -1)"; \
 case "$$v" in $(2)*) ;; *) echo "$(if $(ALLOW_TOOL_DRIFT),WARNING,ERROR): $(1) version mismatch: want $(2)*, got '$$v' (pins: flow/versions.mk)"; $(if $(ALLOW_TOOL_DRIFT),true,exit 1);; esac
endef

check-tools:
	$(call need_tool,iverilog,$(ICARUS_VERSION),iverilog -V)
	$(call need_tool,verilator,$(VERILATOR_VERSION),verilator --version)
	$(call need_tool,yosys,$(YOSYS_VERSION),yosys -V)
	@test -x $(PYTHON) || { echo "ERROR: $(PYTHON) missing; run 'make venv'"; exit 1; }
	@$(PYTHON) -c 'import cocotb; assert cocotb.__version__=="$(shell sed -n 's/^cocotb==//p' requirements.txt)", cocotb.__version__' \
	  || { echo "ERROR: cocotb version mismatch (pin: requirements.txt)"; exit 1; }
	@command -v openroad >/dev/null && echo "openroad: $$(openroad -version | head -1) (pin for later P&R: $(OPENROAD_VERSION))" \
	  || echo "note: openroad not on PATH (only needed for later P&R; pin $(OPENROAD_VERSION))"

check-pdk:
	@test -f "$(LIB_FILE)" || { echo "ERROR: pinned PDK $(PDK_REV) liberty not found: $(LIB_FILE)"; \
	  echo "Fetch it: pip install ciel && ciel enable --pdk-family $(PDK_FAMILY) $(PDK_REV)"; exit 1; }

test: check-tools
	$(PYTHON) verification/smoke/run_smoke.py $(CURDIR)/$(BUILD)/sim

# The test must FAIL when an expectation is wrong; invert the exit status.
test-negative: check-tools
	@mkdir -p $(BUILD)
	@if LFSR_NEGATIVE=1 $(PYTHON) verification/smoke/run_smoke.py $(CURDIR)/$(BUILD)/sim_neg >$(BUILD)/negative.log 2>&1; then \
	  echo "ERROR: negative control passed; the test does not detect a broken expectation"; exit 1; \
	else grep -q 'expected=' $(BUILD)/negative.log || { echo "ERROR: negative control failed for the wrong reason; see $(BUILD)/negative.log"; exit 1; }; \
	  echo "negative control OK (broken expectation was rejected)"; fi

lint: check-tools
	verilator --lint-only -Wall --top-module lfsr8 rtl/smoke/lfsr8.v

synth: check-tools check-pdk
	mkdir -p $(BUILD)
	SMOKE_LIB=$(LIB_FILE) SMOKE_OUT=$(BUILD) yosys -q -l $(BUILD)/yosys.log -c flow/synth/smoke.tcl
	@{ echo "pdk_rev: $(PDK_REV)"; echo "liberty: $(LIB_FILE)"; echo "corner: $(LIB_CORNER)"; \
	   echo "yosys: $$(yosys -V)"; } > $(BUILD)/liberty_record.txt
	@grep -q sky130_fd_sc_hd $(BUILD)/lfsr8_netlist.v || { echo "ERROR: netlist has no sky130_fd_sc_hd cells"; exit 1; }
	@echo "synth OK: $(BUILD)/lfsr8_netlist.v, cell_count.rpt, liberty_record.txt"

clean:
	rm -rf flow/build

# sim/: CM-A channel, integer LE 1M receiver, BER sweep (needs numpy, pytest from `make venv`)
.PHONY: sim-test sim-quick

sim-test:
	$(PYTHON) -m pytest -q sim/tests

sim-quick:
	$(PYTHON) sim/sweep/ber_sweep.py --quick --out $(CURDIR)/flow/build/sim/ber.json
