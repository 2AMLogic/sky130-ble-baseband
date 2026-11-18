# 802.15.4 PER sensitivity budget (issue #137)

**Simulated, CM-A.** Attribution of the `sim/model/oqpsk_rx.py` reference
receiver's shortfall against the ratified PER row (`spec/target-spec.md`,
"Demodulator performance"): PER < 1 % at SNR ≤ 5 dB in 2 MHz noise bandwidth
(target), ≤ 7 dB (fallback). Every number below is simulated, carries its seed
and packet cap in `oqpsk-sensitivity-budget-2026-11-15.json` (same directory),
and every capped point is marked as a 95 % Clopper-Pearson **upper bound**, not
a measurement. Row verdicts use the CP upper bound, as the spec row requires.

- **Producer**: `sim/analysis/oqpsk_sensitivity_budget.py`, from the tree at
  commit `92d2d00de72a` (the analysis script and its tests; `sim/model/`,
  `rtl/` and `spec/` are byte-identical to `origin/main`, no committed
  behaviour change). NumPy 1.26.4 (the repo pin), PCG64, `--seed 1
  --run-index 0`, stop at 100 packet errors or the point's packet cap
  (baseline 20000, bracket points 7.5/8/8.5 dB 6000, variant and
  quantization points 4000). Same-machine identity only (sim/README.md
  "Determinism"); the run reproduced the committed sweep's `per_snr` points at
  5/7/9 dB exactly before any variant delta was taken.
- **Method**: each experimental arm overrides the receiver's module-level
  acquisition constants around `per_sweep.run_point` and the override is
  **proven** to have taken effect through the real `_accept`/`channel_filter`
  before the arm's numbers are trusted; all arms share the baseline's packet
  stream (same seed derivation, `ber_sweep.point_seed`), so arm-vs-baseline
  deltas are paired on identical stimulus.

## 1. Where the crossing actually is (AC 4)

The committed 2 dB grid bracketed the crossing in (7, 9] dB. Measured here:

| SNR (dB) | packets | errors | PER | 95 % CP upper | class split (sync / fcs / residual) | stopped by |
|---|---|---|---|---|---|---|
| -1 | 100 | 100 | 1.0 | 1.0 | 100 / 0 / 0 | 100 errors |
| 1 | 100 | 100 | 1.0 | 1.0 | 100 / 0 / 0 | 100 errors |
| 3 | 100 | 100 | 1.0 | 1.0 | 97 / 3 / 0 | 100 errors |
| 5 | 229 | 100 | 0.4367 | 0.5036 | 91 / 9 / 0 | 100 errors |
| 7 | 2462 | 100 | 0.04062 | 0.04918 | 98 / 2 / 0 | 100 errors |
| 7.5 | 5640 | 100 | 0.01773 | 0.02152 | 100 / 0 / 0 | 100 errors |
| 8 | 6000 | 38 | 0.006333 | **0.008683** | 38 / 0 / 0 | packet cap — **bound** |
| 8.5 | 6000 | 13 | 0.002167 | 0.003702 | 13 / 0 / 0 | packet cap — **bound** |
| 9 | 20000 | 11 | 5.5e-4 | 9.839e-4 | 11 / 0 / 0 | packet cap — **bound** |

The 5/7/9 dB points reproduce the committed evidence
(`sim/results/2026-11-14-1564a0ec0cfb/per.json`, quoted in the issue)
exactly: 229/100, 2462/100 and 20000/11 packets/errors.

**The crossing is in (7.5, 8] dB**: 7.5 dB *measured*-fails (upper 0.0215),
the 8 dB point's upper bound 0.0087 is the first under 1 % (a `bound_only`
point — 38 errors — so the pass is an upper-bound claim, like the committed
9 dB pass). The shortfall against the 5 dB target is therefore in
**(2.5, 3]** dB, tightening the issue's (2, 4] bracket.

**AC 1, the class split**: `sync_misses` dominates at every SNR (91-100 of
100 errors wherever the count is measured). The residual third class
(`errors − sync_misses − fcs_failures`, correction 2 of the issue) is **zero
at every `per_snr` point** — reported, not assumed — so nothing in this row
points at a PHR/length mis-parse; the gap is acquisition, not PSDU corruption.
FCS failures are a minor class (9/100 at 5 dB, 2/100 at 7 dB, 3/100 at 3 dB,
0 elsewhere measured).

