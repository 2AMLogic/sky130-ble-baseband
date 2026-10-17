# sky130-ble-baseband

A digital baseband for 2.4 GHz low-power radios on the
[SkyWater sky130](https://github.com/google/skywater-pdk) open PDK — a
Bluetooth Low Energy LE 1M GFSK modem and an IEEE 802.15.4 O-QPSK modem,
with the time-critical lower MAC / link-layer functions in hardware —
designed by AI agents driving
[klayout-tools](https://github.com/2AMLogic/klayout-tools) and the
open-source digital flow: cocotb + Icarus for verification, Yosys for
synthesis, OpenROAD for place-and-route.

**Status: just opened, specification phase.** Nothing is designed yet.

**Built agent-native.** Every specification, decision record, testbench, and
line of documentation here is produced by AI agents working from a ratified
spec and an append-only evidence trail — not human-authored work that agents
merely assisted with. Verification is the product: every claim traces to a
recorded result. Where the agents hit friction with the open-source tooling —
most often [klayout-tools](https://github.com/2AMLogic/klayout-tools) — that
friction is filed as a public issue against the tool itself, so the fix
benefits everyone using sky130, not just this repo.

## Why this block, on this node

A radio baseband is a digital block whose correctness is statistical. The
modem is judged by bit- and packet-error rates under noise, frequency
offset and timing drift, not by a single expected output — so the
verification has to be a link-level simulation with a channel model, and
the RTL has to match a reference receiver bit-exactly so that the
statistics computed on the model hold for the hardware.

Both physical layers are low symbol rate (LE 1M is 1 Msym/s; 802.15.4 at
2.4 GHz is 2 Mchip/s), so the datapath fits comfortably in sky130 standard
cells. The difficulty is elsewhere: synchronization, frequency-offset
tolerance, and hard real-time turnaround (the LE inter-frame space is
150 µs; 802.15.4 turnaround is 12 symbol periods) that the hardware must
meet with no software in the loop.

## Scope

- **In scope**: LE 1M GFSK modulator and demodulator; 802.15.4 2.4 GHz
  O-QPSK spreader and despreader; preamble/access-address/SFD detection;
  CRC (CRC-24 for LE, the 16-bit FCS for 802.15.4); LE data whitening;
  packet framing; hardware timers for inter-frame turnaround and automatic
  acknowledgement; a register and FIFO interface to a host.
- **Not in scope**: the RF front end, ADC, DAC or synthesizer — this repo
  specifies the digital interface to them (I/Q sample format and rate, AGC
  hooks, TX modulation output) and stops; the upper link layer and the
  protocol stacks, which run as software on a host.
- **Not claimed**: any qualification, certification or standards
  compliance. See `CLAUDE.md` for what may be said.

## Target specification (DRAFT — engineering to ratify, see issue #2)

| Parameter | Target | Fallback | Stretch |
|---|---|---|---|
| PHYs | LE 1M GFSK + 802.15.4 O-QPSK | LE 1M only | LE 2M |
| RX input | 8 Msps complex I/Q, ≤ 8-bit | 4 Msps | — |
| LE 1M demod | BER ≤ 1e-3 at a ratified Eb/N0 in AWGN, with frequency offset | — | coded PHY |
| 802.15.4 demod | PER < 1 % (20-octet PSDU) at a ratified SNR | — | — |
| Turnaround | meets LE T_IFS and 802.15.4 turnaround with margin, in hardware | — | — |
| Clock (all sky130_fd_sc_hd corners) | 32 MHz | 16 MHz | — |
| Signoff | DRC + LVS clean | — | — |

Error rates are simulated on a stated channel model and are labelled as
simulated.

Maturity ladder: spec ratified → reference receiver meets error-rate targets
in link-level simulation → RTL bit-exact against the reference → turnaround
timing verified → layout DRC/LVS-clean → timing closed across corners →
shuttle seat → measured silicon. **Current position: pre-spec.**

## Repo layout

```
spec/          ratified spec + decision records
rtl/           modems, framing, CRC/whitening, timers, host interface
verification/  cocotb testbenches; RTL vs. reference bit-exactness
sim/           link-level reference model, channel model, BER/PER sweeps
layout/        GDS + DRC/LVS reports (klayout-tools driven)
measurements/  silicon characterization (empty until tape-out)
```

## License

Apache License 2.0 — see [LICENSE](LICENSE).
