# sky130-ble-baseband — agent instructions

Open-source canary block: a BLE LE 1M + IEEE 802.15.4 digital baseband
(modems plus hardware lower MAC) on SkyWater sky130, designed and verified
by AI agents. **Digital.**

- **PDK**: SkyWater sky130 (open PDK, google/skywater-pdk), `sky130_fd_sc_hd`
  standard cells. Digital: cocotb + Icarus, Yosys, OpenROAD. Layout, DRC,
  and LVS through klayout-tools (`klt`).
- **Statistical correctness is the point, and the risk.** A modem is right
  when its error rate is right under noise, carrier-frequency offset,
  sample-clock drift and multipath. So the chain is: a reference receiver in
  `sim/` with a declared channel model → error-rate sweeps on it → RTL that
  matches it bit-exactly on shared stimulus. A BER claim that was computed
  on the model and not tied to the RTL by bit-exactness is not a claim
  about this block. Every error-rate result is simulated and says so.
- **Scope discipline.** This repo has no `consumes:` edge, and the fleet has
  no 2.4 GHz front end on sky130. Do not design an RF front end, ADC, DAC or
  synthesizer here. Specify the digital interface to them — I/Q sample rate
  and width, AGC and RSSI hooks, the TX modulation output — and stop. The
  upper link layer and protocol stacks are host software; the hardware/
  software split is a decision record, not drift.
- **Friction protocol (the canary's job)**: every time klayout-tools is
  awkward, missing a capability, or wrong for what you need, file an issue at
  `2AMLogic/klayout-tools` describing the tool gap generically — that tracker
  is scoped to the tool, so keep design-specific detail out of it and describe
  the gap, not the design.
- **Verification is the product**: no claim without a testbench. Every timing
  claim names its liberty corner; recorded results are append-only evidence.
- Spec changes go through `spec/` with a decision record; agents do not relax
  the ratified spec to make results pass.
- **LE 1M + 802.15.4 is the target.** LE 1M alone is the fallback and LE 2M a
  stretch. Do not let LE 2M or coded-PHY requirements drive architecture
  before the target closes.

## On Bluetooth, and what may be said

The Bluetooth word mark and logos belong to the Bluetooth SIG, and their use
on a product is tied to the SIG's qualification process. This block is a
**baseband implementing the LE 1M physical layer as described in the
Bluetooth Core Specification**, and an IEEE 802.15.4 O-QPSK baseband. Refer
to the specifications by name only to say which one a behaviour follows. Do
not use the Bluetooth logo, do not describe this block as a Bluetooth product
or as qualified, and do not imply compliance or certification with either
standard. Do not name protocol stacks built on 802.15.4. Copy no text or
figures from the specifications into this repo; cite section numbers.
