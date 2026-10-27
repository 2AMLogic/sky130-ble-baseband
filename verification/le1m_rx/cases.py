"""Shared-stimulus cases for the LE 1M RX RTL (decision 0007).

Every case is a pure function of the seed and parameters listed here, built
from the CM-A channel model in ``sim/channel/`` and the integer receiver in
``sim/model/``. ``write_vectors`` materialises, per case, the RX stimulus
``<name>.rx.bin``, the model trace ``<name>.model.trace`` and a manifest
``<name>.json`` (format 1, sha256 of the data files), which is all the cocotb
replay reads. Nothing here runs inside the simulator.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sim" / "channel"), str(ROOT / "sim" / "model")]
import cm_a  # noqa: E402
import le1m_rx  # noqa: E402
import packet  # noqa: E402
import traces  # noqa: E402

AA = packet.DEFAULT_ACCESS_ADDRESS
CRC_INIT = packet.DEFAULT_CRC_INIT


def _payload(rng, n):
    return bytes(rng.integers(0, 256, n, dtype=np.uint8).tolist())


def _frame(rng, payload_octets, tx_aa=AA, flip_bit=None):
    data = _payload(rng, payload_octets)
    bits, _ = packet.build_frame_bits(data, header0=int(rng.integers(0, 256)), access_address=tx_aa)
    if flip_bit is not None:
        bits[flip_bit] ^= 1
    return bits


def _channel(seed, payload_octets, params, tx_aa=AA, flip_bit=None):
    rng = np.random.Generator(np.random.PCG64(seed))
    out = cm_a.generate_packet(_frame(rng, payload_octets, tx_aa, flip_bit), params, rng)
    return out.iq, out.flags, out.gain


def _noise_only(seed, n=3000, sigma=20.0):
    rng = np.random.Generator(np.random.PCG64(seed))
    iq = np.clip(np.rint(rng.standard_normal((n, 2)) * sigma), -128, 127).astype(np.int8)
    flags = np.zeros(n, dtype=np.uint8)
    flags[0] = 2
    return iq, flags, np.full(n, 32, dtype=np.uint8)


def _clipped(seed):
    iq, flags, gain = _channel(seed, 30, cm_a.CmAParams(ebn0_db=18.0))
    wide = iq.astype(np.int32) * 3
    sat = (np.abs(wide) > 127).any(axis=1)
    return np.clip(wide, -128, 127).astype(np.int8), (flags | sat.astype(np.uint8)), gain


def _truncated(seed):
    iq, flags, gain = _channel(seed, 60, cm_a.CmAParams(ebn0_db=20.0))
    cut = 64 * 8 + 40 * 8 + 90 * 8      # lead-in, preamble + AA, then part of the PDU
    return iq[:cut], flags[:cut], gain[:cut]


def _very_short(seed):
    """Cut inside the candidate window after the access address: the search is
    clipped at the end of the stimulus."""
    iq, flags, gain = _channel(seed, 20, cm_a.CmAParams(ebn0_db=20.0))
    cut = 850     # the unclipped packet syncs at 851; cut at 850 the model syncs at 849
    return iq[:cut], flags[:cut], gain[:cut]


# name -> (builder, one-line description)
CASES = {
    "nominal_noiseless": (lambda: _channel(1, 37, cm_a.CmAParams()),
                          "37-octet payload, no noise, no impairment"),
    "noisy_14db": (lambda: _channel(2, 37, cm_a.CmAParams(ebn0_db=14.0)),
                   "Eb/N0 14 dB"),
    "noisy_9db": (lambda: _channel(3, 37, cm_a.CmAParams(ebn0_db=9.0)),
                  "Eb/N0 9 dB, bit errors expected"),
    "cfo_pos_clk_pos_maxlen": (lambda: _channel(4, 255, cm_a.CmAParams(cfo_hz=150e3, clock_ppm=100.0)),
                               "+150 kHz, +100 ppm, 255-octet payload, no noise"),
    "cfo_neg_clk_neg": (lambda: _channel(5, 20, cm_a.CmAParams(ebn0_db=16.0, cfo_hz=-150e3, clock_ppm=-100.0)),
                        "-150 kHz, -100 ppm, 16 dB"),
    "drift_linear": (lambda: _channel(6, 60, cm_a.CmAParams(ebn0_db=16.0, drift_profile="linear", drift_hz=50e3)),
                     "linear +50 kHz drift over the packet, 16 dB"),
    "drift_stepped_neg": (lambda: _channel(7, 60, cm_a.CmAParams(drift_profile="stepped", drift_hz=-50e3,
                                                                  cfo_hz=-100e3)),
                          "stepped -50 kHz drift at the spec peak rate, -100 kHz offset"),
    "noisy_11db_a": (lambda: _channel(21, 37, cm_a.CmAParams(ebn0_db=11.0)), "Eb/N0 11 dB"),
    "noisy_11db_b": (lambda: _channel(22, 80, cm_a.CmAParams(ebn0_db=11.0, cfo_hz=60e3, clock_ppm=40.0)),
                     "Eb/N0 11 dB, +60 kHz, +40 ppm, 80 octets"),
    "cfo_stretch_250k": (lambda: _channel(23, 37, cm_a.CmAParams(ebn0_db=18.0, cfo_hz=250e3)),
                         "+250 kHz offset (stretch row), 18 dB"),
    "drawn_impairments": (lambda: _channel(24, 50, cm_a.CmAParams(ebn0_db=14.0, draw_cfo=True, draw_clock=True)),
                          "offset and clock error drawn per the seeds policy, 14 dB"),
    "bad_crc": (lambda: _channel(8, 37, cm_a.CmAParams(ebn0_db=20.0), flip_bit=40 + 16 + 8 * 10 + 3),
                "one payload bit flipped after the CRC was computed"),
    "noise_only": (lambda: _noise_only(9), "no packet: missed detect, or the model's false alarm"),
    "aa_one_bit_error": (lambda: _channel(10, 30, cm_a.CmAParams(ebn0_db=20.0), tx_aa=AA ^ (1 << 17)),
                         "transmitted access address differs in one bit"),
    "aa_other": (lambda: _channel(11, 30, cm_a.CmAParams(ebn0_db=20.0), tx_aa=0x71764129),
                 "unrelated access address: no sync expected"),
    "aa_eight_bit_error": (lambda: _channel(12, 30, cm_a.CmAParams(ebn0_db=20.0), tx_aa=AA ^ 0x00FF0000),
                           "transmitted access address differs in eight bits"),
    "clipped_input": (lambda: _clipped(13), "input scaled x3 into saturation, rx_sat flagged"),
    "truncated_in_pdu": (lambda: _truncated(14), "stimulus ends inside the PDU"),
    "truncated_in_search": (lambda: _very_short(15), "stimulus ends inside the sync candidate window"),
}


def build(name):
    iq, flags, gain = CASES[name][0]()
    return iq, flags, gain


def model_trace(iq, flags, gain):
    res = le1m_rx.demodulate(iq, flags, gain)
    return sorted(res["trace"], key=lambda r: r[0]), res


def write_vectors(outdir, names=None):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name in (names or CASES):
        iq, flags, gain = build(name)
        rx = outdir / f"{name}.rx.bin"
        rx.write_bytes(cm_a.pack_rx_records(type("O", (), {"iq": iq, "flags": flags, "gain": gain})()))
        records, res = model_trace(iq, flags, gain)
        tr = outdir / f"{name}.model.trace"
        traces.write_trace(tr, records)
        info = {
            "format": 1, "kind": "rx", "phy": "le1m", "rate_msps": 8, "channel_model": "CM-A",
            "description": CASES[name][1], "samples": int(len(iq)),
            "synced": bool(res["synced"]), "crc_ok": bool(res["crc_ok"]),
            "sha256": {rx.name: hashlib.sha256(rx.read_bytes()).hexdigest(),
                       tr.name: hashlib.sha256(tr.read_bytes()).hexdigest()},
        }
        (outdir / f"{name}.json").write_text(json.dumps(info, indent=1, sort_keys=True) + "\n")
        manifest[name] = info
    return manifest


if __name__ == "__main__":
    m = write_vectors(sys.argv[1], sys.argv[2:] or None)
    for k, v in m.items():
        print(f"{k:28s} samples={v['samples']:6d} synced={v['synced']} crc_ok={v['crc_ok']}")
