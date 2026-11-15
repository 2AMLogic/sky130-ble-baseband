# 0010 — `L_tx` starts at the TX-command strobe; the jitter column bounds spread(`L_dig`)

- Status: accepted
- Date: 2026-11-15
- Parent: issue #146. Surfaced during Judge review of PR #144 (closes #122).

## Context

[timing-and-area §3](../timing-and-area.md) split `L_dig` into `L_rx` and `L_tx`
and defined `L_tx` as "that decision cycle to the first `tx_valid` word" — the
end-of-packet decision cycle to the first transmitted word. On both timed paths
that literal interval is the whole programmed turnaround the lower-MAC timer
deliberately spends waiting: LE timed response 4800 clk and 802.15.4 automatic
ACK 6144 clk at 32 MHz ([0006](0006-lower-mac-split.md), "Hardware-resident
deadlines"), against §3's own `L_tx` bounds of 128 clk (LE) and 512 clk
(802.15.4). The literal reading is unsatisfiable by construction on exactly the
paths §3 exists to bound. PR #144 (open, unmerged, at the time of writing)
therefore measures `L_tx` from the TX-command strobe and will record that
reading in `verification/top/latency_record.md`, joining the `L_DIG_CYCLES`
decomposition already in `rtl/top/README.md` — correct behaviour for a bench,
which may not edit the spec. This record is the spec-clarification that
situation owed.

The second ambiguity is quieter: §3's jitter column says only "max − min over
all packets and offsets", without naming which quantity's spread it bounds.

## Evidence: the literal reading contradicts the ratified text three times

Each item below is internal to the ratified file set; none depends on a
measurement or on the quality of this design.

1. **The literal reading makes [frontend-interface §5.2](../frontend-interface.md)
   unsatisfiable on its own terms.** §5.2 requires `T_settle ≤ T_gov − L_dig −
   D_fe − M`; for LE, `T_settle ≤ 135 µs − L_dig − D_fe`. Under the literal
   reading `L_dig` contains the whole last-on-air-bit → first-TX-word interval,
   which on a timed LE response is `T_IFS` = 150 µs — giving
   `T_settle ≤ −15 µs − D_fe`. No front end can meet it, and §5.2's own worked
   illustration (`L_dig` = 10 µs → `T_settle` ≤ 120 µs) would be arithmetically
   impossible.
2. **[0006](0006-lower-mac-split.md)'s deadline table already assigns that
   interval to the MAC timers, not to `L_dig`.** LE `T_IFS`: 150 µs ± 2 µs,
   4800 (± 64) cycles at 32 MHz, measured "end of last bit of received packet …
   to start of first bit (preamble) of the next"; 802.15.4 turnaround: 12
   symbols = 192 µs, 6144 cycles, "end of last symbol of the received frame to
   start of the ACK SHR". Those are precisely the intervals §3's literal `L_tx`
   would bound at 128 and 512 cycles. Two ratified records would bound the same
   interval at 4800 and at ≤ 128.
3. **0006 separates the two quantities and names the command.** Same record,
   above the deadline table: "Deadlines are stated at the air interface (end of
   last received bit to start of first transmitted bit). The digital latency
   inside the block, and the front-end ready budget, are separate: the timer
   fires the TX command early by those amounts (`L_dig` from timing-and-area
   §3 …)." If the timer compensates `L_dig`, then `L_tx` — the quantity between
   the command and the first word — starts at the command strobe by
   construction.

§3's own rationale already spoke of a timer firing a TX command early — a
quantity anchored at a command strobe, not at the decision cycle — so the
requirement rows and the reasoning described two different measurements.

## Decision

### `L_tx` reference point

Old text (timing-and-area §3, `L_tx` bullet):

> `L_tx`: that decision cycle to the first `tx_valid` word of the response
> (preamble/SHR).

New text:

> `L_tx`: the TX-command strobe (`resp_tx_req` for the LE timed response,
> `ack_tx_req` for the 802.15.4 automatic ACK, `cmd_tx_start` for a
> host-triggered transmission) to the first `tx_valid` word of the response
> (preamble/SHR). It does not start at the end-of-packet decision cycle:
> between the two sits the programmed turnaround wait of 0006's deadline
> table, which is the timer's deliberate wait, not latency.

Old text (frontend-interface §5.1, `L_dig` Meaning cell):

> Digital latency: last on-air bit received to the TX decision, plus TX
> decision to the first `tx_valid` word

New text:

> Digital latency: `L_rx` (last on-air bit received to the end-of-packet
> decision) plus `L_tx` (TX command to the first `tx_valid` word); the
> programmed turnaround between them is excluded

Old text (frontend-interface §5.1, prose below the table):

> `L_dig` is the sum of the RX-side detection latency (from the last bit at the
> antenna to the baseband knowing the packet ended) and the TX-side latency
> (from TX decision to the first word on `tx_dev`).

New text: same first clause; the second clause reads "and the TX-side latency
(from the TX command to the first word on `tx_dev`)", followed by a sentence
stating that the programmed turnaround between the two lies outside both, so
`L_dig` is not the wall-clock interval from the last on-air bit to the first
word.

Old text (timing-and-area §3, intro):

> `L_dig` is defined in frontend-interface.md §5.1 as the digital latency from
> the last on-air bit received to the first TX word.

New text:

