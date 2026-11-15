# Single entry point for the verification / lint / synthesis flow.
#   make            -> all: check-tools, test, test-negative, test-le1m-rx, test-le1m-rx-negative, lint, synth,
#                      model-test, parser-test, test-le1m-tx, test-le1m-tx-negative, test-oqpsk, test-oqpsk-negative,
#                      test-top, test-top-negative
#                      (test/test-negative/lint include the rtl/host and rtl/mac benches)
# `make synth` rewrites the committed netlist flow/synth/baseband_top_netlist.v;
# `make synth-check` regenerates it in flow/build/ and fails if it differs.
# Cold start: see verification/README.md. ALLOW_TOOL_DRIFT=1 downgrades tool
# version mismatches to warnings (CI only; local runs must match the pins).

include flow/versions.mk

BUILD    := flow/build/model
TOP      := flow/build/top
SYNTH_BUILD := flow/build/synth
NETLIST  := flow/synth/baseband_top_netlist.v
LIBREC   := flow/synth/liberty_record.txt
RTL_LIST := rtl/baseband.f
# Per-block source lists are sections of $(RTL_LIST), read by the one parser the
# Python benches also use. $(FLISTS)/<block>.f is a generated `verilator -f`
# file list: never hand-edit one, and never hand-keep a second copy of a block's
# files here (issue #118).
RTL_SOURCES := verification/rtl_sources.py
FLISTS   := flow/build/filelists
LE1M_TX_BUILD := flow/build/le1m_tx
LE1M_RX  := flow/build/le1m_rx
OQPSK    := flow/build/oqpsk
VENV     := .venv
PYTHON   ?= $(VENV)/bin/python
CIEL_HOME?= $(HOME)/.ciel
PDK_ROOT ?= $(CIEL_HOME)/ciel/$(PDK_FAMILY)/versions/$(PDK_REV)
LIB_FILE := $(PDK_ROOT)/$(PDK_VARIANT)/libs.ref/$(STD_CELL_LIB)/lib/$(STD_CELL_LIB)__$(LIB_CORNER).lib

.PHONY: all venv check-tools check-pdk check-rtl-list test test-negative lint synth clean model-test parser-test host-test host-test-negative host-lint test-le1m-rx test-le1m-rx-negative test-le1m-tx test-le1m-tx-negative test-oqpsk test-oqpsk-negative test-top test-top-negative synth-check mac-test mac-test-negative mac-lint

all: check-tools test test-negative test-le1m-rx test-le1m-rx-negative lint synth model-test parser-test test-le1m-tx test-le1m-tx-negative test-oqpsk test-oqpsk-negative test-top test-top-negative

venv:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -r requirements.txt

# need_tool <exe> <expected version prefix> <version command>
define need_tool
@command -v $(1) >/dev/null || { echo "ERROR: required tool '$(1)' not found on PATH"; exit 1; }
@v="$$($(3) 2>&1 | grep -o -m1 '$(2)[0-9.]*' | head -1)"; \
 case "$$v" in $(2)*) ;; *) echo "$(if $(ALLOW_TOOL_DRIFT),WARNING,ERROR): $(1) version mismatch: want $(2)*, got '$$v' (pins: flow/versions.mk)"; $(if $(ALLOW_TOOL_DRIFT),true,exit 1);; esac
endef

# negative_control <build dir> <perturb env assignment> <runner> <log path> \
#   <right-reason grep pattern> <error label> <pass why> <ok label> <ok why> [<min count>]
# The single copy of the guard every negative-control target runs: the bench
# must FAIL under its perturb env var, and for the stated right reason. The
# grep pattern is passed bare (no quotes) — the body quotes it; a comma would
# split the $(call) argument list. A min count turns the right-reason check
# into a grep -c threshold instead of the default grep -q presence test.
define negative_control
mkdir -p $(1); \
if $(2) $(3) >$(4) 2>&1; then \
  echo "ERROR: $(6) negative control passed; $(7)"; exit 1; \
