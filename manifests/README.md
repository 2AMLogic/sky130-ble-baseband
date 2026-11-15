# Block manifest and tier-verdict record

This directory holds this block's `klt signoff` input and its committed
output, so the gap to the klayout-tools T1 checklist is read from a tool
rather than from prose.

## Files

- **`sky130-ble-baseband.json`** — the block manifest: `block`,
  `kind: digital`, and an `evidence` map. It cites evidence for item 9 (the
  testbench attestation) and item 10 (the hygiene attestation); no design
  artifact exists for the other items yet.
- **`design-evidence-tiers.md`** — the T1-T4 checklist the grader parses.
  Vendored **byte-identical** from
  [`2AMLogic/klayout-tools@e88f211`](https://github.com/2AMLogic/klayout-tools/blob/e88f211fa485959b382e2596c86648ce4e66ea78/docs/design-evidence-tiers.md)
  `docs/design-evidence-tiers.md` (2026-10-17; upstream is MIT-licensed,
  and this repo's license does not relicense the vendored copy). When
  upstream moves, re-vendor the doc and regenerate the record in the same
  PR.
- **`sky130-ble-baseband.signoff.json`** — the **verdict of record**:
  committed output of the command below. Never hand-edit it. Today all 11
  T1 items read `unmet` / `no_evidence` except items 9 and 10 (`met`); the
  three rows beyond T1 read `unmet` / `tier_not_supported`.
- **`testbench-inventory.json`** — the item-9 attestation inventory: every
  committed cocotb bench under `verification/`, the one `cold_start`
  invocation that runs them all from a clean checkout, and the `pins` block
  (PDK revision and tool versions) item 9 requires. The cold start is
  marked `local_only` — it needs Icarus, Verilator, Yosys and the cocotb
  venv, so `--attest` runs it and `--check` carries its committed outcome.
  It is the bench targets only: `lint` belongs to item 10, and `synth`
  cannot complete yet (`flow/synth/README.md`), so neither is in it.
- **`item9-attestation.json`** — the envelope `klt signoff --attest 9`
  produced from that inventory. Generated, committed, never hand-edited:
  `status` is derived from the checks `--attest` actually ran (one
  file-presence check per bench, the cold start, and the two pin checks),
  not asserted by the author.
- **`hygiene-inventory.json`** — the item-10 attestation inventory: the
  hygiene artifacts (README, license, workflows) and the commands the CI
  workflows run. The two commands marked `local_only` need the full toolchain
  and are run by `--attest`, carried (not re-run) by `--check`.
- **`item10-attestation.json`** — the envelope `klt signoff --attest 10`
  produced from the inventory. The manifest pins the inventory's sha256, so
  editing the inventory without re-attesting turns item 10 stale.

## Pinned tool

`klayout-tools==0.8.0` (the first release with `--attest`, needed for items 9
and 10). CI and the committed record use the same pin.

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

To re-attest an item after changing its inventory, re-pin **that inventory's**
sha256 in the manifest's `evidence.<item>.content_hash` — the manifest pins the
inventory, not the envelope — and regenerate the record above, all in the same
PR. Item 9 (its `cold_start` runs `make venv` itself, then every bench; allow
~10 minutes with the pinned tools on `PATH`):

```console
uvx --from "klayout-tools==0.8.0" klt signoff --attest 9 \
    --inventory manifests/testbench-inventory.json \
    -o manifests/item9-attestation.json
```

Item 10 (run `make venv` first so its `local_only` checks can run):

```console
uvx --from "klayout-tools==0.8.0" klt signoff --attest 10 \
    --inventory manifests/hygiene-inventory.json \
    -o manifests/item10-attestation.json
```

Both exit `3` and write nothing to `-o` when a check fails, so a failed
re-attest never silently overwrites a passing envelope.

**Editing a file one inventory lists means re-attesting that item**, because
each envelope records the sha256 of every file it checked. The two inventories
overlap with this directory and with CI, so in particular: changing
`.github/workflows/signoff.yml`, this README, the root `README.md`, `LICENSE`,
`sim/README.md`, `verification/README.md` or either other workflow drifts
**item 10** and must be followed by the item-10 re-attest above — otherwise
the item-10 `--check` step fails even though the verdict record is fresh.
Likewise, touching any bench under `verification/` drifts **item 9**. The
`--check` steps are what catch this, and they catch it at CI time, not review
time.

## Freshness is CI-enforced

`.github/workflows/signoff.yml` re-runs the grader on every push to `main`
and every pull request, accepts exit codes 0 and 3, and fails when the
fresh output differs byte-for-byte from the committed record. It also re-runs
both attestations with `--check`, so a bench or hygiene artifact that is
deleted or renamed without re-attesting fails CI rather than passing quietly.
