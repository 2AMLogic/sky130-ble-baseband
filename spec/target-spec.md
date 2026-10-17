# Target specification

Status: **DRAFT — pre-ratification.** Ratification is sibling issue #9; until
then nothing here is a ratified requirement and no row is a measured result.
Siblings #7 (front-end tables, TX interface, turnaround), #8 (hardware/software
split, host interface) and #9 (timing/area/corners, bit-exactness, ratification)
add sections to this file; they do not add parallel spec files.

## Rules for this file

- Governing-specification references are **section/clause numbers only**; no
  specification text or figures are copied here.
- **Every citation below is marked `unverified`**: it was written from memory
  and has not been checked against the specification. A row's number is
  engineering intent until its citation is checked (tracked for #9).
- This block implements the LE 1M physical layer as described in the Bluetooth
  Core Specification, and an IEEE 802.15.4 2.4 GHz O-QPSK baseband. Nothing here
  claims qualification, certification or standards conformance.
- Error-rate rows are **simulated** results to be produced in `sim/`, on the
  channel model named in the row. A number in a "Target" column is a ceiling the
  simulation must meet; it is not a result.
- Digital only. RF front end, ADC, DAC and synthesizer are out of scope; the
  digital interface to them is sibling #7.

Abbreviations: **CM-A** = channel model "baseline" and **CM-B** = baseline plus
optional impairments, both defined in [Channel model](#channel-model) and
decision record [0002](decisions/0002-channel-model.md).

## Parameter table

Governing-spec shorthand: **BCS** = Bluetooth Core Specification, Vol 6
(Low Energy Controller); **154** = IEEE 802.15.4 (revision to be pinned by #9;
2015 numbering assumed below). All citations `unverified`.

### PHY set

| Parameter | Target | Fallback | Stretch | Verification method | Governing section | Simulated? / channel model |
|---|---|---|---|---|---|---|
| LE 1M GFSK PHY (1 Msym/s) | in | in (sole PHY) | — | RTL vs reference bit-exact on shared stimulus; error-rate rows below | BCS Vol 6 Part A §3 (modulation), Part B §2 (packet format) — unverified | n/a (structural) |
| 802.15.4 2.4 GHz O-QPSK PHY (2 Mchip/s) | in | out (LE 1M only) | — | as above | 154 Clause 12 — unverified | n/a (structural) |
| LE 2M PHY | out | out | in, only after target closes | reference-model sweep, separate record | BCS Vol 6 Part A §3 — unverified | n/a |
| LE coded PHY | out | out | in, only after target closes | reference-model sweep, separate record | BCS Vol 6 Part A §3 — unverified | n/a |

Stretch PHYs must not shape the datapath, clocking or interface of the target
PHYs (decision [0001](decisions/0001-phy-set.md)).

### Demodulator performance

| Parameter | Target | Fallback | Stretch | Verification method | Governing section | Simulated? / channel model |
|---|---|---|---|---|---|---|
| LE 1M BER at ratified Eb/N0 | BER ≤ 1e-3 at Eb/N0 ≤ 16 dB (**provisional ceiling**, see note 1) | BER ≤ 1e-3 at Eb/N0 ≤ 18 dB | BER ≤ 1e-3 at Eb/N0 ≤ 14 dB | `sim/` BER sweep, ≥100 errors per point, 95 % interval reported; RTL bit-exact against the swept model | BCS Vol 6 Part A §4 (receiver characteristics) — unverified; the 1e-3 criterion is this repo's engineering choice, not a citation | **Simulated**, CM-A with LE-1M frequency offset/drift settings |
| 802.15.4 PER (20-octet PSDU) at ratified SNR | PER < 1 % at SNR ≤ 5 dB in 2 MHz noise bandwidth (**provisional ceiling**, see note 1) | PER < 1 % at SNR ≤ 7 dB | PER < 1 % at SNR ≤ 3 dB | `sim/` PER sweep, ≥100 packet errors per point, 95 % interval reported; RTL bit-exact | 154 Clause 10 (receiver sensitivity criterion) / Clause 12 — unverified | **Simulated**, CM-A with 802.15.4 offset/drift settings |
| LE 1M BER under optional impairments | informational: report Eb/N0 penalty vs CM-A, no pass/fail | — | pass/fail threshold set by a later record | `sim/` sweep | n/a | **Simulated**, CM-B |
| 802.15.4 PER under optional impairments | informational: report SNR penalty vs CM-A, no pass/fail | — | pass/fail threshold set by a later record | `sim/` sweep | n/a | **Simulated**, CM-B |

Note 1. The two ceilings are placeholders chosen so the architecture decision
([0003](decisions/0003-demod-architecture.md)) has a bar to be judged against.
No reference model exists yet; no gap, margin or achievability is claimed.
Ratification (#9) replaces each with a value justified by a `sim/` result, and
may only tighten or confirm a ceiling in the light of the simulated
non-coherent baseline, never relax it to make a result pass.

### Carrier-frequency offset and drift tolerance

Offsets are *received-signal* carrier offset relative to the receiver's nominal
channel centre, inclusive of both ends' crystal error. The error-rate rows above
must hold across the whole range, not only at zero offset.

| Parameter | Target | Fallback | Stretch | Verification method | Governing section | Simulated? / channel model |
|---|---|---|---|---|---|---|
| LE 1M carrier-frequency offset | ±150 kHz | ±100 kHz | ±250 kHz | BER sweep over uniform offset grid incl. both extremes | BCS Vol 6 Part A §3 (radio frequency tolerance) — unverified | **Simulated**, CM-A |
| LE 1M carrier drift within a packet | 50 kHz total over the packet, 20 kHz per 50 µs (peak rate) | 50 kHz total, 10 kHz per 50 µs | — | BER sweep with linear and worst-case stepped drift profiles | BCS Vol 6 Part A §3 (radio frequency tolerance) — unverified | **Simulated**, CM-A |
| 802.15.4 carrier-frequency offset | ±80 ppm relative (≈ ±196 kHz at 2.45 GHz; two ±40 ppm ends) | ±40 ppm relative (≈ ±98 kHz) | — | PER sweep over uniform offset grid incl. both extremes | 154 Clause 10 / Clause 12 (frequency tolerance) — unverified | **Simulated**, CM-A |
| 802.15.4 carrier drift within a packet | none required beyond the offset (static offset per packet) | — | linear drift profile by later record | PER sweep | n/a | **Simulated**, CM-A |

### Symbol-timing and sample-clock drift tolerance

Sample-clock offset is relative between transmitter symbol clock and receiver
sample clock. Arithmetic (not simulated): LE 1M max on-air packet is 2120 µs,
so ±100 ppm relative drifts ≈ 0.21 symbol across it; 802.15.4 max packet is
133 octets = 4256 µs, so ±80 ppm drifts ≈ 0.34 µs ≈ 0.68 chip. The 802.15.4
receiver therefore **must** track timing within the packet; a fixed
preamble-time timing estimate is not enough.

| Parameter | Target | Fallback | Stretch | Verification method | Governing section | Simulated? / channel model |
|---|---|---|---|---|---|---|
| LE 1M relative symbol-clock offset | ±100 ppm (two ±50 ppm ends) | ±50 ppm | — | BER sweep over offset grid at max packet length | BCS Vol 6 Part A §3 (symbol timing) — unverified | **Simulated**, CM-A |
| 802.15.4 relative chip-clock offset | ±80 ppm (two ±40 ppm ends) | ±40 ppm | — | PER sweep at max PSDU length (127 octets) | 154 Clause 10 / Clause 12 (chip rate tolerance) — unverified | **Simulated**, CM-A |
| Initial timing phase | uniform over one symbol (LE) / one chip (154), re-drawn per packet | — | — | covered by every sweep point | n/a | **Simulated**, CM-A |

### Modelling choices for the above (non-normative)

| Parameter | Value | Verification method | Governing section | Simulated? |
|---|---|---|---|---|
| RX input sample rate / width | 8 Msps complex, ≤ 8-bit (README draft; interface detail is #7) | quantization stage in CM-A | none applies (interface choice) | **Simulated**, CM-A |

## Channel model

Normative definition for every error-rate row. Rationale and alternatives:
[0002](decisions/0002-channel-model.md). `sim/` implements this section; any
`sim/` deviation is a bug in `sim/` or a superseding record, not a silent edit.

### Baseline (CM-A) — in every ratified sweep

Signal path, in order:

1. **Transmit waveform** at the reference model's internal rate, complex baseband, unit mean power over the packet.
2. **Carrier-frequency offset** `f_off` (Hz), drawn per packet uniformly from ±the row's offset range; the grid also pins both extremes and zero.
3. **Carrier drift** `f_drift(t)` (Hz), added to `f_off`, shape per the row (none, linear ramp, stepped worst case).
4. **Relative sample-clock offset** `ε` (ppm), drawn per packet uniformly from ±the row's range, applied as resampling; **initial timing phase** drawn per packet uniformly over one symbol (LE) or one chip (154).
5. **Initial carrier phase** uniform over [0, 2π), per packet.
6. **AWGN**: complex white Gaussian noise, variance set from the swept quantity, defined as follows.
   - LE: `Eb/N0` in dB, with `Eb` the mean energy per information bit (1 bit per symbol) and `N0` the one-sided noise power spectral density; the noise is generated over the full simulation bandwidth and the receiver's own channel filter does the band-limiting (so the filter's noise bandwidth counts against the receiver).
   - 802.15.4: `SNR` in dB as signal power over noise power **in a 2 MHz noise bandwidth**, signal power the mean over the packet; the same rule of full-bandwidth noise and receiver-side filtering applies.
7. **Quantization** to the RX input width (≤ 8-bit I and Q), with gain set by a fixed documented AGC rule (not by an oracle on the noiseless signal); clipping counted, not hidden.

Not in CM-A: multipath, phase noise, adjacent-channel and co-channel
interference, DC offset, I/Q imbalance, ADC clock jitter.

### Seeds policy

- One PRNG family fixed in `sim/` (PCG64 via NumPy) — changing it is a superseding record.
- Seed for a point = a stable hash of (row id, impairment settings, sweep-point index, run index). No wall-clock or OS-entropy seeds anywhere in a ratified sweep.
- Every reported result records: seed, PRNG family and version, `sim/` git SHA, row id, channel-model id (CM-A / CM-B) and every parameter above.
- The RTL bit-exactness stimulus (#9) is generated from the same seeds, so shared stimulus is reproducible.

### Statistics

- Each point runs until ≥ 100 errors (bit errors for LE, packet errors for 802.15.4) or a stated packet cap; points that hit the cap are reported as upper bounds, not as measurements.
- Report a 95 % Clopper–Pearson interval per point; a row passes only if the **upper** interval bound meets the target.

### Optional impairments (CM-B) — reported, not in the ratified pass/fail

CM-B = CM-A plus any of: two-ray static multipath (delay spread ≤ 1 symbol /
≤ 1 chip, parameters recorded), transmitter/receiver phase noise as a one-pole
Wiener process (linewidth recorded), narrowband interferer. Each is added one at
a time and reported as a *penalty* against CM-A. Rationale for keeping them out
of pass/fail: [0002](decisions/0002-channel-model.md).

## Demodulation architecture (summary)

LE 1M demodulation is **non-coherent by provisional default**; 802.15.4
despreading is likewise non-coherent. The decision criteria and the exact
`sim/` result that supersedes this are in
[0003](decisions/0003-demod-architecture.md).

## Decision records

| Id | Subject |
|---|---|
| [0001](decisions/0001-phy-set.md) | PHY set |
| [0002](decisions/0002-channel-model.md) | Channel model |
| [0003](decisions/0003-demod-architecture.md) | LE demodulator architecture |
