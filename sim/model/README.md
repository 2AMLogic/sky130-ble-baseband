# sim/model

Integer reference models swept for error rate and compared with the RTL
(decision [0007](../../spec/decisions/0007-bit-exactness.md)). A floating-point
model may exist for exploration; none carries an error-rate claim.

## LE 1M receiver (`le1m_rx.py`)

Non-coherent by provisional default ([0003](../../spec/decisions/0003-demod-architecture.md)).
Input is the RX stimulus of 0007: `int8 I`, `int8 Q`, flags (bit 0 `rx_sat`,
bit 1 `gain_reply`), gain index, one record per sample at 8 Msps. All data-path
arithmetic is integer (numpy `int64` carrying values of the widths below). Core
Specification references: Vol 6 Part A (modulation), Part B 2.1, 2.1.2, 2.3, 3.1.1.

Sample index in every trace record is the index of the input sample (the
`rx_valid` strobe count). Groups of records at the same index are ordered by the
sort in `demodulate` (stable on index).

### Width, rounding and saturation table

| Stage | Input | Operation | Output width | Rounding / saturation |
|---|---|---|---|---|
| Channel filter | I, Q: signed 8 | 11-tap symmetric FIR `1 4 9 16 22 24 22 16 9 4 1`, sum 128, causal | signed 9 | `(acc + 64) >> 7` (round half up); saturate to [-256, 255] |
| Discriminator products | I, Q: signed 9 (current, previous) | `re = I·I' + Q·Q'`, `im = Q·I' − I·Q'` | signed 19 (exact) | none; sample 0 has no predecessor and outputs 0 |
| CORDIC angle | `re`, `im`: signed 19 | vectoring mode, 12 iterations, `x<0` folded by negation plus half a turn | signed 16, full turn = 2^16 | arithmetic shifts truncate toward −∞; atan table `round(atan(2^-i)/2π · 2^16)`; all-zero input forced to 0; result wraps modulo 2^16 |
| Symbol integrator | `f`: signed 16 | `s[n] = f[n-7] + … + f[n]` (8 samples) | signed 19 (exact) | none. Nominal ±250 kHz is ±2048 per sample, ±16384 per symbol |
| Sync correlator | `s`: signed 19 | 40 symbol-spaced taps of `s` against preamble + access address (±1); offset `D` = mean of the 8 preamble taps | `corr` signed 25, `mag` unsigned 25 | `D = sum >> 3` (floor). Accept when `corr ≥ 4096·40` and `8·corr ≥ 7·mag`; take the largest `corr` in the next 8 samples |
| Amplitude `A`, offset `D` (refined) | `corr`, tap sum | `A = (corr·1639 + 2^15) >> 16` (≈ corr/40); `D = (Σv − A·Σp)/40` as `(x·1639 + 2^15) >> 16` on the magnitude, sign restored | signed 19 | round half up on magnitude; `A ≥ 1` |
| Decision | `s − D` | bit = `(s[t] − D) > 0` (1 = positive frequency) | 1 | — |
| Offset tracker | decision error `v − (±A)` | `D += err >> 6` | signed 19 | arithmetic shift (floor) |
| Timing loop | `s` at `t±2` | `e = |s[t+2]−D| − |s[t−2]−D|`; `tacc += (e·⌊2^16/A⌋) >> 12`; step `t` by ±1 when `|tacc| ≥ 48`, subtracting 48 | `tacc` signed 12 | arithmetic shift (floor) |
| Length / CRC | decoded bits | length = header octet 2 (8 bits, LSB first); CRC-24, init 0x555555, poly 0x00065B, register bit 23 sent first | 24 | exact |
| RSSI | filtered I, Q | alpha-max-beta-min magnitude `max + (min >> 1)`, mean over the 320 samples before sync, `(Σ·205 + 2^15) >> 16` | unsigned 9 | round half up |

No data whitening is modelled: the BER stimulus payload is random, and whitening
is a bijection (see `sim/channel/packet.py`).

