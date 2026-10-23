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
