# 0003 — LE demodulator architecture: coherent vs. non-coherent

- Status: accepted as a **provisional default**; supersede criteria below
- Date: 2026-10-17
- Parent: #2; issue #6

## Context

LE 1M GFSK can be demodulated non-coherently (phase-difference / discriminator
based, tolerant of carrier phase, cheap) or coherently (carrier and phase
recovery, needs a phase reference, usually costs area and a more complex
frequency-offset path). The reference model does not exist yet, so **no
error-rate gap between the two has been simulated and none is claimed here.**
The architecture must still be decided now so `sim/` and RTL have a target.

## Decision

- **Provisional default: non-coherent** for LE 1M. 802.15.4 despreading is
  likewise non-coherent (correlation against the chip sequences on a
  phase-difference or magnitude basis), so the two PHYs can share front-end
  frequency-offset handling.
- `sim/` implements the non-coherent receiver first, and, as a comparison, a
  coherent LE receiver, on the same stimulus and channel model (CM-A).

## Decision criteria

A candidate is judged on all three, against the ceilings in
[`../target-spec.md`](../target-spec.md):

1. **Error-rate gap**: Eb/N0 (dB) at BER 1e-3, upper 95 % bound, over the full
   offset/drift/clock range of CM-A.
2. **Area**: synthesized cell area in `sky130_fd_sc_hd` for the demodulator
   alone, at the same clock; the liberty corner is named when the number is
   recorded (the area comparison is made by #9's flow; until then an estimate
   labelled as such).
3. **Frequency-offset tolerance**: the widest offset range over which BER stays
   at or below the target.

## Supersede when

Write a superseding record (naming this one) if either holds in a recorded
`sim/` result on CM-A:

- the non-coherent receiver **cannot meet** the LE 1M BER ceiling anywhere in
  the offset/drift/clock range of the target column (offset ±150 kHz plus
  drift), or only at an Eb/N0 above the fallback ceiling; **or**
- the coherent receiver is better by **≥ 2 dB Eb/N0** at BER 1e-3 **and** its
  demodulator area is no more than **1.25×** the non-coherent one's.

(2 dB and 1.25× are this record's engineering thresholds, not simulated
quantities; changing them is a superseding record.) If the first condition
holds and the second does not, the fallback is to relax nothing: file an issue,
because ratified targets are not relaxed to make results pass.

## Consequences

- RTL architecture work (#9 onward) targets the non-coherent receiver until a
  superseding record exists.
- Open question "coherent vs. non-coherent" is closed by this record; reopening
  requires one of the two conditions above.
