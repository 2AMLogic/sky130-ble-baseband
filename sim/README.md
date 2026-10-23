# sim

Reference models and their tests. See the repo README for scope.

- [`model/`](model/README.md): `le1m_tx.py`, the integer LE 1M TX reference
  model (PDU to whitened, CRC'd, Gaussian-shaped `tx_dev` words), and
  `traces.py` for the golden-trace format ([`trace_format.md`](model/trace_format.md)).
  `model/golden/tx_adv_ch37.trace` is a generated golden trace.
- `tests/`: pytest suite for the above; run with `make model-test`.
