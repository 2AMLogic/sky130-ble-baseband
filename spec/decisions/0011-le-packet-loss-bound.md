# 0011 — A ratified packet-loss bound on the LE 1M BER row

- Status: accepted
- Date: 2026-11-18
- Parent: issue #156. Precondition #133 (decision
  [0009](0009-le-ber-undelivered-packet-accounting.md)) is merged — checked on
  `main` at `1c07cdc`. Surfaced during Judge review of PR #151.

## Decision

After [0009](0009-le-ber-undelivered-packet-accounting.md), the ratified LE 1M
pass/fail surface is one bound on bit-decision quality **among delivered
bits**. A packet the receiver syncs but delivers with the wrong length is
scored over its comparable prefix only and counted undelivered; it contributes
almost no bit errors, so a receiver that truncates a few percent of packets by
misreading length fields meets the ratified BER row while losing those
packets, and no ratified row fails it. This record closes that gap as a
**substantive** amendment: the LE 1M row passes only if a BER bound and a
packet-loss bound both hold.

### Old text

`spec/target-spec.md` "Demodulator performance", the LE 1M row — Target /
Fallback / Stretch:

> BER ≤ 1e-3 at Eb/N0 ≤ 16 dB (**provisional ceiling**, see note 1)
> BER ≤ 1e-3 at Eb/N0 ≤ 18 dB
> BER ≤ 1e-3 at Eb/N0 ≤ 14 dB

`spec/target-spec.md` "Statistics", the pass-rule bullet:

> Report a 95 % Clopper–Pearson interval per point; a row passes only if the
> **upper** interval bound meets the target.

### New text

The LE 1M row — Target / Fallback / Stretch:

> BER ≤ 1e-3 and packet loss ≤ 1e-2 at Eb/N0 ≤ 16 dB (**provisional
> ceilings**, see note 1)
> BER ≤ 1e-3 and packet loss ≤ 1e-2 at Eb/N0 ≤ 18 dB
> BER ≤ 1e-3 and packet loss ≤ 1e-2 at Eb/N0 ≤ 14 dB

The pass-rule bullet:

> Report a 95 % Clopper–Pearson interval per point; a row passes only if the
> **upper** interval bound meets the target. For the LE 1M row, the row passes
> only if that bound **and** the worst graded packet loss meets its ceiling —
> both bounds must hold for the row to pass ([0011](0011-le-packet-loss-bound.md)).

A row's graded packet loss is the worst `packet_loss` — the fraction of
packets not delivered intact, sync miss or wrong-length delivery, as 0009
defines it — among the row's graded points (the ratified Eb/N0, in-spec
points). Note 1 stays generic and now covers three ceilings, each one a later
record may tighten or confirm, never relax.

### What is bound

The bound is on `packet_loss` **as emitted** — `(sync_misses +
undelivered_packets) / packets` — not on `undelivered_packets / packets`
alone:

- It is the quantity 0009's Statistics bullet already reports beside a BER
  row; the conjunction gives that reported figure its ratified number instead
  of defining a second, narrower quantity beside it.
- It is conservative: `packet_loss ≥ undelivered_packets / packets` always, so
  the ceiling also bounds the class 0009 left ungraded, with margin.
- The sync-miss half is not a new constraint: 0009 charges a missed packet as
  every PDU+CRC bit wrong, so the BER upper bound already limits the sync-miss
  rate at any graded point that meets 1e-3. Binding `packet_loss` double-
  covers that half; it lets no class escape that the BER row would have held.
- In the committed record the two quantities coincide (`sync_misses == 0` at
  every graded point), so the choice moves no recorded verdict; in general
  they differ, and this record says which one it binds so the harness does not
  decide silently.

### Why substantive, not additive

The pass condition of an existing ratified requirement changes meaning and
tightens: a row that previously passed on the BER bound alone can now fail on
loss. That is the substantive row of the
[0008](0008-ratification-and-amendment.md) amendment table, so this record
states the old text, the new text, the evidence and who is affected.

### The ceiling

**1e-2**, matching the numeric value of the ratified 802.15.4 PER row
(PER < 1 %): the same delivery-failure bar this spec already set for the other
PHY, at packet granularity. It is about 8× above the worst graded loss in the
committed corrected-accounting record (1.24e-03, `le1m_drift`), so today's
evidence passes with room and the number is not set at measured performance —
a bound at 1.3e-03 would be a bar the current sweep cannot fail, which is not
a ceiling. Per target-spec Note 1 and
[0008](0008-ratification-and-amendment.md) open item 1 it is **provisional**:
a later record may tighten or confirm it from simulation, never loosen it.

