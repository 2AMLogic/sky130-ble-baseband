# Trace format

Implements the trace format of decision
[0007](../../spec/decisions/0007-bit-exactness.md); reader and writer are in
`traces.py` and are shared by the TX and RX models and the cocotb replay.

- UTF-8 text, LF terminated, one record per line: `<sample_index> <field> <value>`
- `sample_index`: decimal, count of `tx_valid` (TX) or `rx_valid` (RX) strobes
  since the start. Non-decreasing down the file.
- `field`: one of `bit octet sync tbound cfo crc rssi gain txdev txact desc irq`.
- `value`: hexadecimal digits, no prefix, unsigned. Signed words are two's
  complement at the field width (`txdev` is 8 bits: `-32` is `e0`).
- No comments, no blank lines. Any line that does not parse, an unknown field,
  a decreasing index, or a missing final newline raises `TraceError`; nothing is
  skipped.

TX fields written by `le1m_tx.py`: `txdev` (every word) and `txact` (value 1
at the first index, value 0 at the first index where it is low).
Rows within one index keep writer order; compare by (index, field).

TX fields written by `oqpsk_tx.py` are the same two (`txdev`, `txact`). RX
fields written by `oqpsk_rx.py`: `gain`, `sync`, `octet`, `tbound`, `crc`,
`rssi` (README "IEEE 802.15.4 2.4 GHz O-QPSK models").