### Trace taps emitted (0007 table, RX rows)

| Field | Index | Value |
|---|---|---|
| `gain` | each sample with the `gain_reply` flag | gain index from the stimulus |
| `sync` | last sample of the access-address window | 1; absent when no sync (a missed detect) |
| `cfo` | at sync, then every 32 symbols | `D`, signed, 24-bit two's complement |
| `bit` | sample of each demodulated PDU/CRC bit | the bit |
| `tbound` | first 16 and last 16 symbols of the packet, and every timing step | symbol number (0 = first PDU bit) |
| `crc` | sample of the last CRC bit | 1 pass, 0 fail |
| `rssi` | same sample | as above |

`octet`, `txdev`, `txact`, `desc`, `irq` are not produced by this model (802.15.4 is
`oqpsk_rx.py` below; TX is `le1m_tx.py`; the host register map is another issue).

### Behaviour that matters for the statistics

- One packet per capture. Acquisition is streaming (threshold plus local
  maximum), not a global search, so it can false-alarm in the noise lead-in; that
  costs the packet and is counted.
- The receiver demodulates as many bits as the decoded length field claims. A
  missed packet counts every PDU and CRC bit as an error in the sweep; a corrupted
  length counts the missing bits. Both are conservative and cluster errors in
  one packet, which the 100-error stop rule does not account for.
- Constants (thresholds, shifts, filter taps) are first-cut values, not tuned
  for performance. Changing one changes the swept model and the golden traces.

## LE 1M TX reference model (`le1m_tx.py`)

`le1m_tx.py` is the integer-arithmetic reference for the LE 1M transmit path
(decision [0007](../../spec/decisions/0007-bit-exactness.md) section 1): PDU
octets in, `tx_dev` words at 8 Msps out
([0005](../../spec/decisions/0005-tx-modulation-output.md)). It follows the
Core Specification, Vol 6 Part B, for packet format (section 2), CRC (3.1.1)
and whitening (3.2). No floating point is used by the model.

```
python3 sim/model/le1m_tx.py --pdu <hex> --channel 37 --out sim/model/golden/tx_adv_ch37.trace
```

Options `--access-address` and `--crc-init` (hex) default to the advertising
values `8E89BED6` and `555555`. The golden file uses PDU
`4209010203040506020106`, channel 37.

### Bit pipeline

1. Preamble: one octet, `0xAA` if access-address bit 0 is 0, else `0x55`.
2. Access address, 4 octets, least significant bit of each octet first.
3. CRC-24 over the unwhitened PDU (2 to 257 octets; the model also accepts
   an empty PDU). Register is 24 bits, preset to the CRC init with spec
   position 0 as the init LSB, feedback taps at positions 0,1,3,4,6,9,10;
   sent position 23 first.
4. Whitening over PDU + CRC, `x^7+x^4+1`, 7-bit register preset to
   `0x40 | channel` (bit 6 is spec position 0), output is register bit 0,
   feedback XOR `0x44`. Channel index 0..39.

### Gaussian shaping (BT = 0.5)

| Item | Value |
|---|---|
| Input | NRZ symbol, bit 1 = +1, bit 0 = -1, held 8 samples |
| Taps | 33 (4 symbols), symmetric, centre tap 16, unsigned 15-bit, table `GAUSS_TAPS` |
| Tap sum | exactly 2^15 = 32 x 2^10 |
| Accumulator | signed, products `tap x (+/-1)`, worst case magnitude 2^15 (17 bits signed) |
| Rounding | `(acc + 2^9) >> 10`, arithmetic shift (round half toward +infinity) |
| Saturation | clamp to int8 [-128, 127] (never reached by this filter; stated for the RTL) |
| Initial state | zero; the filter drains, output length is `8 x bits + 32` words |

