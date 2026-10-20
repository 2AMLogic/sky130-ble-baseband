# 0002 — Channel model for error-rate claims

- Status: ratified in revision 1, [0008](0008-ratification-and-amendment.md)
- Date: 2026-10-17
- Parent: #2; issue #6

## Context

A modem is right when its error rate is right under a *stated* channel. An
error-rate number with no channel is not a claim about this block. The model must
be precise enough for `sim/` to implement without interpretation and stable
enough that RTL bit-exactness (#9) can share stimulus.

## Decision

The normative model is the "Channel model" section of
[`../target-spec.md`](../target-spec.md).

- **Baseline (CM-A)** is in every ratified sweep: AWGN, per-packet carrier
  offset, in-packet carrier drift, relative sample-clock offset, random timing
  and carrier phase, and input quantization. Offset, drift and clock tolerance
  are the dominant stressors for a low-symbol-rate digital modem, and each is
  checkable from the parameter table.
- **Optional impairments (CM-B)** — multipath, phase noise, interferers — are
  **not** in the ratified pass/fail. They are simulated one at a time and
  reported as penalties against CM-A.
- Noise is defined in a stated bandwidth (Eb/N0 for LE, SNR in 2 MHz for 802.15.4)
  and generated full-band so the receiver's own filtering is charged to the
  receiver.
- Seeds are deterministic and recorded; stop rule is ≥ 100 errors with a 95 %
  Clopper–Pearson interval; a row passes on the upper bound.
- Every error-rate row states that it is simulated and names CM-A or CM-B.

## Why multipath and phase noise stay out of pass/fail

- Multipath at these symbol rates over the short ranges of the intended use is
  a link-budget matter dominated by the front end and antenna, neither of which
  is in this repo; a pass/fail threshold would be set without a defensible
  basis.
- Phase noise is a synthesizer property; this repo does not design the
  synthesizer. Its *effect* on the digital demodulator is visible through
  carrier drift and offset, which are in CM-A.
- Both stay as reported penalties so the sensitivity is known and a later record
  can promote one to pass/fail with evidence.

## Alternatives considered

- *AWGN only*: rejected; it hides exactly the offset/drift/timing failures that
  decide whether a digital modem works.
- *Multipath in the ratified sweep*: rejected for now (above); revisit if the
  informational penalty turns out large.

## Supersede when

A `sim/` CM-B result shows an impairment penalty large enough that leaving it out
of pass/fail would mislead; or the front-end tables (#7) fix an impairment this
model does not carry. A new record must say which parameters change and
re-run affected rows.
