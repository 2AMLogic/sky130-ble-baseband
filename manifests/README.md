# Block manifest and tier-verdict record

This directory holds this block's `klt signoff` input and its committed
output, so the gap to the klayout-tools T1 checklist is read from a tool
rather than from prose.

## Files

- **`sky130-ble-baseband.json`** — the block manifest: `block`,
  `kind: digital`, and an `evidence` map. It cites evidence for item 5 (the
  functional half: `klt functional-verification` reports, see
  `requests/fv/` below), item 9 (the testbench attestation) and item 10 (the
  hygiene attestation); no design artifact exists for the other items yet.
- **`requests/fv/`** — the `klt functional-verification` request documents
  behind item 5's citations (issue #202): 22 passing runs (one per bench in
  the item-9 inventory — host at both ratified configurations, le1m_tx,
  le1m_rx, oqpsk_tx, oqpsk_rx, every mac module at the 32 MHz target and the
  16 MHz fallback counts, top, and the section-3 latency checks) plus 11
  negative controls (`.negative.json`). Generated, never hand-edited: every
  request's `sources` come from `rtl/baseband.f` through
  `verification/rtl_sources.py`, the mac cycle budgets from
  `verification/mac/run_mac.py`, both via `verification/fv/suite.py`.
  `make fv-requests` regenerates; `make fv-requests-check` (part of
  `make lint`) fails when a committed request drifts from the file list. The
  four benches whose runners generate stimulus before simulation starts
  (le1m_tx, le1m_rx, oqpsk_tx/rx) run through the wrapper modules in
  `verification/fv/`, which perform the same pre-step the `run_*.py` script
  does and re-export the unmodified bench; the benches themselves are
  untouched.
- **`reports/fv/`** — the committed item-5 evidence: one `klt
  functional-verification` JSON report per request above (negatives as
  `<name>.negative.json`). Every positive report is `status: "pass"` with
  zero failed and zero skipped tests; every negative is `status: "fail"`
  with a failure whose `error_message` carries the same right-reason
  pattern the Makefile's own negative targets grep for. `make fv-check`
  (part of `make lint`) re-validates all of that, plus that no report
  contains an absolute host path. Regenerate everything with
  `make fv-reports`.
