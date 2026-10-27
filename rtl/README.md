# rtl

Synthesizable RTL. `rtl/baseband.f` is the one file list of the integrated
design (lint, synthesis and the integration bench read it); `rtl/top/` is the top
level that ties the blocks below together, see [`rtl/top/README.md`](top/README.md).
See `verification/README.md` for the flow.

## host

`rtl/host/` is the host interface (APB4 registers, TX/RX FIFOs, RX descriptor
FIFO, interrupts, timestamps). Register map: `rtl/host/REGMAP.md`; tests:
`make host-test`, `make host-test-negative`, `make host-lint`.

## le1m_tx

`rtl/le1m_tx/` is the LE 1M transmit path: `le1m_tx` (top) composes
`le1m_frame` (preamble, access address, PDU octet pull, CRC and whitening
sequencing) with `le1m_whiten`, `le1m_crc24` and `le1m_gauss` (33-tap
Gaussian shaper, taps and rounding copied from `sim/model/le1m_tx.py`). It
emits `tx_dev` / `tx_valid` / `tx_active` on the 4-clock sample grid of
`spec/frontend-interface.md` section 3.2 and is bit-exact with the reference
model, including the 32 trailing drain words. The input side is a local
ready/valid PDU-octet pull; the host FIFO path, T_IFS timer and baseband top
are separate blocks. No timing or area claim is made here.

## le1m_rx

`rtl/le1m_rx/` is the LE 1M receive path, bit-exact with `sim/model/le1m_rx.py`
(decisions [0003](../spec/decisions/0003-demod-architecture.md) and
[0007](../spec/decisions/0007-bit-exactness.md)): one module per model stage
(`_fir`, `_disc`, `_cordic`, `_integ`, `_sync`, `_pkt`) and the top `le1m_rx`.
It is strobe driven (`rx_valid`, no minimum spacing, no back-pressure) and
exposes the model's trace taps on `ev_*` for the replay.

- Optional de-whitener (`dewhiten_en`, `chan`): off in the model, so off in the
  bit-exact replay; tested separately against the TX model's whitening.
- `rx_flush` marks the end of a capture (pulse at least 16 clk after the last
  `rx_valid`); it makes the RTL finish a truncated packet the way the model does.
- AGC is not implemented: `agc_gain` is mid-scale, `agc_gain_we` never fires,
  `agc_hold` follows sync to end of packet. `rssi` is `rssi_lin` (the model's
  linear value) saturated to 8 bits until the dB mapping is specified.
- Written for bit-exactness, not area: the 313-deep sample history and the
  320-deep RSSI window are plain registers/memory. Synthesis and timing
  closure are a separate item.

## oqpsk

`rtl/oqpsk/` is the IEEE 802.15.4 2.4 GHz O-QPSK baseband, bit-exact with
`sim/model/oqpsk_tx.py` and `sim/model/oqpsk_rx.py` (decisions
[0003](../spec/decisions/0003-demod-architecture.md),
[0005](../spec/decisions/0005-tx-modulation-output.md) and
[0007](../spec/decisions/0007-bit-exactness.md)). Both tops run at the 8 Msps /
4 samples-per-chip operating point of `spec/frontend-interface.md`; the 4 Msps
fallback is not modelled and not supported.

**TX (`oqpsk_tx`)**: one module. A payload of 0..125 octets is read through
`psdu_idx`/`psdu_data` (asynchronous-read buffer), the block appends the FCS and
emits SHR, PHR and PSDU as `tx_dev` words in `{-64, 0, +64}`, four per chip
interval, `4*(chips+1)` in all. `tx_tick` is the sample-grid enable from the
wrapper (one word per tick; nominally every 4 clk at 32 MHz, +/-1 clk jitter
allowed), so there is no divider and it works unchanged at 16 MHz. `tx_active`
rises with the first word and is low again at tick `len(words)+1`; that is the
model's reading of the interface (`sim/model/README.md`). A start while busy or
with a payload over 125 octets pulses `tx_reject` and sends nothing.

**RX (`oqpsk_rx`)**: one module per model stage, then the top.

| Module | Model stage |
|---|---|
| `oqpsk_rx_fir` | 5-tap FIR `1 4 6 4 1`, `(acc+8)>>4`, saturate to signed 9; also the RSSI magnitude |
| `le1m_rx_disc`, `le1m_rx_cordic` | discriminator products and CORDIC angle, **reused unchanged** from `rtl/le1m_rx/` (the model shares `le1m_rx.discriminate`) |
| `oqpsk_rx_integ` | 4-sample chip integrator, signed 18 |
| `oqpsk_rx_corr` | 16 correlators over 31 chip-spaced taps (signed 23), `mag` (unsigned 23), argmax (lowest index on ties), accept rule, the 320-sample RSSI window |
| `oqpsk_rx_sync` | preamble run of 4 symbol-0 matches, best of the next 4 indices, SFD (symbols 7 then 10, at most 16 further zeros) |
| `oqpsk_rx_pkt` | symbol decisions, +/-1 timing step, PHR length, octets, FCS, trace taps |

- Strobe driven: `rx_valid` with no minimum spacing and no back-pressure (tested
  at one strobe per clk as well as the nominal grid with jitter). Results are
  tied to the sample index, not to the clock.
- `rx_flush` marks the end of a capture (pulse at least 24 clk after the last
  `rx_valid`); a truncated packet then finishes the way the model does: octets
  received so far, no `crc`.
- **One packet per capture**, as the model: after the SFD the engine decodes one
  packet, then stays quiet until `rst_n`. Re-arming for back-to-back packets is
  not done here.
- Trace taps on `ev_*`: `ev_kind` 2 sync, 3 tbound, 5 crc, 6 rssi, 7 octet. No
  `cfo` tap (the model makes no offset estimate) and no `gain` tap (stimulus echo,
  as `le1m_rx`).
- AGC is not implemented: `agc_gain` is mid-scale, `agc_gain_we` never fires,
  `agc_hold` follows sync to end of packet. `rssi` is `rssi_lin` (the model's
  linear value) saturated to 8 bits until the dB mapping is specified, as for LE.
- FCS: the CRC runs over every PSDU octet including the FCS and the residue is
  tested for zero, which is equivalent to the model's compare of the computed FCS
  with the last two octets.
- Written for bit-exactness, not area: the 16 x 31 correlator sums are one
  combinational expression per strobe over a 120-deep `g` history, and the
  320-deep RSSI window and the 385-deep preamble history are plain registers.
  Area, Fmax and synthesis are items 1f/5.
- **Not claimed**: nothing about error rate, offset or drift tolerance (the model
  claims none either; `sim/model/README.md` "Not established"), the 4 Msps
  fallback, auto-ACK or address filtering (`rtl/mac/`), the host interface.
  Clause numbers of the IEEE 802.15.4 PHY remain unverified, as in the model.
