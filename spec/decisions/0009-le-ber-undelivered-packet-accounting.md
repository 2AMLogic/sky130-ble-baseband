# 0009 — LE BER accounting for packets the receiver does not deliver in full

- Status: accepted
- Date: 2026-11-15
- Parent: issue #133. No preconditions; the change is confined to `sim/sweep/ber_sweep.py` and the Statistics wording.

## Decision

`spec/target-spec.md` "Statistics" ratified (revision 1, [0008](0008-ratification-and-amendment.md)):

> Each point runs until ≥ 100 errors (**bit errors for LE**, packet errors for
> 802.15.4) or a stated packet cap; points that hit the cap are reported as
> upper bounds, not as measurements.

and said nothing about how a packet the receiver fails to deliver in full
contributes to the LE bit-error count. The sweep harness filled that silence
with an unreviewed convention: `ber_sweep.py` charged every bit the receiver
did not return as a wrong bit decision. This record defines the convention in
the spec, as a **substantive** amendment. The Statistics section gains one
bullet (the existing bullets are unchanged):

> LE bit errors are wrong decisions among the bits the receiver actually
> returned. A packet delivered with the wrong length (its length field read
> corrupted, or its demodulation exhausted the record) is counted in an
> undelivered-packet counter of its own and scored over the comparable bits it
> returned; it is never charged for bits it did not demodulate. The bit-error
> denominator is delivered bits, and the fraction of packets not delivered
> intact (sync miss or wrong-length delivery) is reported alongside as the loss
> figure that qualifies a BER row. A sync-missed packet counts as every PDU+CRC
> bit in error.

### Why substantive, not additive

The ratified requirement's *value* does not change and no Target / Fallback /
Stretch column moves — but the *meaning* of the ratified quantity changes: a
recorded "LE BER" number was a mixture of a bit-error rate and a packet-loss
rate, and it is now a bit-error rate over delivered bits with the loss rate
reported beside it. Pinning down what an existing ratified requirement counts
is a change of meaning, so the substantive row of the 0008 amendment table
applies.

## Evidence

The committed full-sweep record
`sim/results/2026-11-14-88245d69b74d/` (append-only, untouched) shows the
fingerprint. At 16 dB, `le1m_cfo`, 0 Hz: `errors: 257, bits: 27552, packets:
82, crc_failures: 1` against neighbours at 1 439–5 856 packets. The receiver
derives its output length from the received length field
(`sim/model/le1m_rx.py`, `want = 16 + 8·length + 24`); one flipped bit there
reads 37 as 5, so the receiver returns 80 of 336 bits and the old harness
charged the 256-bit remainder as errors. Reproduced end to end on a noiseless
channel (Eb/N0 = ∞, no offset, no clock error) by flipping one on-air length
bit: **errors = 257** — bit-exact to the committed point. The charge for one
flip depended only on which bit was hit (1, 9, 33, 257 in the reproduction),
which is the bimodal errors-per-failing-packet distribution in the record.

Ruled out by the record's own counters: not the sync correlator
(`sync_misses == 0` at every anomalous point) and not timing recovery
(`timing_steps`/packet indistinguishable across offsets). The receiver's
*packet* error rate at 16 dB is flat (1.08e-02–1.45e-02) across all seven
offsets while the reported BER spanned 175x; the zero-offset point was measured
healthy in the same sweep's `le1m_clock` row (BER 2.49e-05 at 16 dB, fully
ideal channel). The 0 Hz anomaly tracked the accounting, not the offset.

**Second error path, identified.** The 18 dB anomalous packets (-150 kHz:
175 errors; 0 Hz: 164; replay totals 176 / 165 match the committed points) are
*not* the truncation path: `len(got) = 443 > 336` in both, the length field
read long from corrupted header bits (176, 181), the demodulation exhausted the
record, and ~52 % of the comparable prefix mismatched from bit 4 / bit 12 on —
a whole-packet demodulation derangement, not un-demodulated bits. Under this
record's convention those charges stand as they should: they are wrong
decisions among bits the receiver returned. The old truncation charge
(`len(ref) − m`) never fires on them; it fired only on short reads.

`sim/sweep/per_sweep.py` (802.15.4 PER) charges `errors += 1` per failed packet
and computes Clopper–Pearson over packets — packet-granular on both sides. It
does not share this defect and is unchanged.

## Who is affected

- **Every consumer of a committed LE BER number**: the statistic now measures
  the ratified quantity ("bit errors for LE") instead of a BER/PLR mixture.
  `undelivered_packets` and `packet_loss` accompany each point so nothing is
  hidden.
- **The sweep harness** (`sim/sweep/ber_sweep.py`): the scoring changes; the
  grid, seeds, stop rule, caps and negative control do not, so point indices —
  and therefore seeds — are unchanged.
- **The RTL bit-exactness suite**: unaffected. `sim/model/le1m_rx.py` is not
  modified by this record; the receiver's length-field behaviour is correct and
  spec-shaped (it must trust the received length field).

## Bounds on this record

1. No Target / Fallback / Stretch value changes: **BER ≤ 1e-3 at Eb/N0 ≤ 16 dB
   stays the ratified target**, as do the fallback, the stretch and every other
   row.
2. Per [0008](0008-ratification-and-amendment.md) rule 1, an argument about the
   measurement does not excuse a miss: the sweep is re-run under the corrected
   accounting as a new append-only record, and any row that still misses 1e-3
   is recorded as a miss.
3. The committed record `2026-11-14-88245d69b74d` stays byte-identical
   (append-only, rule 4); it is superseded for LE BER readings by the new
   record, and its numbers are not restated or edited.

## Rejected

- *Keep charging lost bits, compute Clopper–Pearson at packet granularity*:
  retains a metric that is neither a BER nor a PER, and the ratified row says
  "bit errors".
- *Charge a fixed `len(ref)` for any undelivered packet* (the sync-miss
  convention): makes BER scale with packet length rather than with bit-decision
  quality, and still invalidates the interval at the affected points.
- *Widen the stop rule instead* (more errors per point): does not fix the
  invalid interval; a length-field flip stays worth 256 charges.
- *Change the receiver so a corrupt length cannot shorten its output*: the
  receiver is correct; the defect was in how the harness scored it.
