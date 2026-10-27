"""Shared vector materialisation for the case modules (decision 0007).

The LE 1M and O-QPSK ``cases.py`` write their stimulus, model trace and manifest
through the same code, so a change to the manifest format or the hashing cannot
drift between them. Each module keeps its own per-PHY manifest fields. Imports no
simulator, so the generators run without cocotb.
"""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "sim" / "channel"),
                str(Path(__file__).resolve().parents[1] / "sim" / "model")]
import cm_a  # noqa: E402
import traces  # noqa: E402


def noise_only_iq(seed, n, sigma):
    """Clipped-Gaussian int8 I/Q with no packet in it."""
    rng = np.random.Generator(np.random.PCG64(seed))
    return np.clip(np.rint(rng.standard_normal((n, 2)) * sigma), -128, 127).astype(np.int8)


def pack_rx(iq, flags, gain):
    """The ``<name>.rx.bin`` record stream for one RX stimulus."""
    return cm_a.pack_rx_records(type("O", (), {"iq": iq, "flags": flags, "gain": gain})())


def sorted_trace(res):
    """A demodulator result's trace in sample order."""
    return sorted(res["trace"], key=lambda r: r[0])


def write_case(outdir, name, stim_name, stim_bytes, records, info):
    """Write ``<stim_name>``, ``<name>.model.trace`` and ``<name>.json`` under
    ``outdir``. ``info`` carries the per-PHY manifest fields; ``format`` and
    ``sha256`` are added here. Returns the finished manifest."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stim = outdir / stim_name
    stim.write_bytes(stim_bytes)
    tr = outdir / f"{name}.model.trace"
    traces.write_trace(tr, records)
    info = dict(info, format=1,
                sha256={stim.name: hashlib.sha256(stim.read_bytes()).hexdigest(),
                        tr.name: hashlib.sha256(tr.read_bytes()).hexdigest()})
    (outdir / f"{name}.json").write_text(json.dumps(info, indent=1, sort_keys=True) + "\n")
    return info
