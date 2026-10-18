# 0007 — Bit-exactness between `sim/` and RTL: shared stimulus and golden traces

- Status: accepted (ratified with the spec, see [0008](0008-ratification-and-amendment.md))
- Date: 2026-10-18
- Parent: #2; issue #9

## Context

Error rates are computed in `sim/` under the channel model of
[0002](0002-channel-model.md). They are a claim about this block only if the RTL
produces exactly what the swept model produces. The open question in the parent
was whether to enforce that with shared stimulus files or with cocotb
co-simulation against the Python model.

A second question hides inside it: a receiver written in floating point and an
RTL in fixed point are never bit-exact, so "the reference receiver" has to be
the fixed-point one.

## Decision

1. **There is one reference receiver, and it is integer arithmetic.** The model
   in `sim/` that is swept for BER and PER is the same model the RTL is compared
   with: fixed-point, with every register width, rounding and saturation rule
   written down. A floating-point model may exist for exploration; it carries no
   error-rate claim and no row in the target spec cites it.
2. **Enforcement is shared stimulus plus golden traces, replayed by cocotb.**
   `sim/` writes stimulus files and the model's trace files. A cocotb testbench
   under Icarus reads the stimulus, drives the RTL, writes the RTL's trace in the
   same format, and compares. The Python model is not run inside the simulator.
3. **Equality is exact.** No tolerance, no "within one LSB". The first mismatch
   fails the test and is reported with the file, record number and field.

## What is compared

Comparison is by **sample index, not by clock cycle.** The index is the count of
`rx_valid` strobes (RX) or of `tx_valid` strobes (TX) since the start of the
file, which is the only time base the model has. Cycle-level latency is a
separate requirement, measured by a different test
([timing-and-area §3](../timing-and-area.md)), so the two cannot hide each other.

| Direction | Signal / tap | Compared at | Notes |
|---|---|---|---|
| RX | recovered bit (LE) or decoded octet (802.15.4) stream | every output, with the sample index of the strobe that produced it | the data path result |
| RX | sync event: sample index at which the access address (LE) or SFD (802.15.4) is declared found | every packet | includes a missed-detect (no event) |
| RX | symbol/chip boundary sample index | every symbol/chip for the first and last 16 of each packet, and at every timing correction | timing-recovery state, not every symbol, to bound file size |
| RX | frequency-estimate word and its update index | every update | the register the model and RTL both define in the model spec |
| RX | CRC / FCS pass flag and the sample index where it is final | every packet | |
| RX | `rssi` and `rssi_valid` index | every packet | |
| RX | `agc_gain` and `agc_gain_we` index | every write | closes the AGC loop with the stimulus: see below |
| TX | `tx_dev` word | every `tx_valid` strobe | including the preamble, whitening and CRC fields |
| TX | `tx_active` rising and falling sample index | every packet | |
| Both | host-visible status: packet descriptor fields, interrupt-cause bits at packet end | every packet | the register map is not frozen yet; names follow `host-interface.md` |

Not compared: internal pipeline registers other than the taps above, signals
whose only meaning is to the front end's analog side, and clock-cycle timing
(see §3 of the timing file). Adding a tap is an additive amendment; removing
one is substantive.

**AGC and closed loops.** The stimulus file is a fixed sample stream. A real
front end would change the sample stream in reply to `agc_gain`; a file cannot.
Therefore stimulus carries the front end's reply as data: a second column
`gain_reply` states at which sample index each requested gain takes effect, per
the model's `agc_settled` rule, and the compared `agc_gain` writes must equal
the model's writes while the stimulus is generated under that same rule. A
stimulus whose gain changes depend on RTL output that differs from the model is
simply a mismatch at the first diverging write.

## File formats

Plain, versionless-by-name files so that a testbench can be written without
asking:

- **Manifest**, `<name>.json`: `format` = 1; `kind` (`rx` or `tx`); `phy`
  (`le1m` or `ieee154`); `rate_msps` (8 or 4); `channel_model` (`CM-A` or
  `CM-B`) and every parameter of [target-spec "Seeds policy"](../target-spec.md#channel-model);
  `sim_git_sha`; `prng` family and version; `seed`; `samples`; list of expected
  packets (offset, payload octets) for the traces' packet count; sha256 of each
  data file.
- **RX stimulus**, `<name>.rx.bin`: little-endian, one record per `rx_valid`
  strobe: `int8 I`, `int8 Q`, `uint8 flags` (bit 0 = `rx_sat`, bit 1 =
  `gain_reply` strobe applied before this sample, bits 2–7 zero), `uint8 gain`
  (the gain index in force, 0–63). 4 octets per record.
- **TX stimulus**, `<name>.tx.json`: the PDU/PSDU octets to send, the access
  address / CRC init / channel index (LE) or none (802.15.4), and the start
  index, as hex strings.
- **Trace**, `<name>.<model|rtl>.trace`: UTF-8 text, one record per line,
  `<sample_index> <field> <value>` with `<value>` hexadecimal; fields are the
  taps in the table above (`bit`, `octet`, `sync`, `tbound`, `cfo`, `crc`,
  `rssi`, `gain`, `txdev`, `txact`, `desc`, `irq`). Text so that a mismatch is
  diffable by eye. A trace line that cannot be parsed is a failure, not a skip.

Stimulus files are generated by `sim/` from the seeds policy, so any stimulus
can be regenerated from its manifest. A **committed regression set** (small:
tens of packets per PHY, both rates where the fallback applies, at the extremes
of the offset and drift ranges, a missed-detect, a bad CRC, a saturating
sample) lives under `verification/vectors/`; large sweep stimulus is
regenerated on demand and never committed.

## Alternatives rejected

- **cocotb co-simulation against the live Python model**: ties the verdict to
  Python's speed (a 100-error BER point is millions of samples), makes the
  model a runtime dependency of the test, and leaves nothing to re-run or diff
  when a run fails. Rejected for the primary gate; a short co-simulation smoke
  test may exist as a development aid and is not a claim.
- **Comparing the float model with a tolerance**: a tolerance is exactly the
  slack in which the statistics stop transferring to the hardware.
- **Cycle-accurate compare**: forbids the RTL from pipelining differently
  without changing a statistical result; latency is bounded separately.

## Consequences

- `sim/` must be written in integer arithmetic for the swept receiver, with
  widths in a model spec; this is a requirement on #4's successors, not a new
  tool.
- A BER or PER row is "tied to the RTL" only when the bit-exactness test over
  the committed regression set passes at the RTL commit being claimed; the
  evidence records both commits.
- The Verilog `rx_sat`/gain behaviour of a real front end is not exercised by a
  file beyond the `gain_reply` column; closed-loop behaviour against a real
  front end is out of scope.
