# sim

Reference models and the error-rate sweep. Every error-rate result produced
here is **simulated** and says so.

| Path | What |
|---|---|
| `channel/cm_a.py` | CM-A channel ([spec](../spec/target-spec.md#channel-model), [0002](../spec/decisions/0002-channel-model.md)): GFSK source, offset, drift, clock offset and timing phase, carrier phase, AWGN by Eb/N0, fixed AGC, 8-bit quantization with clip count; also packs/unpacks the 0007 `.rx.bin` record format |
| `channel/packet.py` | LE 1M test-packet bits (preamble, access address, PDU, CRC-24) |
| `model/le1m_rx.py` | Integer non-coherent LE 1M receiver; widths in [model/README.md](model/README.md) |
| `model/traces.py` | Shared 0007 trace reader/writer |
| `sweep/ber_sweep.py` | Seeded BER sweep, Clopper-Pearson stop rule, writes `results/<date>-<sha>/ber.json` |
| `model/le1m_tx.py` | Integer LE 1M TX reference model (PDU to whitened, CRC'd, Gaussian-shaped `tx_dev` words); trace format in [model/trace_format.md](model/trace_format.md); `model/golden/tx_adv_ch37.trace` is a generated golden trace |
| `channel/cm_a_oqpsk.py` | CM-A for 802.15.4: the TX model's O-QPSK waveform through the same offset, chip-clock and timing-phase (one chip), carrier-phase, AGC and 8-bit stages; AWGN set by SNR in a 2 MHz noise bandwidth |
| `model/oqpsk_tx.py`, `model/oqpsk_rx.py` | Integer 802.15.4 TX and non-coherent RX reference models |
| `sweep/per_sweep.py` | Seeded PER sweep (statistics and seeding imported from `ber_sweep.py`), writes `results/<date>-<sha>/per.json` |
| `tests/` | pytest controls |

## Commands

```
make sim-test                              # pytest controls (about 10 s)
make model-test                            # sim/tests plus the TX CRC negative control
python3 sim/sweep/ber_sweep.py --quick     # CI sweep; writes sim/results/<date>-<sha>/ber.json
python3 sim/sweep/ber_sweep.py             # full sweep (below)
```

`--quick` is 11 points with small packet caps; it ran in about 2 s locally. The
CI step is timed against the 5-minute bound on the runner (see the workflow log).
Quick mode proves the harness, not the row: its capped points are upper bounds
that cannot show the 16 dB row met.

**Full sweep.** `python3 sim/sweep/ber_sweep.py [--seed N] [--run-index N]
[--only ROW ...] [--packet-cap N] [--max-length-packet-cap N]`. Rows: `le1m_cfo`
(offsets −150…+150 kHz in 50 kHz steps, both extremes pinned), `le1m_drift`
(±50 kHz linear and stepped at offsets −150/0/+150 kHz), `le1m_clock` (±100 ppm
and 0 at the 2120 µs maximum packet), `le1m_uniform` (offset and clock drawn
per packet), each at Eb/N0 12, 14, 16, 18 dB. Defaults: 20000 packets per point
(3000 for max-length points), stop at 100 errors. That is hours of CPU single
threaded and is meant for a dedicated machine, not a shared dispatch worker;
split it into shards (next section).

**Shards and merge.** One shard is one row: `--only ROW` with exactly one row and
no `--out` writes `sim/results/<date>-<sha>/shards/ROW.json`, in the `ber.json`
format (it carries `base_seed`, point `run_index`, `sim_git_sha`, `mode`, and the
`stop_rule` packet caps). Shard row ids: `le1m_cfo`, `le1m_drift`, `le1m_clock`,
`le1m_uniform`, `negative_control` (the out-of-spec control, flagged and excluded
from `rows`). Smoke check one shard with tiny caps:

```
python3 sim/sweep/ber_sweep.py --only le1m_clock --packet-cap 2 --max-length-packet-cap 2
```

After all five shards exist in one `shards/` directory, assemble the full file:

```
python3 sim/sweep/ber_sweep.py --merge sim/results/<date>-<sha>/shards   # writes ../ber.json
```

`--merge` recomputes `rows` with the same `row_summary` and orders points by grid
index, so a merge equals a non-sharded run at the same caps. It exits non-zero,
naming the row or file, on a missing, duplicate or partial row; on shards that
disagree on seed, run index, mode, stop rule, SHA or SHA provenance; and on a
`-dirty` SHA or a `--quick` shard, so run shards from a committed tree. Use the
same `--seed`, `--run-index` and caps for every shard (the defaults are
unchanged). The shards are submitted as Spot batch jobs of the job kind in
2AMLogic/2am#6381; see that reference for submission, not this repo.

**`sim_git_sha` on a runner with no repo git root.** That job kind ships the tree
as a `git archive` tarball and makes a *throwaway* git root on the instance, so
`git_sha()` there reports a synthetic commit — a different one per shard, which
`--merge` then refuses. The submitting host knows the real commit, so it asserts
it: `--sim-git-sha <hex commit id>`. The report records which way the id was
obtained, in `sim_git_sha_source`: `derived` (read from this checkout's git) or
`asserted` (named on the command line). `--merge` requires every shard to agree
on that field too, so a derived shard and an asserted one never merge into one
record, and an asserted id is never read as a derived one. The flag takes a bare
lowercase hex id only, and is refused with `--merge` (a merged report takes the
id from its shards).

**Reading `ber.json`.** Each point carries seed, errors, bits, 95 % Clopper-Pearson
bounds, clip count, `stopped_by` and `bound_only`, and the label "simulated,
CM-A". A `bound_only` point hit its packet cap and is an upper bound, not a
measurement. Bit errors are wrong decisions among the bits the receiver
returned: a packet delivered with the wrong length (length field corrupted, or
the demodulation exhausted the record) is counted in `undelivered_packets` and
scored over the comparable prefix, never charged for bits it did not demodulate
(decision [0009](../spec/decisions/0009-le-ber-undelivered-packet-accounting.md));
`packet_loss` is the fraction of packets not delivered intact (sync miss or
wrong-length delivery) and qualifies a BER row. A sync-missed packet counts as
every PDU+CRC bit in error. `rows` reports, per row at 16 dB, the worst upper
bound, the worst `packet_loss`, whether the bound is ≤ 1e-3, whether the loss
is ≤ 1e-2 and `row_passes` — the conjunction of the two, since decision
[0011](../spec/decisions/0011-le-packet-loss-bound.md) a row passes only if
both hold; that is a report for the evidence record, not a claim that the row
is met.
`negative_control` and `out_of_spec` points are excluded from `rows`.

## The committed LE 1M sweep (`sim/results/2026-11-14-88245d69b74d/`)

**Simulated, CM-A.** One full (non-`--quick`) run of all four ratified LE 1M rows
plus the negative control, at Eb/N0 12 / 14 / 16 / 18 dB, default packet caps,
`--seed 1`, `--run-index 0`, NumPy 1.26.4 (this repo's `requirements.txt` pin).
93 points. It is an error-rate record, not a claim that a row is met.

**Where it ran.** Not on a loom-worker and not on an operator machine: five
per-row shards as `repo-script` Spot batch jobs (2AMLogic/2am#6381, operator
ruling 2026-10-28 / fleet:decide q82), heavy image `ami-08688417b66e0c74d`, one
`m7i.4xlarge` each. The tree shipped as a `git archive` tarball of commit
`88245d69b74db5b9e0c90cc085fe203ef7e413cb`, SHA-256
`dd9a8743f82113e91d3c883d8078047e7f7aa1ee807bdd5fde63e1d37bc41b36` — that hash,
not the commit id, is the durable input identity, because this evidence was
produced from the pull request head for issue #55 and that commit is not
reachable on `main` after a squash merge. The `sim/` tree it names is the one
this record was merged in with.

**The commands.** Submitted from the fleet repo's submitter; `<SHA12>` is
`88245d69b74d`, the 12-character form `sim_git_sha` records:

```
infra/aws/repo-script-submit.py --source-dir <this checkout> --commit HEAD \
    --repo 2AMLogic/sky130-ble-baseband --issue 55 \
    --script sim/sweep/ber_sweep.py --output sim/results \
    --shard "--only le1m_cfo       --sim-git-sha <SHA12>" \
    --shard "--only le1m_drift     --sim-git-sha <SHA12>" \
    --shard "--only le1m_clock     --sim-git-sha <SHA12>" \
    --shard "--only le1m_uniform   --sim-git-sha <SHA12>" \
    --shard "--only negative_control --sim-git-sha <SHA12>" \
    --out <collect dir>
python3 sim/sweep/ber_sweep.py --merge sim/results/2026-11-14-88245d69b74d/shards
```

`--sim-git-sha` is required here, for the reason in the previous section. The
five collected shard files are committed beside `ber.json` under `shards/`, so
the merge can be re-run from them without re-simulating.

**Wall time.** 438 s (`le1m_cfo`), 541 s (`le1m_drift`), 184 s (`le1m_clock`),
53 s (`le1m_uniform`), under 1 s (`negative_control`); no shard was reclaimed
(`retry_count` 0). The three largest ran concurrently, so the sweep took about
10 minutes of wall clock and about 20 minutes of CPU — the "hours single
threaded" above is the pre-shard figure and was not re-measured on one core.

Submitting all five at once launched only **three**: the heavy slice
(`BATCH_HEAVY_MAX_VCPU=64`) had 16 of its 64 vCPU free after three 16-vCPU
instances, but the launcher also wants three instance types to fit, and only two
do at 16 vCPU. So the fourth and fifth shards were refused at launch
(`BATCH_HEAVY_MAX_VCPU`) and resubmitted as a second group, which is the
documented recovery. Nothing was run locally and no cap was lowered.

**What it reports.** `rows` reports, per row at 16 dB, the worst 95 % CP upper
bound and whether it is ≤ 1e-3. Every in-spec 16 dB point reached 100 errors, so
no row verdict here rests on a capped point:

| row | worst CP upper at 16 dB | ≤ 1e-3 | all points measured |
|---|---|---|---|
| `le1m_cfo` | 1.053e-02 | **no** | yes |
| `le1m_drift` | 1.694e-03 | **no** | yes |
| `le1m_clock` | 3.852e-05 | yes | yes |
| `le1m_uniform` | 2.478e-04 | yes | yes |

**Two rows miss, and the miss is recorded, not relaxed.** `le1m_cfo` misses on
its **zero-offset** point (BER 9.3e-03 at 16 dB), which is 160x worse than the
-50 kHz point (5.7e-05) in the same row and Eb/N0 — the row is *not* worst at
the offset extremes, and BER is non-monotonic in Eb/N0 at several offsets. That
pattern points at the receiver model rather than at the stop rule or the caps;
it is a receiver finding, tracked separately, and nothing here was tuned to make
a row pass. `le1m_drift` misses by about 1.7x on three points.

**Superseded for LE BER readings** by the corrected-accounting record below:
those two row misses were the error-accounting artifact of decision
[0009](../spec/decisions/0009-le-ber-undelivered-packet-accounting.md), not a
receiver property. This record stays as committed (append-only).

**The negative control.** Point 92, 800 kHz offset at 16 dB, flagged
`out_of_spec` and excluded from `rows`: BER 1.000 (336 of 336 bits, one sync
miss), CP bounds [9.891e-01, 1.000]. It fails the row by four orders of
magnitude, which is what a working control looks like.

**Reproducing it.** Re-run the commands above at the same commit (or any tree
with the same tarball SHA-256) and the same NumPy, and `ber.json` is
byte-identical except for the `<date>-<sha>` directory name. Verified by
re-running the `le1m_uniform` shard as a second batch job on the same image: see
the PR for #55. Cross-machine identity is not claimed (see "Determinism").

## The corrected-accounting LE 1M sweep (`sim/results/2026-11-15-8bdc8843f6f8/`)

**Simulated, CM-A.** The full sweep of issue #133 re-run under decision
[0009](../spec/decisions/0009-le-ber-undelivered-packet-accounting.md)'s
accounting: identical grid, seeds (`--seed 1`, `--run-index 0`), packet caps
and NumPy 1.26.4 as the 2026-11-14 record, so every point replays the same
packets and differs only in how they are scored. 93 points, produced from the
tree of commit `8bdc8843f6f8` — the commit that fixed the scoring. Generated
evidence, not hand-written; the shards are committed beside `ber.json`.

| row | worst CP upper at 16 dB | ≤ 1e-3 | all points measured | worst packet loss |
|---|---|---|---|---|
| `le1m_cfo` | 5.102e-05 | **yes** | yes | 1.16e-03 |
| `le1m_drift` | 2.939e-04 | **yes** | yes | 1.24e-03 |
| `le1m_clock` | 3.852e-05 | yes | yes | 0 (no loss events) |
| `le1m_uniform` | 3.920e-05 | yes | yes | 6.50e-04 |

**Both formerly-missing rows now meet 1e-3, and the reason is stated, not
smuggled.** `le1m_cfo`'s 2026-11-14 miss was one truncated packet charged as
257 bit errors (16 dB / 0 Hz stopped after 82 packets); the same point under
corrected scoring runs 10 735 packets and measures BER 2.77e-05, in family with
its neighbouring offsets. `le1m_drift`'s miss was the same artifact. The
receiver's packet-level behaviour is unchanged between the records — the
point seeds are identical, so this comparison is the same noise draw scored
two ways, not a kinder run. Loss figures sit beside every row above and every
point in the file: a BER row is qualified by them, per decision 0009.

**Where it ran.** Five per-row shards as `repo-script` Spot batch jobs
(2AMLogic/2am#6381), heavy image `ami-08688417b66e0c74d`, one `m7i.4xlarge`
each, no shard reclaimed (`retry_count` 0). The tree shipped as a `git
archive` tarball of commit `8bdc8843f6f8e991f16c1ebfdb878fc253367cf1`, SHA-256
`f364e3b87975aa21dba511c9e52513921f0b5e6cb14418ca8f63f924295ee7a1`. Two
groups, because the fleet's heavy slice had room for three 16-vCPU instances,
not five: `le1m_cfo` (568 s), `le1m_drift` (675 s) and `le1m_clock` (185 s)
ran first; `le1m_uniform` (71 s) and `negative_control` (<1 s) were refused at
launch (`BATCH_HEAVY_MAX_VCPU`) and resubmitted as a second group — the
documented recovery, also seen on the 2026-11-14 run. Nothing was run locally
and no cap was lowered.

**The second error path, recorded.** The 2026-11-14 record's rare
many-errors-per-packet events (the 18 dB packets charged 175 and 164) are *not*
the truncation path: replay shows `len(got) = 443 > 336` — the length field
read long from corrupted header bits, the demodulation exhausted the record,
and ~52 % of the comparable prefix mismatched from bit 4/12 on, a whole-packet
demodulation derangement. Corrected scoring charges them as they should be
charged: wrong decisions among bits the receiver returned.

**The negative control.** 800 kHz offset at 16 dB: BER 1.000, CP bounds
[9.891e-01, 1.000] — fails the row by three orders of magnitude, as a working
control must.

**Reproducing it.** Same commands as the 2026-11-14 record with the shards
split as above, at commit `8bdc8843f6f8` (or any tree with the same tarball
SHA-256) and NumPy 1.26.4; `--sim-git-sha 8bdc8843f6f8` on every shard.

## PER sweep (802.15.4)

```
python3 sim/sweep/per_sweep.py --quick     # CI sweep (make sim-quick runs it after the BER one)
python3 sim/sweep/per_sweep.py             # full sweep
python3 sim/sweep/per_sweep.py --only per_cfo --packet-cap 20
```

Rows: `per_snr` (20-octet PSDU, SNR -1…9 dB, no offsets), `per_cfo` (20 octets,
offsets -196…+196 kHz in 49 kHz steps, both ±80 ppm extremes pinned, SNR 3/5/7 dB),
`per_clock` (127 octets, chip clock -80/0/+80 ppm, SNR 3/5/7 dB), and
`negative_control` (800 kHz offset at 9 dB, flagged out of spec and excluded
from `rows`). A packet is in error if it is not detected, the FCS fails, or the
PSDU is not returned exactly. Stop at 100 packet errors or the cap (default 20000
packets, 3000 at 127 octets; `--quick` 40 and 10); a capped point is `bound_only`.
`per.json` reports, per row at 5 dB, the worst upper bound and whether it is
below 1 %, plus a `negative_control` record whose `fails_row` must be true; both
are reports, not assertions. The full sweep is hours of CPU and is meant for a
dedicated machine, not a shared dispatch worker. Same determinism contract as
above. `--quick` proves the harness, not the row.

### Full-sweep run record (2026-11-14)

`results/2026-11-14-1564a0ec0cfb/per.json` is the committed full-caps run. It was
produced on the Spot batch fleet through the `repo-script` job kind
(2AMLogic/2am#6381), not on a shared dispatch worker.

| | |
|---|---|
| Command | `python3 sim/sweep/per_sweep.py --seed 1 --run-index 0 --out sim/results/spot/per.json` |
| Source commit | `1564a0ec0cfb`, clean tree (`run.json`: `1564a0ec0cfb21ec354683b43899cc7e10ec0933`) |
| Seed / run index | `--seed 1` / `--run-index 0` |
| Packet caps | defaults — 20000 packets per point, 3000 at 127 octets, stop at 100 errors |
| Spot group / job | `rs-20261114T184505Z-1564a0ec` / `rs-20261114T184505Z-1564a0ec-s00` |
| Instance | `i-0d91821c074de2710`, `m6i.4xlarge`, `us-east-1c`, spot, AMI `ami-08688417b66e0c74d` |
| Wall time | 689 s, 0 Spot retries (single threaded: `cpu_busy_fraction` 0.0627 of 16 vCPU) |

689 s is far under the hours-of-CPU estimate above because PER is high at most grid
points, so the 100-error stop rule ends a point after 100–3000 packets instead of at
the cap. Only the 9 dB `per_snr` point ran to the 20000-packet cap, and it is the
run's one `bound_only` point; the other 42 points are measurements.

**Provenance caveat.** The file's own `sim_git_sha` reads `3f7ee0f76614`, which is
**not** a commit of this repository. The `repo-script` runner `git init`s the
extracted `git archive` tarball and makes one local commit so work-tree-relative
tooling resolves, so `git_sha()` records that synthetic commit instead of the
submitted one. The real source commit is the `1564a0ec0cfb` above, taken from the
job's `run.json`. The file is committed exactly as produced — results here are
append-only evidence and are not hand-edited. Tracked upstream as 2AMLogic/2am#7287.

**Row verdicts as found** — reported, not asserted; `rows` summarises each row at
5 dB against PER < 1 %:

| Row | Worst 95 % CP upper at 5 dB | Below 1 %? |
|---|---|---|
| `per_snr` (20 octets, no offsets) | 0.504 | no |
| `per_cfo` (20 octets, incl. both ±196 kHz ends) | 0.828 | no |
| `per_clock` (127 octets, ±80 ppm) | 0.849 | no |
| `negative_control` (800 kHz offset at 9 dB) | 1.000 | `fails_row` true, as designed |

All three ratified rows are **missed** at the spec's 5 dB ceiling. `per_snr` first
gets under 1 % at 9 dB (5.5e-4, CP upper 9.8e-4), so the reference receiver is about
4 dB short of the `spec/target-spec.md` row and 2 dB short of its fallback. That is a
recorded result, not a reason to relax a ratified row; the shortfall is dispositioned
in #137.

### Sensitivity budget (issue #137)

The committed `per_snr` row misses the ratified ceiling, and
`sim/analysis/oqpsk_sensitivity_budget.py` is the attribution measurement: it
re-runs selected `per_snr` points with the receiver's acquisition constants
overridden one at a time (proving each override took effect through the real
`_accept`/`channel_filter`), splits error classes per point, and measures the
input-quantization contribution on a 1/16 LSB grid via the `keep_float` hook.
It changes no committed behaviour — `sim/model/`, `rtl/` and `spec/` stay
byte-identical, and the script asserts its unmodified baseline reproduces the
committed 5/7/9 dB `per_snr` points exactly before reporting any delta.

```
python3 sim/analysis/oqpsk_sensitivity_budget.py --quick    # smoke, < 1 min
python3 sim/analysis/oqpsk_sensitivity_budget.py            # full budget, ~25 min single-threaded
```

The recorded finding is `results/oqpsk-sensitivity-budget-2026-11-15.md`
(raw points in the `.json` beside it), all simulated, CM-A: the crossing is
in (7.5, 8] dB (shortfall (2.5, 3] dB vs the 5 dB target); `sync_misses`
dominates everywhere and the residual class is zero; the accept **ratio**
term (`4·corr ≥ 3·mag`) is the dominant recoverable cost (≈ 3.1 dB by
relaxing it to `corr ≥ mag/2`, which is a receiver change carrying the
matching RTL edit with it), the absolute floor never binds, `PREAMBLE_RUN`
is ≈ 0.2 dB, and 8-bit quantization and clipping are measurably ~0 dB.

## Determinism

Seed = SHA-256 of (row id, impairment settings, point index, run index, `--seed`),
PCG64 via NumPy; the NumPy version is recorded in `ber.json`. Two runs with the
same arguments on the same machine and NumPy give byte-identical JSON; the
`<date>-<sha>` directory is the only varying part. Floating-point library
differences across platforms can change a quantized sample, so cross-machine
identity is not claimed.

## Modelling choices to know

- Stages 2-5 of CM-A are one resampling step, applied to the baseband and to an
  unwrapped phase track (equivalent order, narrower interpolation band).
- Drift `linear`: ramp from 0 to the total over the packet. `stepped`: the whole
  drift at the peak rate (20 kHz per 50 µs) starting at the packet midpoint.
- AGC: one settled gain per capture from the rms of the noisy record, 1.5 dB steps,
  target 32 LSB complex rms. A closed AGC loop is out of scope here.
- Data whitening is not modelled (random payload; see `model/README.md`).
- The TX reference model (`model/le1m_tx.py`) is not used by this sweep; the sweep uses its
  own float GFSK source, which is a channel-side stimulus, not a swept model.
