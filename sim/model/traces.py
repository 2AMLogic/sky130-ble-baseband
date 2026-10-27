"""Trace file reader/writer for the golden-trace format of decision 0007.

One record per line: ``<sample_index> <field> <value-hex>``. The reader and
writer are field-agnostic over the 0007 field list so the RX model and the
cocotb replay share them. See trace_format.md.
"""

import re

FIELDS = frozenset(
    "bit octet sync tbound cfo crc rssi gain txdev txact desc irq".split()
)

_LINE = re.compile(r"([0-9]+) ([a-z]+) ([0-9a-fA-F]+)")


class TraceError(ValueError):
    """A trace line (or record) that cannot be parsed; never skipped."""


def _check(index, field, value, where):
    if field not in FIELDS:
        raise TraceError(f"{where}: unknown field {field!r}")
    if not (isinstance(index, int) and index >= 0):
        raise TraceError(f"{where}: bad sample index {index!r}")
    if not (isinstance(value, int) and value >= 0):
        raise TraceError(f"{where}: value must be a non-negative integer, got {value!r}")


def format_record(index, field, value):
    _check(index, field, value, "record")
    return f"{index} {field} {value:x}"


def write_trace(path, records):
    """Write (index, field, value) records; indices must be non-decreasing."""
    last = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for n, (index, field, value) in enumerate(records, 1):
            _check(index, field, value, f"record {n}")
            if index < last:
                raise TraceError(f"record {n}: sample index {index} decreases (was {last})")
            last = index
            f.write(f"{index} {field} {value:x}\n")


def read_trace(path):
    """Return a list of (index, field, value) tuples; any bad line raises."""
    records = []
    last = 0
    with open(path, encoding="utf-8", newline="") as f:
        for n, raw in enumerate(f, 1):
            where = f"{path}:{n}"
            if not raw.endswith("\n"):
                raise TraceError(f"{where}: missing line terminator")
            m = _LINE.fullmatch(raw[:-1])
            if not m:
                raise TraceError(f"{where}: cannot parse {raw[:-1]!r}")
            index, field, value = int(m[1]), m[2], int(m[3], 16)
            _check(index, field, value, where)
            if index < last:
                raise TraceError(f"{where}: sample index {index} decreases (was {last})")
            last = index
            records.append((index, field, value))
    return records


def to_unsigned(value, bits):
    """Two's-complement encode a signed integer for a trace value."""
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if not lo <= value <= hi:
        raise ValueError(f"{value} does not fit in {bits} signed bits")
    return value & ((1 << bits) - 1)


def to_signed(value, bits):
    if not 0 <= value < (1 << bits):
        raise ValueError(f"{value} does not fit in {bits} bits")
    return value - (1 << bits) if value >> (bits - 1) else value


def compare_by_index(name, rtl_records, model_records, *, ignore=(), flip=None):
    """Exact comparison by (sample index, field); order within a pair is kept.

    ``ignore`` names fields dropped from the model side. ``flip=(field, mask)``
    is the negative control: the first model record of that field (else the
    first record) has its value XORed with ``mask``, so the compare must fail.
    """
    want = [r for r in model_records if r[1] not in ignore]
    if flip is not None and want:
        field_, mask = flip
        k = next((i for i, r in enumerate(want) if r[1] == field_), 0)
        idx, field, val = want[k]
        want[k] = (idx, field, val ^ mask)

    def group(records):
        g = {}
        for idx, field, val in records:
            g.setdefault((idx, field), []).append(val)
        return g

    gr, gw = group(rtl_records), group(want)
    keys = sorted(set(gr) | set(gw))
    for n, key in enumerate(keys):
        if gr.get(key) != gw.get(key):
            raise AssertionError(
                f"{name}: first mismatch at record group {n} (sample {key[0]}, field {key[1]}): "
                f"rtl={[f'{v:x}' for v in gr.get(key, [])]} "
                f"expected={[f'{v:x}' for v in gw.get(key, [])]} "
                f"(rtl {len(rtl_records)} records, model {len(want)})")
    assert len(rtl_records) == len(want), f"{name}: record count rtl={len(rtl_records)} expected={len(want)}"


def load_rx_case(vec, name):
    """(iq, flags, model trace) of an RX case; needs sim/channel on sys.path."""
    from pathlib import Path

    import cm_a

    iq, flags, _gain = cm_a.unpack_rx_records((Path(vec) / f"{name}.rx.bin").read_bytes())
    return iq, flags, read_trace(Path(vec) / f"{name}.model.trace")
