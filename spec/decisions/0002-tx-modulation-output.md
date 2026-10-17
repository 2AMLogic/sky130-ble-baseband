# 0002: TX modulation output is a signed frequency-deviation word

Status: proposed (issue #7, parent #2). Date: 2026-10-17.

## Decision

The baseband emits an 8-bit signed frequency-deviation word at 8 Msps
(4 Msps fallback), LSB 7.8125 kHz, with Gaussian shaping applied in the
baseband. Both LE 1M (+/-32 LSB) and 802.15.4 O-QPSK treated as half-sine
MSK (+/-64 LSB) use it.

## Reasoning

Both target PHYs are constant-envelope, so frequency alone carries the
information. The word needs no DAC amplitude accuracy, matches a
direct-VCO or fractional-N front end, and is the same format for both PHYs.
The LSB weight makes both nominal deviations exact integers.

## Rejected alternatives

- I/Q samples: needs a DAC and an up-converter with image rejection; wastes
  amplitude resolution on a constant-envelope signal.
- Two-point modulation command (separate high/low-frequency paths): couples
  the interface to one front-end architecture.
- Bit-level (unshaped) output: moves Gaussian filtering to the front end,
  out of the bit-exact scope.

## Open check

The O-QPSK half-sine to MSK equivalence, including the chip-to-sign mapping,
is an engineering assumption. The reference model (sibling A / sim) must
confirm it before ratification; this record does not claim it.