Taps were generated once offline as the sampled Gaussian
`exp(-n^2 / (2 s^2))`, `s = 8 sqrt(ln 2) / (2 pi BT)` samples, scaled to sum
2^15 with each tap rounded to nearest (rounded sum was already exact). A test
checks the table against that definition to within 1 count. A settled run
of one bit gives exactly +/-32 LSB (7.8125 kHz x 32 = 250 kHz, decision 0005).

### tx_active and sample index

Sample index is the count of `tx_valid` strobes since the start (0007). The
word at index 0 is the first preamble sample (zero before the filter fills).
`txact` rises at index 0; the front-end interface says it is high from the
first word to the last word plus one sample, so the trace records the falling
edge at index `len(words) + 1` (first index at which it is 0). That reading
of the interface text is this model's interpretation; amend here if the RTL
timing item decides otherwise.

### Known-answer status

No published sample vector was available when the tests were written. The CRC
and whitening known answers in `sim/tests` are pinned from independent
bit-level implementations of the spec's register description and are marked
**unverified** against a spec-published vector.

### Tests

`make model-test` runs `sim/tests` and then a negative control
(`CRC_NEGATIVE=1` flips the CRC init handed to the model; the CRC
known-answer test must fail, and the target inverts that exit status).

## IEEE 802.15.4 2.4 GHz O-QPSK models (`oqpsk_tx.py`, `oqpsk_rx.py`)