else $(if $(10),n=$$(grep -c '$(5)' $(4)); [ "$$n" -ge $(10) ] || { echo "ERROR: $(6) negative control failed for the wrong reason ($$n $(5) reports of $(10)); see $(4)"; exit 1; },grep -q '$(5)' $(4) || { echo "ERROR: $(6) negative control failed for the wrong reason; see $(4)"; exit 1; }); \
  echo "$(8) negative control OK ($(9))"; fi
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
	$(MAKE) mac-test

# The tests must FAIL when an expectation is wrong; invert the exit status.
test-negative: check-tools host-test-negative
	$(MAKE) mac-test-negative

# LE 1M RX RTL: shared stimulus replayed through cocotb + Icarus, compared with
# sim/model/le1m_rx.py by sample index (decision 0007). Vectors are regenerated
# from the case table in verification/le1m_rx/cases.py.
test-le1m-rx: check-tools
	$(PYTHON) verification/le1m_rx/run_le1m_rx.py $(CURDIR)/$(LE1M_RX)/sim

# A perturbed expectation must be rejected, and for the right reason: the
# mismatch report carries `expected=`.
test-le1m-rx-negative: check-tools
	@$(call negative_control,$(LE1M_RX),LE1M_RX_NEGATIVE=1,$(PYTHON) verification/le1m_rx/run_le1m_rx.py $(CURDIR)/$(LE1M_RX)/sim_neg nominal_noiseless,$(LE1M_RX)/negative.log,first mismatch.*expected=,le1m_rx,the replay does not detect a broken expectation,le1m_rx,perturbed expectation was rejected)

# 802.15.4 O-QPSK RTL (rtl/oqpsk): TX words and RX trace taps replayed through
# cocotb + Icarus against sim/model/oqpsk_{tx,rx}.py by sample index (decision
# 0007), including the committed golden traces. The RX top reuses two LE 1M
# stages unchanged; the `# block: oqpsk_rx` section of rtl/baseband.f names them.
test-oqpsk: check-tools
	$(PYTHON) verification/oqpsk/run_oqpsk.py $(CURDIR)/$(OQPSK)/sim

# A perturbed expectation must be rejected by each half, and for the right
# reason: the mismatch report carries `expected=`.
test-oqpsk-negative: check-tools
	@for half in "tx payload3" "rx psdu1_no_fcs"; do set -- $$half; \
	  $(call negative_control,$(OQPSK),OQPSK_NEGATIVE=1,$(PYTHON) verification/oqpsk/run_oqpsk.py $(CURDIR)/$(OQPSK)/sim_neg_$$1 $$1 $$2,$(OQPSK)/negative_$$1.log,first mismatch.*expected=,oqpsk $$1,the replay does not detect a broken expectation,oqpsk $$1,perturbed expectation was rejected); \
	done

# A .v on disk that $(RTL_LIST) does not declare would be linted by nothing
# and synthesised into nothing; a declared path that is missing breaks both.
check-rtl-list:
	@python3 $(RTL_SOURCES) --check

$(FLISTS)/%.f: $(RTL_LIST) $(RTL_SOURCES)
	python3 $(RTL_SOURCES) --out $@ $*

LINT_BLOCKS := le1m_tx le1m_rx oqpsk_tx oqpsk_rx

lint: check-tools check-rtl-list host-lint $(addprefix $(FLISTS)/,$(addsuffix .f,$(LINT_BLOCKS)))
	verilator --lint-only -Wall --top-module baseband_top -f $(RTL_LIST)
	verilator --lint-only -Wall --top-module le1m_tx -f $(FLISTS)/le1m_tx.f
	verilator --lint-only -Wall --top-module le1m_rx -f $(FLISTS)/le1m_rx.f
	verilator --lint-only -Wall --top-module oqpsk_tx -f $(FLISTS)/oqpsk_tx.f
	verilator --lint-only -Wall --top-module oqpsk_rx -f $(FLISTS)/oqpsk_rx.f
	$(MAKE) mac-lint

