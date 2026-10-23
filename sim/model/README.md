# LE 1M TX reference model

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

## Bit pipeline

1. Preamble: one octet, `0xAA` if access-address bit 0 is 0, else `0x55`.
2. Access address, 4 octets, least significant bit of each octet first.
3. CRC-24 over the unwhitened PDU (2 to 257 octets; the model also accepts
   an empty PDU). Register is 24 bits, preset to the CRC init with spec
   position 0 as the init LSB, feedback taps at positions 0,1,3,4,6,9,10;
   sent position 23 first.
4. Whitening over PDU + CRC, `x^7+x^4+1`, 7-bit register preset to
   `0x40 | channel` (bit 6 is spec position 0), output is register bit 0,
   feedback XOR `0x44`. Channel index 0..39.

## Gaussian shaping (BT = 0.5)

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

## tx_active and sample index

Sample index is the count of `tx_valid` strobes since the start (0007). The
word at index 0 is the first preamble sample (zero before the filter fills).
`txact` rises at index 0; the front-end interface says it is high from the
first word to the last word plus one sample, so the trace records the falling
edge at index `len(words) + 1` (first index at which it is 0). That reading
of the interface text is this model's interpretation; amend here if the RTL
timing item decides otherwise.

## Known-answer status

No published sample vector was available when the tests were written. The CRC
and whitening known answers in `sim/tests` are pinned from independent
bit-level implementations of the spec's register description and are marked
**unverified** against a spec-published vector.

## Tests

`make model-test` runs `sim/tests` and then a negative control
(`CRC_NEGATIVE=1` flips the CRC init handed to the model; the CRC
known-answer test must fail, and the target inverts that exit status).
