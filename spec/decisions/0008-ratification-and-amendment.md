# 0008 — Ratification, scope of the ratified spec, and the amendment rule

- Status: accepted
- Date: 2026-10-18
- Parent: #2; issue #9. Preconditions #6, #7 and #8 are merged (checked on `main` at `fa52ba7`).

## Decision

The spec is ratified as **revision 1** with the scope and the open items below.
Ratification freezes requirements; it does not turn a placeholder into a
verified fact, and this record says which is which.

### Ratified (frozen by this record)

- `spec/target-spec.md`: every row's target, fallback and stretch, the channel model (CM-A / CM-B), seeds policy and statistics rule.
- `spec/frontend-interface.md`: signal tables, rates, widths, turnaround budget formulae.
- `spec/timing-and-area.md`: corner set, clock targets, `L_dig`, area budget.
- Decision records 0001 to 0008.

### Not yet frozen

- `spec/host-interface.md` is **excluded** until issue #15 (a wording-only
  correction of the interrupt-status and error-flag text) merges. Ratification
  freezes a file, and the file is known to need that edit. When #15 merges, its
  PR adds a changelog line below and the file becomes ratified without a
  decision record, because #15 changes wording and no requirement.

### Open items carried into revision 1 (none is a relaxation)

1. **Error-rate ceilings are provisional.** The LE BER and 802.15.4 PER ceilings
   (target-spec Note 1) were to be replaced by values justified by a `sim/`
   result; no `sim/` exists. They are ratified **as ceilings**: a later record
   may tighten or confirm them from simulation, never loosen them.
2. **Every governing-specification citation is `unverified`** (written from
   memory, in this file set and in 0006). Ratification does not verify them.
   Checking a citation and correcting a section number or marking it verified is
   an editorial amendment (below); it cannot change a requirement value.
3. **Liberty corner list is unverified against the pin** until #3 pins the PDK
   (timing-and-area §1). The binding corner is a priori until an STA report
   exists.
4. **LE timed response, SN/NESN** (0006, R1): whether hardware patches the
   preloaded header is undecided. Either outcome is additive to the ratified
   requirements, so it is not a blocker; it needs its own decision record before
   the LE response RTL is written.
5. **Area figures are estimates** and stay so until Yosys has produced a
   number (timing-and-area §4).

## Amendment rule

Changes to ratified files are one of three kinds.

| Kind | Examples | Needs |
|---|---|---|
| **Editorial** | a citation checked and corrected or marked verified; a typo; a link; the binding corner replaced by the corner an STA report shows; a corner list matched to the PDK pin | a line in the changelog below, in the PR that makes it. The change must not alter any number in a Target / Fallback / Stretch column or any requirement |
| **Additive** | a new row, tap, corner or register that adds a requirement without weakening one | a decision record (next number in the single sequence) and a changelog line |
| **Substantive** | any change to a value or a meaning in an existing requirement, including tightening one | a decision record that states the old text, the new text, the evidence, and who is affected, and a changelog line |

Rules that apply to all kinds:

1. **Agents never relax a ratified row to make a result pass.** A miss is
   recorded as a miss, with its evidence, and the response is a new decision
   record that is argued on the evidence about the design, not on the result.
   A record that loosens a row must state what changed in the world (a spec
   misread, a physical limit shown by simulation of the channel), not merely
   that the block missed.
2. A row's fallback column being met instead of its target is a recorded
   outcome, not an amendment.
3. Decision records are numbered in one sequence; `spec/README.md` is the only
   index. A superseded record keeps its file and gets a `Superseded by` line.
4. Recorded results (simulation, STA, bit-exactness runs) are append-only
   evidence; they are never edited, only superseded by later entries.
5. No wording anywhere states or implies qualification, certification or
   compliance with either governing specification
   ([root CLAUDE.md](../../CLAUDE.md)).

## Changelog

Newest last. One line per amendment: date, kind, files, issue/PR.

- 2026-10-18 — revision 1 ratified (this record; issue #9). `host-interface.md` held pending #15.

## Rejected

- *Ratifying only after the reference receiver exists*: the point of a ratified
  spec is that the receiver is built to it; the provisional-ceiling rule gives
  the receiver a fixed bar without waiting.
- *Holding all ratification for #15*: it would leave the other
  ratified files floating for a wording edit.