# Synthesis of baseband_top at the pinned liberty corner (flow/versions.mk), flattened
# and mapped to sky130_fd_sc_hd. Cell counts and area are not timing claims (those
# belong to the STA item and name their own corner). The committed netlist and its
# liberty record are the item-1 derived artifacts; `synth-check` is their freshness check.
define run_synth
mkdir -p $(1)
SYNTH_TOP=baseband_top SYNTH_LIST=$(RTL_LIST) SYNTH_LIB=$(LIB_FILE) SYNTH_OUT=$(1) SYNTH_NETLIST=$(2) \
  yosys -q -l $(1)/yosys.log -c flow/synth/synth.tcl
@{ echo "pdk_rev: $(PDK_REV)"; echo "liberty: $(STD_CELL_LIB)__$(LIB_CORNER).lib"; echo "corner: $(LIB_CORNER)"; \
   echo "yosys: $$(yosys -V)"; } > $(3)
@grep -q sky130_fd_sc_hd $(2) || { echo "ERROR: netlist has no sky130_fd_sc_hd cells"; exit 1; }
endef

synth: check-tools check-pdk
	$(call run_synth,$(SYNTH_BUILD),$(NETLIST),$(LIBREC))
	@echo "synth OK: $(NETLIST), $(LIBREC); reports in $(SYNTH_BUILD)/"

synth-check: check-tools check-pdk
	$(call run_synth,$(SYNTH_BUILD)/fresh,$(SYNTH_BUILD)/fresh/netlist.v,$(SYNTH_BUILD)/fresh/liberty_record.txt)
	@cmp $(NETLIST) $(SYNTH_BUILD)/fresh/netlist.v || { echo "ERROR: committed netlist is stale; run 'make synth' and commit"; exit 1; }
	@cmp $(LIBREC) $(SYNTH_BUILD)/fresh/liberty_record.txt || { echo "ERROR: committed liberty record is stale; run 'make synth' and commit"; exit 1; }
	@echo "synth-check OK: committed netlist reproduced byte-for-byte"

# Integration bench (verification/top): baseband_top with every sub-block, APB in,
# samples / tx words at the front-end pins.
test-top: check-tools
	$(PYTHON) verification/top/run_top.py $(CURDIR)/$(TOP)/sim

# Each test perturbs one expected value; the run must fail with `expected=`.
test-top-negative: check-tools
	@$(call negative_control,$(TOP),TOP_NEGATIVE=1,$(PYTHON) verification/top/run_top.py $(CURDIR)/$(TOP)/sim_neg,$(TOP)/negative.log,expected=,top,the bench does not detect a broken expectation,top,every perturbed expectation was rejected,7)

# Host interface (rtl/host/): APB registers, FIFOs, interrupts, timestamps.
HOST_BUILD := flow/build/host

host-test: check-tools
	$(PYTHON) verification/host/run_host.py $(CURDIR)/$(HOST_BUILD)/sim

# A broken expectation (W1C on a disabled INT_STATUS bit) must FAIL the bench.
host-test-negative: check-tools
	@$(call negative_control,$(HOST_BUILD),HOST_NEGATIVE=1,$(PYTHON) verification/host/run_host.py $(CURDIR)/$(HOST_BUILD)/sim_neg,$(HOST_BUILD)/negative.log,expected=,host,the test does not detect a broken expectation,host,broken expectation was rejected)

host-lint: check-tools $(FLISTS)/host.f
	verilator --lint-only -Wall --top-module host_top -f $(FLISTS)/host.f

clean:
	rm -rf flow/build