> `L_dig` is defined in frontend-interface.md §5.1 as the sum of the two
> processing latencies below — `L_rx + L_tx` — excluding the programmed
> turnaround between them ([0010](0010-digital-latency-reference-points.md)).

### The programmed turnaround is excluded from both

Old text: none (the exclusion was implicit).

New text (timing-and-area §3, after the split bullets):

> The programmed turnaround wait (LE `T_IFS`, 802.15.4 `T_TA`; 0006,
> "Hardware-resident deadlines") lies between `L_rx`'s end and `L_tx`'s start
> and is excluded from both. `L_dig = L_rx + L_tx` is therefore the sum of the
> two processing latencies, not the wall-clock interval from the last on-air
> bit received to the first TX word — that interval is the turnaround deadline
> itself (4800 cycles on LE, 6144 on 802.15.4 at 32 MHz), which 0006 bounds
> separately.

Consequence: the sentence "digital latency from the last on-air bit received to
the first TX word" is removed from both ratified files. `L_dig = L_rx + L_tx`
still holds; the wall-clock reading does not.

### The jitter column names its quantity

Old text (timing-and-area §3, column header):

> Jitter (max − min over all packets and offsets) ≤

New text:

> Jitter, spread(`L_dig`) (max − min over all packets and offsets) ≤

Old text (§3 rationale):

> The timer fires the TX command early by `L_tx + T_settle` (0006), which only
> works if latency is **repeatable**: that is the jitter column.

New text:

> The timer fires the TX command early by `L_dig + T_settle` (0006), so the
> placement error it must absorb is the spread of `L_dig` — the total is what
> the timer compensates. That is the jitter column; spread(`L_rx`) and
> spread(`L_tx`) are recorded by the bench as evidence but are not separately
> bounded.

Ratifying the total, and a correction. PR #144 justified enforcing on
spread(`L_dig`) by subadditivity: "`L_dig = L_rx + L_tx` makes spread(`L_dig`)
≤ spread(`L_rx`) + spread(`L_tx`), so the enforced bound is the binding one".
That argument gets the direction backwards: subadditivity bounds the total
*from above* by the sum of the parts, so enforcing each part at the column's
value would permit spread(`L_dig`) up to 2 µs on LE — outside the whole
`T_IFS` tolerance. The sound reason to bound the total directly is that the
total is the amount the timer compensates: 0006 fires the command early by
`L_dig` (plus the settle budget), so its placement error is spread(`L_dig`),
whatever its parts do. §3's 1 µs LE bound sits inside 0006's ± 2 µs `T_IFS`
tolerance with margin, which is coherent only for the total. The enforcement
choice is unchanged; only its justification is corrected here.

## Classification under 0008

This record is written to the **substantive** standard. §3's `L_tx` bullet, the
§3 intro, frontend-interface §5.1's `L_dig` row and prose, and §3's jitter
column each change the **meaning** of quantities that existing requirement rows
bound, and 0008's substantive kind covers "any change to a value **or a
meaning** in an existing requirement". The "editorial" claim in the issue title
rests only on the "changes no number" limb, so this record carries the full
substantive-grade content (old text, new text, evidence, who is affected) and
states its own classification; the 0008 changelog line names it substantive.
**No numeric bound moves**: every value, cycle column and `T_settle` budget is
unchanged, and §1, §2 and §4 of the timing file are untouched.

Under 0008 rule 1, the argument is a **spec misread** — the three ratified-text
contradictions above — and explicitly not "the measured design missed the
bound": no bound is loosened and no result is being excused. PR #144's bench
(open at the time of writing) measures the strobe-referenced `L_tx` and
conforms to the reading ratified here.
Direction of causation: this record is the authority; if the ratified reading
had differed from what #144 enforces, the follow-up would re-align the bench,
never this spec.

## Who is affected

- **The top-level bench** (`verification/top`, `make test-top`): it currently
  measures end of packet (air) → `rx_end` and → first TX word, asserted against
  the wall-clock turnaround deadlines of 0006 (4800/6144 clk) — `L_rx` plus the
  turnaround, not yet the strobe-referenced split. PR #144 (open at the time of
  writing) is what re-anchors it on `L_rx`, `L_tx` and `L_dig` from the strobes
  ratified here and will record the spread in a
  `verification/top/latency_record.md`; this record names what that bench will
  measure.
- **The `L_DIG_CYCLES` parameters** (`rtl/top`, `LE_L_DIG_CYCLES` /
  `OQ_L_DIG_CYCLES`): their decomposition (end of packet → `rx_end`, then
  `rx_end` → first word) is the `L_rx + L_tx` sum excluding the programmed
  turnaround, used as the timer's fire-early amount — the role this reading
  formalises.
- **The front-end datasheet reader**: §5.2's `T_settle ≤ T_gov − L_dig − D_fe − M`
  becomes satisfiable as written. Against a wall-clock `L_dig` containing the
  turnaround, no front end could close the budget on a timed path.

## Alternatives rejected

- **Keep the literal wording and let the bench record carry the reading**: the
  ratified spec and the committed evidence would describe two different
  measurements, and §5.2 would stay unsatisfiable as written.
- **Reword timing-and-area §3 only**: the same sentence lives in
  frontend-interface §5.1; fixing one file moves the inconsistency to the
  other.
- **Bound spread(`L_rx`) and spread(`L_tx`) separately instead**: the parts do
  not compensate the timer, the total does; separate part bounds leave the
  quantity the timer actually absorbs unbounded.
