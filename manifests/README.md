# Block manifest and tier-verdict record

This directory holds this block's `klt signoff` input and its committed
output, so the gap to the klayout-tools T1 checklist is read from a tool
rather than from prose.

## Files

- **`sky130-ble-baseband.json`** — the block manifest: `block`,
  `kind: digital`, and an `evidence` map. It cites evidence only for item 10
  (the hygiene attestation); no design artifact exists for the other items yet.
- **`design-evidence-tiers.md`** — the T1-T4 checklist the grader parses.
  Vendored **byte-identical** from
  [`2AMLogic/klayout-tools@e88f211`](https://github.com/2AMLogic/klayout-tools/blob/e88f211fa485959b382e2596c86648ce4e66ea78/docs/design-evidence-tiers.md)
  `docs/design-evidence-tiers.md` (2026-10-17; upstream is MIT-licensed,
  and this repo's license does not relicense the vendored copy). When
  upstream moves, re-vendor the doc and regenerate the record in the same
  PR.
- **`sky130-ble-baseband.signoff.json`** — the **verdict of record**:
  committed output of the command below. Never hand-edit it. Today all 11
  T1 items read `unmet` / `no_evidence` except item 10 (`met`); the three
  rows beyond T1 read `unmet` / `tier_not_supported`.
- **`hygiene-inventory.json`** — the item-10 attestation inventory: the
  hygiene artifacts (README, license, workflows) and the commands the CI
  workflows run. The two commands marked `local_only` need the full toolchain
  and are run by `--attest`, carried (not re-run) by `--check`.
- **`item10-attestation.json`** — the envelope `klt signoff --attest 10`
  produced from the inventory. The manifest pins the inventory's sha256, so
  editing the inventory without re-attesting turns item 10 stale.

## Pinned tool

`klayout-tools==0.8.0` (the first release with `--attest`, needed for item 10).
CI and the committed record use the same pin.

## Regenerate

```console
uvx --from "klayout-tools==0.8.0" klt signoff \
    --manifest manifests/sky130-ble-baseband.json \
    --tiers-doc manifests/design-evidence-tiers.md \
    --format json > manifests/sky130-ble-baseband.signoff.json
```

The command exits `3` when at least one T1 item is `unmet` (a valid, clean
run) and `0` when every item is `met`. Any change that affects the verdict
— new evidence, a manifest edit, a vendored-doc bump, a version-pin bump —
regenerates and commits the record in the same PR.

To re-attest item 10 after changing the inventory (run `make venv` first so
the `local_only` checks can run), then re-pin the inventory's sha256 in the
manifest and regenerate the record:

```console
uvx --from "klayout-tools==0.8.0" klt signoff --attest 10 \
    --inventory manifests/hygiene-inventory.json \
    -o manifests/item10-attestation.json
```

## Freshness is CI-enforced

`.github/workflows/signoff.yml` re-runs the grader on every push to `main`
and every pull request, accepts exit codes 0 and 3, and fails when the
fresh output differs byte-for-byte from the committed record.
