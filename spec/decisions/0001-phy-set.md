# 0001 — PHY set

- Status: ratified in revision 1, [0008](0008-ratification-and-amendment.md)
- Date: 2026-10-17
- Parent: #2; issue #6

## Context

The block must close timing and area on sky130 standard cells with no RF
front end in the repo. Several PHYs exist; supporting all of them up front
would let the widest one set datapath width, clocking and interface.

## Decision

- **Target**: LE 1M (GFSK, 1 Msym/s) and 802.15.4 2.4 GHz O-QPSK (2 Mchip/s).
- **Fallback**: LE 1M alone, if the 802.15.4 path does not close.
- **Stretch**: LE 2M, then LE coded PHY, only after the target closes and only
  by a separate record.
- Stretch PHYs must not drive architecture: no datapath width, clock rate,
  interface field or register is justified by LE 2M or coded PHY while the
  target is open. Where a choice is free, prefer the one that does not
  foreclose them.

## Consequences

- RX input of 8 Msps (fallback 4 Msps) is sized for the target PHYs; LE 2M would
  need a revisit of the rate and is not budgeted here.
- `sim/` implements LE 1M and 802.15.4 first.

## Supersede when

A ratified requirement (via #9) names LE 2M or coded PHY as target, or the
802.15.4 path is dropped to fallback after a `sim/` or timing result shows it
cannot close; either needs a new record that references this one.