# LE 1M TX reference model tests (sim/model). Pure Python: no simulator, so no
# check-tools. The CRC negative control must FAIL the CRC known-answer test.
model-test:
	@mkdir -p $(BUILD)
	$(PYTHON) -m pytest -q sim/tests
	@$(call negative_control,$(BUILD),CRC_NEGATIVE=1,$(PYTHON) -m pytest -q sim/tests -k crc24_kat,$(BUILD)/model_negative.log,crc24 KAT mismatch,model,the CRC known-answer test does not detect a flipped init,model,flipped CRC init was rejected)

# The file-list parser's own tests (verification/tests, issue #147). Pure
# Python: no simulator and no PDK, so no check-tools. The parser gates
# check-rtl-list and every generated per-block list, so a regression here
# fails in the same CI job (flow) as the lint it would break.
parser-test:
	$(PYTHON) -m pytest -q verification/tests

# sim/: CM-A channels, integer LE 1M and 802.15.4 receivers, BER and PER sweeps (needs numpy, pytest from `make venv`)
.PHONY: sim-test sim-quick

sim-test:
	$(PYTHON) -m pytest -q sim/tests

sim-quick:
	$(PYTHON) sim/sweep/ber_sweep.py --quick --out $(CURDIR)/flow/build/sim/ber.json
	$(PYTHON) sim/sweep/per_sweep.py --quick --out $(CURDIR)/flow/build/sim/per.json

# LE 1M TX RTL: cocotb replay of the model's traces (golden + generated packets),
# bit-exact per decision 0007. The negative control corrupts one expected txdev
# record, so the replay must FAIL with the 'tx trace mismatch' message.
test-le1m-tx: check-tools
	$(PYTHON) verification/le1m_tx/run_le1m_tx.py $(CURDIR)/$(LE1M_TX_BUILD)/sim

test-le1m-tx-negative: check-tools
	@$(call negative_control,$(LE1M_TX_BUILD),LE1M_TX_NEGATIVE=1,$(PYTHON) verification/le1m_tx/run_le1m_tx.py $(CURDIR)/$(LE1M_TX_BUILD)/sim_neg,$(LE1M_TX_BUILD)/negative.log,tx trace mismatch: .*field txdev,LE 1M TX,the replay does not detect a wrong expected word,le1m_tx,corrupted txdev record was rejected)

# rtl/mac/: lower-MAC timers, trigger, auto-ACK, address filters (issue #51).
# Cycle-count benches at the 32 MHz target counts and the 16 MHz fallback counts.
MAC_BUILD := flow/build/mac

mac-test: check-tools
	@mkdir -p $(MAC_BUILD)
	@for mhz in 32 16; do \
	  PYTHONPATH=verification/mac $(PYTHON) verification/mac/run_mac.py $(CURDIR)/$(MAC_BUILD)/sim $$mhz >$(MAC_BUILD)/mac$$mhz.log 2>&1 \
	    || { grep -E 'FAIL|Error|failed' $(MAC_BUILD)/mac$$mhz.log | tail -20; echo "ERROR: mac benches failed at $$mhz MHz; see $(MAC_BUILD)/mac$$mhz.log"; exit 1; }; \
	  grep -E '^(cocotb mac @|MEASURED)' $(MAC_BUILD)/mac$$mhz.log; \
	done

# Same benches with wrong cycle-budget expectations (MAC_NEGATIVE=1); must fail.
mac-test-negative: check-tools
	@$(call negative_control,$(MAC_BUILD),MAC_NEGATIVE=1,PYTHONPATH=verification/mac $(PYTHON) verification/mac/run_mac.py $(CURDIR)/$(MAC_BUILD)/sim_neg 32,$(MAC_BUILD)/negative.log,expected=,mac,the cycle-budget tests do not detect a wrong expectation,mac,wrong cycle budgets were rejected)

mac-lint: check-tools $(FLISTS)/mac.f
	@mods=$$(python3 $(RTL_SOURCES) --modules mac) || exit 1; \
	 for m in $$mods; do verilator --lint-only -Wall --top-module $$m -f $(FLISTS)/mac.f || exit 1; done; \
	 echo "mac lint OK"