## 2. The acquisition gate, one constant at a time (AC 2)

Baseline constants: `MIN_AMPLITUDE = 4096` (absolute floor
`corr_best ≥ 126976`), `ACCEPT_NUM/ACCEPT_DEN_SHIFT = 3/2` (ratio
`4·corr ≥ 3·mag`, i.e. ≥ 87.5 % magnitude-weighted chip-transition sign
agreement), `PREAMBLE_RUN = 4`. One at a time, against the same packets:

| arm | override | PER at 5 dB | PER at 7 dB | 7 dB CP upper | 7 dB vs baseline (derived, see note) |
|---|---|---|---|---|---|
| baseline | — | 0.4367 (100/229, meas.) | 0.04062 (100/2462, meas.) | 0.0492 | — |
| `minamp_2048` | floor 4096→2048 | 0.4367 | 0.04062 | 0.0492 | **0.0 dB** |
| `minamp_1024` | floor 4096→1024 | 0.4367 | 0.04062 | 0.0492 | **0.0 dB** |
| `ratio_only` | floor → 0 (ratio only) | 0.4367 | 0.04062 | 0.0492 | **0.0 dB** |
| `floor_only` | ratio disabled (floor only) | 0.09814 (100/1019, meas.) | 0.00325 (13/4000, **bound**) | 0.00555 < 1 % | **≈ 2.1 dB recovered** |
| `ratio_half` | ratio 3/4 → 1/2 | 0.1259 (100/794, meas.) | 0.001 (4/4000, **bound**) | 0.00256 < 1 % | **≈ 3.1 dB recovered** |
| `prerun_2` | `PREAMBLE_RUN` 4→2 | 0.3367 (100/297, meas.) | 0.03232 (100/3094, meas.) | 0.0392 | **≈ 0.2 dB recovered** |

Note on the last column: the dB figure is **derived arithmetic on two measured
PERs** — the baseline's measured local slope (1.94 dB per decade of PER
between the 5 and 7 dB points; 5.56 dB/decade between 3 and 5 dB, 1.39
between 7 and 7.5) times the log-ratio of the two PERs on the same packet
stream. It is an equivalent-shift estimate, not a crossing measurement.

Findings:

- **The absolute floor never binds.** Halving it, quartering it, or deleting
  it (`ratio_only`) reproduces the baseline outcome **packet-for-packet** at
  every SNR (identical error counts on identical stimulus). `MIN_AMPLITUDE`
  is not where any dB are.
- **The 3/4 ratio term is the dominant recoverable cost.** Relaxing it to 1/2
  (75 % weighted agreement instead of 87.5 %) recovers ≈ 3.1 dB-equivalent at
  7 dB and moves that point's upper bound from 0.0492 (fails) to 0.00256
  (passes the 1 % fallback row, as an upper-bound claim at cap 4000). Its 8 dB
  point has **0 errors in 4000** (upper 9.2e-4).
- **Full ratio removal is worse than relaxation, and regresses at high SNR.**
  `floor_only` recovers less at 7 dB (≈ 2.1 dB) and at 9 dB *worsens* to
  12 errors in 4000 (vs the baseline's 2): with the ratio gone, false
  acquisitions rise, and at 5 dB its dominant error class flips from
  `sync_misses` to `fcs_failures` (86/100) — the loose gate detects *something*
  and then demodulates the wrong thing. Any gate change must keep the ratio
  term or add a false-acquisition guard; the search's `hits`/`floor` ordering
  (one bad hit can skip past the true preamble) is part of that mechanism.
- **`PREAMBLE_RUN = 4` costs ≈ 0.2 dB** — real but minor.
- **Crossings within each arm's cap** (first point with CP upper < 1 %, all
  `bound_only` at 8-9 dB because the 100-error stop is not reached there):
  baseline ≤ 8 dB (measured-fail at 7.5), `ratio_half` ≤ 7 dB, `floor_only`
  ≤ 7 dB, `prerun_2` ≤ 8 dB, floor-term variants 9 dB — the last only because
  the variant cap (4000) is tighter than the baseline's bracket cap (6000) at
  8 dB on identical streams: the floor variants' 8 dB point is the same
  28/4000 as the baseline's first 4000 packets. Compare arms by the dB column,
  not by these cap-dependent crossing points.

## 3. AGC / 8-bit quantization (AC 3)

