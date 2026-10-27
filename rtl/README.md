# rtl

Synthesizable RTL. `rtl/smoke/` holds a **placeholder** 8-bit LFSR
(`lfsr8.v`) that exists only to exercise the verification, lint and synthesis
flow; it is not part of the baseband and goes away once real RTL uses the same
flow. See `verification/README.md` for the flow.

`rtl/le1m_tx/` is the LE 1M transmit path: `le1m_tx` (top) composes
`le1m_frame` (preamble, access address, PDU octet pull, CRC and whitening
sequencing) with `le1m_whiten`, `le1m_crc24` and `le1m_gauss` (33-tap
Gaussian shaper, taps and rounding copied from `sim/model/le1m_tx.py`). It
emits `tx_dev` / `tx_valid` / `tx_active` on the 4-clock sample grid of
`spec/frontend-interface.md` section 3.2 and is bit-exact with the reference
model, including the 32 trailing drain words. The input side is a local
ready/valid PDU-octet pull; the host FIFO path, T_IFS timer and baseband top
are separate blocks. No timing or area claim is made here.
