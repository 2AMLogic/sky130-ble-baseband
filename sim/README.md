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
| `tests/` | pytest controls |

## Commands

```
make sim-test                              # pytest controls (about 10 s)
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
split it with `--only`.

**Reading `ber.json`.** Each point carries seed, errors, bits, 95 % Clopper-Pearson
bounds, clip count, `stopped_by` and `bound_only`, and the label "simulated,
CM-A". A `bound_only` point hit its packet cap and is an upper bound, not a
measurement. `rows` reports, per row at 16 dB, the worst upper bound and whether it
is ≤ 1e-3; that is a report for the evidence record, not a claim that the row is met.
`negative_control` and `out_of_spec` points are excluded from `rows`.

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
- The TX reference model (`le1m_tx.py`) is a separate issue; this sweep uses its
  own float GFSK source, which is a channel-side stimulus, not a swept model.
