# 0012 — The signoff checklist comes from the pinned tool, not a vendored copy

- Status: accepted
- Date: 2026-11-23
- Parent: issue #126. Operator ruling of 2026-11-23 (attended `/fleet:decide`
  session, round 20261121-r19, q103), made once for the twelve repos that
  asked the same question: **remove the vendored copy of the design-evidence
  tiers document and the `--tiers-doc` override; the pinned klayout-tools
  release alone selects the checklist.**

## Decision

The T1-T4 checklist `klt signoff` grades this block against is the
`docs/design-evidence-tiers.md` bundled inside the pinned
`klayout-tools==0.9.2` wheel
([2AMLogic/klayout-tools@v0.9.2](https://github.com/2AMLogic/klayout-tools/blob/v0.9.2/docs/design-evidence-tiers.md)).
Nothing in this repo duplicates it:

- `manifests/design-evidence-tiers.md` (vendored 2026-10-17 in `4fd61d0`,
  byte-identical to `klayout-tools==0.8.0`'s bundled copy at the time) is
  deleted. No `.UPSTREAM` marker existed beside it.
- Every `--tiers-doc` caller drops the flag: the regenerate command in
  `manifests/README.md` and both uses in `.github/workflows/signoff.yml`
  (the fresh run and the echoed regenerate hint). The workflow's
  error text no longer names a "vendored tier doc".
- `verification/tool_pins.py` no longer excludes the deleted file from its
  pin-literal scan (the exclusion's stated reason — vendored upstream text
  this repo cannot edit — no longer applies to any file).
- The signoff record is regenerated once with the pinned tool and without
  `--tiers-doc`, in the same PR as the deletion.
- The CI step that byte-compares a fresh `klt signoff` run against the
  committed record is kept unchanged in effect: it is what catches a
  checklist change at a pin bump.

This reverses the earlier decision to vendor the document, including where
an issue or record asked for the vendored copy by name.

## Evidence

- **The vendored copy had drifted behind the pin it existed to mirror.** It
  was byte-identical to `klayout-tools==0.8.0`'s bundled doc (1053 lines,
  `sha256:a26b9026…efdc7`) but the pin moved to 0.9.2, whose wheel bundles
  1116 lines (`sha256:d9287ec9…490a`) — 63 lines of checklist the record's
  `--tiers-doc` override was silently not grading against, while the record
  claimed the in-repo path as `source_doc`.
- **The reversal moves no verdict.** The record was regenerated with
  `klayout-tools==0.9.2` without `--tiers-doc` and compared field by field
  against the committed one: every item `status` and `reason`, the tier
  result (`null`), `t1_item_count`/`build_t1_item_count`/`t1_met_count`,
  every citation, and the whole `build` block are identical. Only
  `source_doc` (`manifests/design-evidence-tiers.md` →
  `docs/design-evidence-tiers.md`), `source_doc_content_hash`, and the
  doc-derived item `text`/`notes` fields changed, carrying the 0.8.0 → 0.9.2
  checklist drift the operator ruling anticipated ("where the copy had
  drifted, the item texts may change"). The command still exits `3` (clean
  run, unmet items), as before.

## Who is affected

- **Anyone regenerating the record**: the command in `manifests/README.md`
  no longer passes `--tiers-doc`; there is nothing to re-vendor when
  upstream moves.
- **A klayout-tools pin bump** now changes the checklist implicitly — the
  bundled doc moves with the wheel. The CI fresh-run-vs-committed-record
  byte-compare catches that (and any verdict change) in the bump PR, which
  must regenerate the record in the same commit.
- **`verification/tool_pins.py`** scans one fewer excluded path; its
  negative-control suite drops the corresponding parametrized case. The
  remaining exclusions (generated record, installed tooling, the test's own
  drift fixtures) are unchanged.

## Bounds on this record

1. No `spec/` row, value or meaning changes: this record relocates the
   checklist's provenance, not any requirement the checklist grades. No
   signoff verdict, item attestation or cited evidence changes (verified
   above), so nothing here relaxes or tightens a graded bar.
2. The CI comparison of a fresh run against the committed record is kept
   unchanged in effect — the ruling names it "what catches a checklist
   change at a pin bump".
3. The klayout-tools pin itself is not bumped by this record.

## Rejected

- *Keep vendoring and re-vendor on every pin bump*: the mechanism already
  failed once — the 0.8.0 → 0.9.2 bump updated the pin and not the copy —
  and a duplicate that can silently lag the pin it mirrors is worse than no
  duplicate.
- *Record the graded doc's digest in the signoff record without removing
  the vendored copy*: the record already carries
  `source_doc_content_hash`; the gap was that the override pointed it at a
  stale in-repo file. If `klt signoff` ever needs a stronger in-record
  checklist identity, that is a klayout-tools request, filed generically
  per this repo's friction protocol — not a reason to keep a copy here.
