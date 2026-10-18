# 0004 — One front-end sample interface serves both PHYs

Status: proposed (issue #7, parent #2). Date: 2026-10-17.

## Context

LE 1M and 802.15.4 O-QPSK have different symbol rates (1 Msym/s vs
2 Mchip/s) and channel spacings. The question is whether the interface to
the front end needs per-PHY sample rates or decimation paths.

## Decision

A **single** complex I/Q interface at 8 Msps (4 Msps fallback) serves both
PHYs. Per-PHY channel filtering and decimation happen inside the baseband,
after the interface. The front end only receives a channel index and a
`fe_phy` select that affects the frequency plan, never the sample format.

## Reasoning

- 8 Msps gives 8 samples per LE symbol and 4 per 802.15.4 chip; 4 Msps gives
  4 and 2. Both are integer ratios, so no fractional resampler is needed
  at the interface.
- One interface means one front-end contract and one testbench stimulus
  format for the reference receiver and RTL.
- Putting decimation after the interface keeps it inside the bit-exact
  scope (reference receiver vs RTL).

## Rejected alternatives

- Separate per-PHY sample rates (for example 4 Msps for LE, 8 Msps for
  802.15.4): two front-end contracts, mode-dependent clocking, no gain.
- Front-end-side decimation per PHY: moves filtering out of the bit-exact scope.

## Consequences

- Front end must provide 8 Msps (target) in both modes.
- Anti-alias filtering for the 4 Msps fallback is the front end's job.