## Evidence

- **The gap, reproduced.** On the pre-0009 harness one flipped on-air length
  bit at Eb/N0 = ∞ scored `errors = 257` of 336 PDU+CRC bits, because the
  un-demodulated remainder was charged (issue #156, reproducing the 0009
  fingerprint). Post-0009 the same packet scores `errors = 1` and is counted
  in `undelivered_packets`: the loss moved out of the graded number and into a
  reported one, and the reported one had no pass/fail bound.
- **Committed corrected-accounting record**
  `sim/results/2026-11-15-8bdc8843f6f8/` (append-only, untouched), graded
  points at 16 dB: worst `packet_loss` 1.163e-03 (`le1m_cfo`, 39 undelivered
  of 57 824 packets, 0 sync misses), 1.238e-03 (`le1m_drift`, 38 of 48 723),
  6.496e-04 (`le1m_uniform`, 6 of 9 237), 0 (`le1m_clock`, 0 of 5 188). All
  four rows pass the new rule — the amendment does not retroactively fail
  recorded evidence.
- **Loss is not negligible below the ratified Eb/N0.** `le1m_drift` carries
  `packet_loss` 6.17e-02 at 12 dB (5 undelivered of 81 packets). That point is
  not graded — it is below the ratified Eb/N0 and `row_summary()`'s filter
  excludes it — and that filter is under test so it stays that way.
- **The harness already had the aggregate.** `sim/sweep/ber_sweep.py`'s
  `row_summary()` computed `worst_packet_loss` per graded row beside
  `worst_cp_upper`; the change is the named constant
  `TARGET_PACKET_LOSS = 1e-2` and a conjunction: the per-row report gains
  `target_packet_loss`, `packet_loss_meets_target` and `row_passes`, and the
  printed summary line reports the loss verdict beside the BER one, still
  "reported, not asserted". No grid, seed, stop rule or scoring changes; no
  new measurement.

## Who is affected

- **Consumers of ratified LE row verdicts**: the LE 1M row is now a
  two-condition row. A verdict that reports the row as passing means both
  bounds held; a row can now fail on loss while meeting 1e-3 BER, and that
  outcome is recorded, not relaxed.
- **The sweep harness** (`sim/sweep/ber_sweep.py`): the row verdict and the
  per-row report change as above. Points, seeds and every per-point field are
  unchanged, so committed records stay byte-identical and re-merge to the same
  points; only recomputed row summaries gain keys.
- **Recorded evidence**: none is edited (0008 rule 4). The committed
  corrected-accounting record passes the new rule as committed.
- **The receiver** (`sim/model/le1m_rx.py`) and every RTL block: unaffected.
  This record grades delivery behaviour; it does not change it. The length-
  field fragility itself remains the receiver finding tracked by #133.

## Bounds on this record

1. Decision [0009](0009-le-ber-undelivered-packet-accounting.md) is not
   edited; its accounting stands as merged.
2. The BER ceiling (1e-3), the ratified Eb/N0 (16 dB), the fallback and
   stretch Eb/N0 (18 / 14 dB) and every 802.15.4 row are unchanged.
3. The 1e-2 loss ceiling is provisional under target-spec Note 1 and
   [0008](0008-ratification-and-amendment.md) open item 1: a later record may
   tighten or confirm it from simulation, never loosen it.
4. The CM-B optional-impairment rows stay informational by ratified choice; no
   loss bound is added there.

## Rejected

- *A separate ratified LE packet-loss / PER row* (the issue's option 1): BER
  here is a rate conditional on delivery — its denominator is delivered bits —
  so "BER row passed, loss row failed" invites averaging two verdicts that
  describe one link. The symmetry with 802.15.4 is superficial: there PER is
  the graded quantity and there is no BER row to pair it with.
- *Loss stays informational for LE* (option 3): leaves the hole open by
  choice, against this repo's premise that the graded quantity is the one that
  matters to a link.
- *Binding `undelivered_packets / packets` alone*: narrower than the reported
  quantity and it saves nothing — the sync-miss half is already bounded by the
  BER row — while needing a second aggregate beside `worst_packet_loss`.
  Binding the figure the report already carries keeps one loss number in the
  file self-describing.
- *Setting the ceiling at measured performance* (≈ 1.3e-03): a bar the current
  sweep cannot fail; not a ceiling.
