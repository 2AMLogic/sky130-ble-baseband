# Single entry point for the verification / lint / synthesis flow.
#   make            -> all: check-tools, test, test-negative, test-le1m-rx, test-le1m-rx-negative, lint, synth,
#                      model-test, test-le1m-tx, test-le1m-tx-negative
#                      (test/test-negative/lint include the rtl/mac/ lower-MAC benches)
# Cold start: see verification/README.md. ALLOW_TOOL_DRIFT=1 downgrades tool
# version mismatches to warnings (CI only; local runs must match the pins).

include flow/versions.mk

BUILD    := flow/build/smoke
LE1M_TX_BUILD := flow/build/le1m_tx
LE1M_TX_RTL := $(addprefix rtl/le1m_tx/,le1m_whiten.v le1m_crc24.v le1m_frame.v le1m_gauss.v le1m_tx.v)
LE1M_RX  := flow/build/le1m_rx
VENV     := .venv
PYTHON   ?= $(VENV)/bin/python
CIEL_HOME?= $(HOME)/.ciel
PDK_ROOT ?= $(CIEL_HOME)/ciel/$(PDK_FAMILY)/versions/$(PDK_REV)
LIB_FILE := $(PDK_ROOT)/$(PDK_VARIANT)/libs.ref/$(STD_CELL_LIB)/lib/$(STD_CELL_LIB)__$(LIB_CORNER).lib

.PHONY: all venv check-tools check-pdk test test-negative lint synth clean model-test host-test host-test-negative host-lint test-le1m-rx test-le1m-rx-negative test-le1m-tx test-le1m-tx-negative mac-test mac-test-negative mac-lint

all: check-tools test test-negative test-le1m-rx test-le1m-rx-negative lint synth model-test test-le1m-tx test-le1m-tx-negative

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

test: check-tools host-test
	$(PYTHON) verification/smoke/run_smoke.py $(CURDIR)/$(BUILD)/sim
	$(MAKE) mac-test

# The test must FAIL when an expectation is wrong; invert the exit status.
test-negative: check-tools host-test-negative
	@mkdir -p $(BUILD)
	@if LFSR_NEGATIVE=1 $(PYTHON) verification/smoke/run_smoke.py $(CURDIR)/$(BUILD)/sim_neg >$(BUILD)/negative.log 2>&1; then \
	  echo "ERROR: negative control passed; the test does not detect a broken expectation"; exit 1; \
	else grep -q 'expected=' $(BUILD)/negative.log || { echo "ERROR: negative control failed for the wrong reason; see $(BUILD)/negative.log"; exit 1; }; \
	  echo "negative control OK (broken expectation was rejected)"; fi
	$(MAKE) mac-test-negative

# LE 1M RX RTL: shared stimulus replayed through cocotb + Icarus, compared with
# sim/model/le1m_rx.py by sample index (decision 0007). Vectors are regenerated
# from the case table in verification/le1m_rx/cases.py.
test-le1m-rx: check-tools
	$(PYTHON) verification/le1m_rx/run_le1m_rx.py $(CURDIR)/$(LE1M_RX)/sim

# A perturbed expectation must be rejected, and for the right reason: the
# mismatch report carries `expected=`.
test-le1m-rx-negative: check-tools
	@mkdir -p $(LE1M_RX)
	@if LE1M_RX_NEGATIVE=1 $(PYTHON) verification/le1m_rx/run_le1m_rx.py $(CURDIR)/$(LE1M_RX)/sim_neg nominal_noiseless >$(LE1M_RX)/negative.log 2>&1; then \
	  echo "ERROR: le1m_rx negative control passed; the replay does not detect a broken expectation"; exit 1; \
	else grep -q 'first mismatch.*expected=' $(LE1M_RX)/negative.log || { echo "ERROR: le1m_rx negative control failed for the wrong reason; see $(LE1M_RX)/negative.log"; exit 1; }; \
	  echo "le1m_rx negative control OK (perturbed expectation was rejected)"; fi

