# rtl

Synthesizable RTL. `rtl/smoke/` holds a **placeholder** 8-bit LFSR
(`lfsr8.v`) that exists only to exercise the verification, lint and synthesis
flow; it is not part of the baseband and goes away once real RTL uses the same
flow. See `verification/README.md` for the flow.

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