Measured, not just derived. The same packets are run through the unmodified
integer receiver with the input quantization refined from the int8 grid to a
1/16 LSB grid (`frac_bits = 4`): the pre-gain float record
(`ChannelOutput.float_iq`, `keep_float=True`) is scaled by the recorded AGC
gain and by 2⁴, `FIR_OUT_BITS` is raised 9→13 so the channel FIR does not
clip the finer grid, and the delay-and-multiply discriminator is unaffected
by scale — it is a CORDIC *angle*, so every downstream threshold keeps its
absolute meaning. The harness is anchored by asserting that `frac_bits = 0`
reproduces the committed int8 samples and demodulation **bit-exactly**
(per packet, and in the unit tests).

| SNR (dB) | int8 PER | 1/16-LSB PER | errors int8 | errors fine |
|---|---|---|---|---|
| 5 | 0.4367 (100/229) | 0.4464 (100/224) | 91 sync / 9 fcs | 89 sync / 11 fcs |
| 7 | 0.04062 (100/2462) | 0.041374 (100/2417) | 98 / 2 | 98 / 2 |
| 8 | 0.006333 (38/6000, bound) | 0.007 (28/4000, bound) | 38 / 0 | 28 / 0 |

Refining the quantization **does not improve PER** — differences at 5/7 dB are
within run-to-run noise of the paired stream, and the 8 dB error count is
unchanged (28 in the shared first 4000 packets). Equivalent delta ≈ 0.0 dB
(at 7 dB: +0.02 dB, i.e. noise). **Clipping is zero** in every point recorded
here (`clipped_samples = 0`, including the 20000-packet 9 dB point), so the
AGC's 1.5 dB-step gain never saturates int8 at these SNRs. The 8-bit input
pipeline is measurably not part of this gap — hypothesis 3 of the issue is
refuted by measurement, matching the issue's derived ~35 dB margin.

## 4. Recommendation (AC 5)

**(a), with a bounded constant**: the evidence names the accept **ratio**
(`ACCEPT_NUM/ACCEPT_DEN_SHIFT = 3/2` in `oqpsk_rx._accept`) as the dominant
recoverable mechanism — ≈ 3.1 dB of the (2.5, 3] dB shortfall at 7 dB,
recoverable by relaxing it to 1 (`ACCEPT_NUM=1, ACCEPT_DEN_SHIFT=1`, i.e.
`corr ≥ mag/2`, 75 % weighted agreement), which leaves the 8-9 dB points
unregressed within caps (0/4000 at 8 dB, 2/4000 at 9 dB — the baseline's own
values). The absolute floor (`MIN_AMPLITUDE`) provably never binds in 5-9 dB
and can stay as is; `PREAMBLE_RUN` is worth ≈ 0.2 dB and is not the lever.

Filing that change is a **receiver change, not a model-only edit**: the
identical ratio lives in RTL (`rtl/oqpsk/oqpsk_rx_corr.v:159`,
`cb4 >= mag3` over `27'sd126976`/`cb_x`), so it carries the golden-trace
regeneration and the bit-exact cocotb replay with it, and it must be
accompanied by a false-acquisition check (the `floor_only` 9 dB regression
above is the cautionary case; the moderate relaxation showed none within
caps, but the follow-up must re-verify the acquisition search, not just the
constant).

**What the fix does not buy**: with the ratio relaxed, the 5 dB point is
PER 0.126 (upper 0.151) — the 5 dB *target* ceiling is still missed by an
amount the named acquisition mechanisms do not cover. After the ≈ 3 dB
recovery, the remainder is plausibly the architectural cost of
non-coherent chip-differential detection (decision 0003's expected penalty),
which is the precondition evidence for the spec conversation — question 2 of
the issue — but does not trigger it by itself: under the ratified amendment
rule (decision 0008, open item 1) the ceilings may be tightened or confirmed,
never loosened, so the 5 dB row stands as a miss either way.

## Scope of this record

This is an error-budget record, not a row verdict and not a receiver change:
`sim/model/oqpsk_rx.py`, `rtl/oqpsk/*` and `spec/` are unchanged by the PR
that commits it (`make test-oqpsk` and `make model-test` pass unmodified).
The committed `per.json` evidence is untouched (append-only). The LE 1M
zero-offset anomaly is issue #133; the one shared-code link —
`oqpsk_rx.demodulate` calls `le1m_rx.discriminate` — was kept in view but no
LE 1M number appears here.