lint: check-tools host-lint
	verilator --lint-only -Wall --top-module lfsr8 rtl/smoke/lfsr8.v
	verilator --lint-only -Wall --top-module le1m_tx $(LE1M_TX_RTL)
	verilator --lint-only -Wall --top-module le1m_rx rtl/le1m_rx/*.v
	$(MAKE) mac-lint

synth: check-tools check-pdk
	mkdir -p $(BUILD)
	SMOKE_LIB=$(LIB_FILE) SMOKE_OUT=$(BUILD) yosys -q -l $(BUILD)/yosys.log -c flow/synth/smoke.tcl
	@{ echo "pdk_rev: $(PDK_REV)"; echo "liberty: $(LIB_FILE)"; echo "corner: $(LIB_CORNER)"; \
	   echo "yosys: $$(yosys -V)"; } > $(BUILD)/liberty_record.txt
	@grep -q sky130_fd_sc_hd $(BUILD)/lfsr8_netlist.v || { echo "ERROR: netlist has no sky130_fd_sc_hd cells"; exit 1; }
	@echo "synth OK: $(BUILD)/lfsr8_netlist.v, cell_count.rpt, liberty_record.txt"

# Host interface (rtl/host/): APB registers, FIFOs, interrupts, timestamps.
HOST_BUILD := flow/build/host
HOST_RTL   := $(addprefix rtl/host/,host_fifo.v host_desc_fifo.v host_irq.v host_timestamp.v host_regs.v host_top.v)

host-test: check-tools
	$(PYTHON) verification/host/run_host.py $(CURDIR)/$(HOST_BUILD)/sim

# A broken expectation (W1C on a disabled INT_STATUS bit) must FAIL the bench.
host-test-negative: check-tools
	@mkdir -p $(HOST_BUILD)
	@if HOST_NEGATIVE=1 $(PYTHON) verification/host/run_host.py $(CURDIR)/$(HOST_BUILD)/sim_neg >$(HOST_BUILD)/negative.log 2>&1; then \
	  echo "ERROR: host negative control passed; the test does not detect a broken expectation"; exit 1; \
	else grep -q 'expected=' $(HOST_BUILD)/negative.log || { echo "ERROR: host negative control failed for the wrong reason; see $(HOST_BUILD)/negative.log"; exit 1; }; \
	  echo "host negative control OK (broken expectation was rejected)"; fi

host-lint: check-tools
	verilator --lint-only -Wall --top-module host_top $(HOST_RTL)

clean:
	rm -rf flow/build

# LE 1M TX reference model tests (sim/model). Pure Python: no simulator, so no
# check-tools. The CRC negative control must FAIL the CRC known-answer test.
model-test:
	@mkdir -p $(BUILD)
	$(PYTHON) -m pytest -q sim/tests
	@if CRC_NEGATIVE=1 $(PYTHON) -m pytest -q sim/tests -k crc24_kat >$(BUILD)/model_negative.log 2>&1; then \
	  echo "ERROR: model negative control passed; the CRC known-answer test does not detect a flipped init"; exit 1; \
	else grep -q 'crc24 KAT mismatch' $(BUILD)/model_negative.log || { echo "ERROR: model negative control failed for the wrong reason; see $(BUILD)/model_negative.log"; exit 1; }; \
	  echo "model negative control OK (flipped CRC init was rejected)"; fi

# sim/: CM-A channel, integer LE 1M receiver, BER sweep (needs numpy, pytest from `make venv`)
.PHONY: sim-test sim-quick

sim-test:
	$(PYTHON) -m pytest -q sim/tests

sim-quick:
	$(PYTHON) sim/sweep/ber_sweep.py --quick --out $(CURDIR)/flow/build/sim/ber.json

# LE 1M TX RTL: cocotb replay of the model's traces (golden + generated packets),
# bit-exact per decision 0007. The negative control corrupts one expected txdev
# record, so the replay must FAIL with the 'tx trace mismatch' message.
test-le1m-tx: check-tools
	$(PYTHON) verification/le1m_tx/run_le1m_tx.py $(CURDIR)/$(LE1M_TX_BUILD)/sim

test-le1m-tx-negative: check-tools
	@mkdir -p $(LE1M_TX_BUILD)
	@if LE1M_TX_NEGATIVE=1 $(PYTHON) verification/le1m_tx/run_le1m_tx.py $(CURDIR)/$(LE1M_TX_BUILD)/sim_neg >$(LE1M_TX_BUILD)/negative.log 2>&1; then \
	  echo "ERROR: LE 1M TX negative control passed; the replay does not detect a wrong expected word"; exit 1; \
	else grep -q 'tx trace mismatch: .*field txdev' $(LE1M_TX_BUILD)/negative.log || { echo "ERROR: LE 1M TX negative control failed for the wrong reason; see $(LE1M_TX_BUILD)/negative.log"; exit 1; }; \
	  echo "le1m_tx negative control OK (corrupted txdev record was rejected)"; fi

# rtl/mac/: lower-MAC timers, trigger, auto-ACK, address filters (issue #51).
# Cycle-count benches at the 32 MHz target counts and the 16 MHz fallback counts.
MAC_BUILD := flow/build/mac
MAC_MODULES := mac_timer mac_trigger mac_ack_ctrl mac_ackwait mac_le_resp mac_addr_filter_154 mac_le_filter

mac-test: check-tools
	@mkdir -p $(MAC_BUILD)
	@for mhz in 32 16; do \
	  PYTHONPATH=verification/mac $(PYTHON) verification/mac/run_mac.py $(CURDIR)/$(MAC_BUILD)/sim $$mhz >$(MAC_BUILD)/mac$$mhz.log 2>&1 \
	    || { grep -E 'FAIL|Error|failed' $(MAC_BUILD)/mac$$mhz.log | tail -20; echo "ERROR: mac benches failed at $$mhz MHz; see $(MAC_BUILD)/mac$$mhz.log"; exit 1; }; \
	  grep -E '^(cocotb mac @|MEASURED)' $(MAC_BUILD)/mac$$mhz.log; \
	done

# Same benches with wrong cycle-budget expectations (MAC_NEGATIVE=1); must fail.
mac-test-negative: check-tools
	@mkdir -p $(MAC_BUILD)
	@if MAC_NEGATIVE=1 PYTHONPATH=verification/mac $(PYTHON) verification/mac/run_mac.py $(CURDIR)/$(MAC_BUILD)/sim_neg 32 >$(MAC_BUILD)/negative.log 2>&1; then \
	  echo "ERROR: mac negative control passed; the cycle-budget tests do not detect a wrong expectation"; exit 1; \
	else grep -q 'expected=' $(MAC_BUILD)/negative.log || { echo "ERROR: mac negative control failed for the wrong reason; see $(MAC_BUILD)/negative.log"; exit 1; }; \
	  echo "mac negative control OK (wrong cycle budgets were rejected)"; fi

mac-lint: check-tools
	@for m in $(MAC_MODULES); do verilator --lint-only -Wall --top-module $$m rtl/mac/*.v || exit 1; done; echo "mac lint OK"