Integer reference for the 802.15.4 PHY (decision
[0007](../../spec/decisions/0007-bit-exactness.md)). Clause numbers of IEEE
802.15.4 (2.4 GHz O-QPSK PHY: PPDU format, symbol-to-chip mapping, O-QPSK
modulation; MAC frame check sequence) are **unverified**, as in
[target-spec](../../spec/target-spec.md); this README names the clauses by title
only and copies no text or table. The chip table is `oqpsk_tx.CHIP_TABLE`
(symbol 0 listed, symbols 1..7 by 4-chip rotation, 8..15 by inverting odd chips;
a test pins that structure, not the spec's printed table).

**Sample rate.** 8 Msps (4 samples per chip), the target operating point of
[frontend-interface](../../spec/frontend-interface.md) §1, like `le1m_*`. The
4 Msps fallback (2 samples per chip) is not modelled in this version.

```
python3 sim/model/oqpsk_tx.py --psdu <hex> [--append-fcs] --out sim/model/golden/tx_154_psdu20.trace
```

The golden TX trace is the 18-octet payload `01..12` plus FCS (20-octet PSDU).
`golden/rx_154_loopback_psdu20.trace` is the RX model's trace for the noiseless
loopback of that packet (ideal FM modulator as test stand-in for the front end,
amplitude 100, 37 idle samples before the packet).

### TX

PSDU (with FCS; `with_fcs` appends it) -> PPDU: 4 preamble octets `00`, SFD
`A7`, PHR (7-bit length, reserved bit 0), PSDU. Octets go out low nibble first
as 4-bit symbols, each spread to 32 chips. FCS is the ITU-T CRC-16, init 0, bits
LSB first, sent little-endian; pinned by the published CRC-16/KERMIT check value
for `123456789`.

**Half-sine shaping.** Even chips drive I, odd chips drive Q delayed by one
chip, half-sine pulses two chips wide. This is MSK, so the shaped signal has
constant envelope and a frequency that is constant within each chip interval.
The model therefore emits the frequency directly: in chip interval `k` the word
is `64 * s_k` (+/-500 kHz at 7.8125 kHz per LSB, decision 0005), with
`s_k = -c_k c_{k-1}` for even `k` and `+c_k c_{k-1}` for odd `k` (chips as +/-1,
chip 1 = +1). The first interval (I pulse rising alone) and the interval after
the last chip (Q pulse falling alone) have no phase change and emit 0. This
closes the "open check" of decision 0005: a test builds the floating-point
half-sine waveform as an independent oracle and compares the sign of the phase
change over every chip interval for all 16 symbols. Floating point is used only
in that test.

| Item | Value |
|---|---|
| Output | `tx_dev` signed 8, `{-64, 0, +64}`, 4 words per chip interval |
| Word count | `4 * (chips + 1)`, chips = `32 * 2 * (6 + PSDU octets)` |
| Multiplies / rounding / saturation | none; sign select only. Saturation to [-128, 127] is never reached |
| `txact` | rises at index 0, falls at index `len(words) + 1` (same reading as `le1m_tx`) |

### RX

Non-coherent by provisional default ([0003](../../spec/decisions/0003-demod-architecture.md)):
the choice of front end is **not final** and has not been compared with a
coherent one. The despreader works on products of adjacent chips, which the
frequency discriminator observes without a carrier phase reference. Input is the
0007 RX stimulus (`int8 I`, `int8 Q`, flags, gain), not chips.

| Stage | Input | Operation | Output width | Rounding / saturation |
|---|---|---|---|---|
| Channel filter | I, Q: signed 8 | 5-tap symmetric FIR `1 4 6 4 1`, sum 16, causal | signed 9 | `(acc + 8) >> 4`; saturate to [-256, 255] |
| Discriminator, CORDIC | as `le1m_rx` (shared functions) | angle of `z[n] conj(z[n-1])` | signed 16, turn = 2^16 | as the LE table; nominal +/-500 kHz is +/-4096 per sample |
| Chip integrator | `f`: signed 16 | `g[n] = f[n-3] + ... + f[n]` | signed 18 (exact) | none. Nominal +/-16384 per chip |
| Symbol correlators | 31 chip-spaced `g` taps (transitions 1..31) | 16 correlators `W[m,j] = s_{j+1}` of symbol `m`, `corr = W g` | signed 23 (exact); `mag = sum|g|` unsigned 23 | none |
| Accept | `corr_best`, `mag` | `corr >= 4096 * 31` and `4 * corr >= 3 * mag` | 1 | — |
| Preamble run | accepted symbol 0 | 4 symbol-0 matches 128 samples apart arm the search; best of the next 4 indices | | |
| SFD | accepted symbols | symbols 7 then 10 (SFD `A7`) within 16 further zero symbols | | any other symbol: no sync, search resumes after the failure point |
| Symbol decision | `corr[:, t]` | argmax over 16 (lowest index on ties) | 4 bits | |
| Timing tracking | `corr[m, t-1..t+1]` | after each symbol, move `t` by +/-1 if that neighbour strictly beats the decided symbol's value at `t` | | |
| PHR / PSDU | symbols | length = PHR bits 0..6; `2 * length` symbols follow | | |
| FCS | PSDU octets | ITU-T CRC-16 of all but the last two octets equals the last two, little-endian | 1 | PSDU shorter than 2 octets: always 0 |
| RSSI | filtered I, Q | as the LE receiver (`le1m_rx._rssi`, 320 samples before sync) | unsigned 9 | as LE |

**Trace taps.** `gain` (as LE), `sync` (last sample of the SFD window; absent on
a miss), `octet` (PSDU and FCS octets, sample of the octet's last chip), `tbound`
(chip boundary sample, value = chip number with chip 0 the first PHR chip, for
the first and last 16 chips and at every timing step), `crc` (1 FCS pass, 0 fail
or too short, at the last chip) and `rssi`. `cfo` is not produced: this version
makes no frequency-offset estimate (`D` is taken as 0), so a carrier offset
shifts every `g` by a constant and is not tolerated beyond the correlator
margin. Offset, noise and drift handling are issues #43 and #56.

**Not established.** No error-rate or tolerance claim: only noiseless loopback
is tested. The timing tracker and thresholds are first-cut and untested under
sample-clock drift. A truncated capture yields the octets received and no `crc`
record.

Tests: `sim/tests/test_oqpsk_tx.py`, `sim/tests/test_oqpsk_rx.py` (loopback at
PSDU 3, 20 and 127 octets plus a 1-octet PSDU, 8 timing phases, bad FCS, SFD
miss, truncation, golden-trace regeneration).