- **`design-evidence-tiers.md`** — the T1-T4 checklist the grader parses.
  Vendored **byte-identical** from
  [`2AMLogic/klayout-tools@e88f211`](https://github.com/2AMLogic/klayout-tools/blob/e88f211fa485959b382e2596c86648ce4e66ea78/docs/design-evidence-tiers.md)
  `docs/design-evidence-tiers.md` (2026-10-17; upstream is MIT-licensed,
  and this repo's license does not relicense the vendored copy). When
  upstream moves, re-vendor the doc and regenerate the record in the same
  PR.
- **`sky130-ble-baseband.signoff.json`** — the **verdict of record**:
  committed output of the command below. Never hand-edit it. Today item 5
  reads `unmet` / `partial_coverage` (the functional half is cited; the
  grader's `detail.missing_kinds` names `sta`, which stays open in #42
  until the routed netlist exists), item 9 and item 10 read `met`, and every
  other T1 item reads `unmet` / `no_evidence`; the three rows beyond T1 read
  `unmet` / `tier_not_supported`.
- **`testbench-inventory.json`** — the item-9 attestation inventory. Its
  listing rule: every tracked file under `verification/` other than that
  directory's own README (an item-10 hygiene artifact) that the targets in
  this inventory's own `cold_start.argv` execute or import. Benches and the
  harness modules those targets load qualify alike, which is why
  `cocotb_run.py`, `rtl_sources.py`, the shared runners, case tables and
  common helpers are listed next to the benches they serve. A file the cold
  start never executes or imports is deliberately not listed; each such
  file is dispositioned under "Item 9 scope" below. The inventory also
  carries the one `cold_start` invocation that runs them all from a clean
  checkout, and the `pins` block (PDK revision and tool versions) item 9
  requires. The cold start is marked `local_only` — it needs Icarus,
  Verilator, Yosys and the cocotb venv, so `--attest` runs it and `--check`
  carries its committed outcome. The cold start runs the bench targets
  only: `lint` belongs to item 10, `synth` cannot complete yet
  (`flow/synth/README.md`), and the `sim/` reference-model, channel-model
  and sweep-harness tests are anchored outside item 9 — the decision and
  its reasoning are recorded in "Item 9 scope" below.
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

### Item 9 scope: why no `sim/` path is inventoried

Recorded 2026-11-15 (#142). Item 9's claim is every *claimed measurement's*
testbench. This block's chain is a reference receiver in `sim/` under a
declared channel model, error-rate sweeps on it, then RTL benches that
replay the models' traces bit-exactly (decision 0007) — and the item-9
inventory holds the RTL side of that chain, the part that ties an error-rate
record to this block. The `sim/` side is deliberately anchored elsewhere:

1. **Reference-model and channel-model tests** (`sim/tests/`): audited by
   item 10's `reference-model tests (make sim-test)` check, and run in CI
   twice — `flow.yml` via `make model-test` and `sim.yml` via
   `make sim-test`. Folding them into item 9's cold start would re-run what
   item 10 already attests, spending cold-start headroom (~607 s of klt's
   1800 s command-evidence bound, measured at the #129 review) for no new
   evidence.
2. **BER sweep harness and result** (`sim/sweep/ber_sweep.py`,
   `sim/tests/test_ber_sweep.py`,
   `sim/results/2026-11-14-88245d69b74d/`): the inventory description's
   commitment — "those sweeps enter this inventory when their results land"
   — fired when PR #134 committed the LE 1M results. Discharged by this
   record rather than by widening: the harness is committed with
   reproduction commands in `sim/README.md` (an item-10 hygiene artifact;
   item 10's README requirement covers reproducing every result), its pytest
   control runs in CI and is audited by item 10's `make sim-test` check, and
   the committed `ber.json` rows are records — simulated, CM-A — not row
   claims item 9 grades. No BER *result* is attested under item 9.
3. **PER sweep** (`sim/sweep/per_sweep.py`, `sim/tests/test_per_sweep.py`,
   `sim/results/2026-11-14-1564a0ec0cfb/per.json`): deferred. #56 landed the
   sweep and #137 the attribution analysis; the committed sensitivity budget
   (simulated, CM-A) puts the PER < 1 % crossing at ~8 dB against the
   ratified ≤ 5 dB row (≤ 7 dB fallback), so no PER result can back an
   item-9 claim until the row is met or the row is revisited through
   `spec/`.

`verification/rtl_sources.py` (added by #127) **is listed**: every
`run_*.py` runner imports it to build its RTL source list, so it
participates in the cold start this inventory attests. Its earlier
"deliberately not
listed" disposition (recorded here by #142) was settled the other way by
#158, against the listing rule stated above.

Two files under `verification/` remain deliberately not listed, because no
`cold_start.argv` target executes or imports them:
`verification/tests/test_rtl_sources.py` runs under `make parser-test` in
`.github/workflows/flow.yml`, and `verification/top/latency_record.md` is
the append-only record the latency target produces, not code a run
executes. Neither is anchored by an attestation today; anchoring them
elsewhere is a separate completeness question, not an omission of the rule
above. The `verification/fv/` suite (issue #202) falls under the same rule
from the other side: its modules are executed only by `klt
functional-verification` through the committed requests, never by a
cold-start target, so they are not listed here — their evidence is the
item-5 report set, structurally validated by `make fv-check` inside
`make lint` (an item-10 check), and the requests' source lists are guarded
against `rtl/baseband.f` drift by `make fv-requests-check` in the same
place.

## Pinned tool

`klayout-tools==0.9.2`. Bumped from 0.8.0 (the first release with `--attest`,
needed for items 9 and 10) because item 5's functional evidence needs
request-level `env` for the cocotb benches (2AMLogic/klayout-tools#4338,
first released in 0.9.0) and the evidence-file `content_hash` basis that lets
a manifest pin a `functional-verification` citation
(2AMLogic/klayout-tools#4893). CI and the committed record use the same pin.
`make lint` checks these literals against CI's pin
(`verification/tool_pins.py`, #171), so a bump changes `signoff.yml` and
every command block here in the same commit.

## Regenerate

```console
uvx --from "klayout-tools==0.9.2" klt signoff \
    --manifest manifests/sky130-ble-baseband.json \
    --tiers-doc manifests/design-evidence-tiers.md \
    --format json > manifests/sky130-ble-baseband.signoff.json
```

The command exits `3` when at least one T1 item is `unmet` (a valid, clean
run) and `0` when every item is `met`. Any change that affects the verdict
— new evidence, a manifest edit, a vendored-doc bump, a version-pin bump —
regenerates and commits the record in the same PR.

### The item-5 functional evidence changed

Regenerate the reports (and their negative controls) from the requests, then
re-pin the citations' `content_hash` values and regenerate the record, all in
the same PR:

```console
make fv-reports     # runs every request; regenerates manifests/reports/fv/
.venv/bin/python - <<'PY'
import hashlib, json, sys
sys.path[:0] = ["verification/fv"]
import suite
cites = [{"file": (f := suite.REPORTS_DIR / f"{b['name']}.json").relative_to(suite.ROOT).as_posix(),
          "content_hash": "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()}
         for b in suite.POSITIVE]
manifest = json.load(open("manifests/sky130-ble-baseband.json"))
manifest["evidence"]["5"] = cites
with open("manifests/sky130-ble-baseband.json", "w") as fh:
    json.dump(manifest, fh, indent=2); fh.write("\n")
PY
```

`make fv-reports` itself validates every report (all tests pass, every
negative fails for the right reason, no absolute host paths); `make
fv-check` re-validates the committed set without running anything, and is
part of `make lint`.

**How stale item-5 evidence is caught.** Each citation's `content_hash`
pins the report file's own bytes (`content_hash_basis: "evidence_file"`,
2AMLogic/klayout-tools#4893 — this verb's envelope carries no input-hash
`provenance` at the pinned release), so a re-run or hand-edit of a
committed report makes `klt signoff` grade it `stale_evidence`, and the
byte-compare step in `signoff.yml` fails on the changed verdict. Editing a
bench under `verification/` is caught by the item-9 `--check` step (the
envelope records every inventoried file's sha256). An edit to an RTL source
under `rtl/` that leaves the committed reports untouched is **not**
detected by `klt signoff` at any released klt: that is the gap
2AMLogic/klayout-tools#5550 tracked, and its fix (a `provenance` block that
pins citations to the RTL digest, upstream commit `74a3512b`) is not in a
release at this pin. When a release carries it, bump the pin, regenerate
the reports (they will carry provenance), re-pin the citations, and this
caveat goes away. Until then CI's flow job — which re-runs the benches
themselves on every PR — is what turns a behavioural RTL break red; no
repo-local hash checker is added to substitute for the missing verb
capability.

### A hygiene artifact changed

**Editing a file one inventory lists means re-attesting that item**, because
each envelope records the sha256 of every file it checked. The two inventories
overlap with this directory and with CI, so in particular: changing
`.github/workflows/signoff.yml`, this README, the root `README.md`, `LICENSE`,
`sim/README.md`, `verification/README.md` or either other workflow drifts
**item 10** and must be followed by the item-10 re-attest below — otherwise
the item-10 `--check` step fails even though the verdict record is fresh.
Likewise, touching any bench under `verification/` drifts **item 9**. The
`--check` steps are what catch this, and they catch it at CI time, not review
time.

The re-attest is the only step an artifact edit needs. The inventory is
byte-unchanged, so the manifest's `evidence."10".content_hash` pin — the
**inventory's** sha256, never the envelope's — still holds, and
`manifests/sky130-ble-baseband.signoff.json` is byte-unchanged too, because
an artifact-only edit does not change the graded verdict. Re-pinning the
**envelope's** own sha256 into `evidence."10".content_hash` instead grades
item 10 `stale_evidence`. And if `manifests/item10-attestation.json`
conflicts on rebase, resolve the conflict by re-running `--attest` on the
rebased tree — never by hand-merging the JSON.

Item 10 (run `make venv` first so its `local_only` checks can run):

```console
uvx --from "klayout-tools==0.9.2" klt signoff --attest 10 \
    --inventory manifests/hygiene-inventory.json \
    -o manifests/item10-attestation.json
```

Item 9 (its `cold_start` runs `make venv` itself, then every bench; allow
~10 minutes with the pinned tools on `PATH`):

```console
uvx --from "klayout-tools==0.9.2" klt signoff --attest 9 \
    --inventory manifests/testbench-inventory.json \
    -o manifests/item9-attestation.json
```

### The inventory changed

To re-attest an item after changing its inventory, re-pin **that inventory's**
sha256 in the manifest's `evidence.<item>.content_hash` — the manifest pins the
inventory, not the envelope — and regenerate the record above, all in the same
PR, in addition to the re-attest. Item 9 (its `cold_start` runs `make venv`
itself, then every bench; allow ~10 minutes with the pinned tools on `PATH`):

```console
uvx --from "klayout-tools==0.9.2" klt signoff --attest 9 \
    --inventory manifests/testbench-inventory.json \
    -o manifests/item9-attestation.json
```

Item 10 (run `make venv` first so its `local_only` checks can run):

```console
uvx --from "klayout-tools==0.9.2" klt signoff --attest 10 \
    --inventory manifests/hygiene-inventory.json \
    -o manifests/item10-attestation.json
```

Every `--attest` command above exits `3` and writes nothing to `-o` when a
check fails, so a failed re-attest never silently overwrites a passing
envelope.

## Freshness is CI-enforced

`.github/workflows/signoff.yml` re-runs the grader on every push to `main`
and every pull request, accepts exit codes 0 and 3, and fails when the
fresh output differs byte-for-byte from the committed record. It also re-runs
both attestations with `--check`, so a bench or hygiene artifact that is
deleted or renamed without re-attesting fails CI rather than passing quietly.
