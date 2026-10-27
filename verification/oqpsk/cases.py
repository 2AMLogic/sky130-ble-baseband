"""Shared-stimulus cases for the 802.15.4 O-QPSK RTL (decision 0007).

Every case is a pure function of the seed and parameters listed here, built
from the integer models in ``sim/model/`` (``oqpsk_tx`` for payloads and the
loopback waveform). ``write_vectors`` materialises, per case, the stimulus
(``<name>.rx.bin`` for RX, ``<name>.psdu`` for TX), the model trace
``<name>.model.trace`` and a manifest ``<name>.json`` (format 1, sha256 of the
data files), which is all the cocotb replay reads. Nothing here runs inside the
simulator. There is no hand-written vector: every expected record comes from
the model.
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sim" / "channel"), str(ROOT / "sim" / "model"), str(ROOT / "verification")]
import oqpsk_rx  # noqa: E402
import oqpsk_tx  # noqa: E402
import vector_common  # noqa: E402

GOLDEN_TX = ROOT / "sim" / "model" / "golden" / "tx_154_psdu20.trace"
GOLDEN_RX = ROOT / "sim" / "model" / "golden" / "rx_154_loopback_psdu20.trace"
GOLDEN_PAYLOAD = bytes(range(1, 19))     # the golden traces' 18-octet payload (+ FCS = 20)


def _payload(seed, n):
    rng = np.random.Generator(np.random.PCG64(seed))
    return bytes(rng.integers(0, 256, n, dtype=np.uint8).tolist())


# ---------------------------------------------------------------- TX cases
# name -> (payload without FCS, description). The block appends the FCS.
TX_CASES = {
    "payload0": (b"", "empty payload: PSDU is the FCS alone"),
    "payload1": (_payload(101, 1), "1-octet payload"),
    "payload3": (_payload(102, 3), "3-octet payload"),
    "golden_payload18": (GOLDEN_PAYLOAD, "golden trace: 18-octet payload, 20-octet PSDU"),
    "payload60": (_payload(103, 60), "60-octet payload"),
    "payload125_max": (_payload(104, 125), "125-octet payload: 127-octet PSDU (maximum)"),
}


def tx_model_trace(payload):
    words = oqpsk_tx.tx_dev_words(oqpsk_tx.with_fcs(payload))
    return list(oqpsk_tx.trace_records(words))


# ---------------------------------------------------------------- RX cases
modulate = oqpsk_tx.modulate     # shared ideal modulator; also used by verification/top


def _stim(iq):
    flags = np.zeros(len(iq), dtype=np.uint8)
    gain = np.full(len(iq), 32, dtype=np.uint8)
    flags[0] = 2
    return iq, flags, gain


def _loopback(psdu, sfd=oqpsk_tx.DEFAULT_SFD, **kw):
    return _stim(modulate(oqpsk_tx.tx_dev_words(psdu, sfd), **kw))


def _fcs_packet(seed, n):
    return oqpsk_tx.with_fcs(_payload(seed, n))


def _noisy(seed, n, sigma, **kw):
    iq, flags, gain = _loopback(_fcs_packet(seed, n), **kw)
    rng = np.random.Generator(np.random.PCG64(seed + 1000))
    noisy = iq.astype(np.float64) + rng.standard_normal(iq.shape) * sigma
    return np.clip(np.rint(noisy), -128, 127).astype(np.int8), flags, gain


def _drifting(seed, n, period):
    """Sample-clock error: one deviation word repeated (period > 0) or dropped
    (period < 0) every |period| words, so the symbol timing walks and the
    receiver's +/-1 timing step fires."""
    words = list(oqpsk_tx.tx_dev_words(_fcs_packet(seed, n)))
    out = []
    for k, w in enumerate(words):
        if period < 0 and k % -period == 0:
            continue
        out.append(w)
        if period > 0 and k % period == 0:
            out.append(w)
    return _stim(modulate(out))


def _bad_fcs():
    psdu = bytearray(_fcs_packet(205, 20))
    psdu[3] ^= 0x10
    return _loopback(bytes(psdu))


def _truncated(seed, n, cut):
    iq, flags, gain = _loopback(_fcs_packet(seed, n))
    return iq[:cut], flags[:cut], gain[:cut]


def _noise_only(seed, n=4000, sigma=20.0):
    return _stim(vector_common.noise_only_iq(seed, n, sigma))


# name -> (builder, description)
RX_CASES = {
    "loopback_psdu3": (lambda: _loopback(_fcs_packet(301, 1)), "PSDU 3 octets"),
    "golden_psdu20": (lambda: _loopback(oqpsk_tx.with_fcs(GOLDEN_PAYLOAD)),
                      "golden loopback: 20-octet PSDU, 37 idle samples"),
    "loopback_psdu127": (lambda: _loopback(_fcs_packet(302, 125)), "PSDU 127 octets (maximum)"),
    "psdu1_no_fcs": (lambda: _loopback(b"\x5a"), "1-octet PSDU: no FCS, crc 0"),
    "psdu2_fcs_only": (lambda: _loopback(oqpsk_tx.with_fcs(b"")), "2-octet PSDU: the FCS of an empty payload"),
    "psdu0": (lambda: _loopback(b""), "PHR length 0: nothing after the PHR"),
    "phase_1": (lambda: _loopback(_fcs_packet(303, 18), lead=41), "idle lead 41"),
    "phase_5": (lambda: _loopback(_fcs_packet(303, 18), lead=45), "idle lead 45"),
    "short_lead_0": (lambda: _loopback(_fcs_packet(304, 18), lead=0), "packet starts at sample 0"),
    "short_lead_7": (lambda: _loopback(_fcs_packet(304, 18), lead=7), "lead shorter than the filter/CORDIC latency"),
    "short_lead_130": (lambda: _loopback(_fcs_packet(304, 18), lead=130), "lead of about one symbol"),
    "bad_fcs": (_bad_fcs, "one PSDU bit flipped after the FCS: syncs, crc 0"),
    "sfd_miss": (lambda: _loopback(_fcs_packet(206, 20), sfd=0xA6), "corrupted SFD: no sync"),
    "noise_only": (lambda: _noise_only(9), "no packet: no sync expected"),
    "silence": (lambda: _stim(np.zeros((4000, 2), dtype=np.int8)), "all-zero input: no sync"),
    "truncated_mid_psdu": (lambda: _truncated(306, 40, 3157), "capture ends inside the PSDU"),
    "truncated_after_sfd": (lambda: _truncated(307, 20, 1500), "capture ends one symbol after the SFD: no PHR decoded"),
    "truncated_in_phr": (lambda: _truncated(309, 20, 1640), "capture ends at the PHR boundary"),
    "truncated_after_phr": (lambda: _truncated(310, 20, 1900), "capture ends two symbols into the PSDU"),
    "truncated_in_search": (lambda: _truncated(308, 20, 625), "capture ends inside the preamble"),
    "noisy_s8": (lambda: _noisy(401, 20, 8.0), "loopback plus Gaussian noise, sigma 8 LSB"),
    "noisy_s35": (lambda: _noisy(403, 30, 35.0), "loopback plus Gaussian noise, sigma 35 LSB"),
    "drift_pos": (lambda: _drifting(501, 30, 600), "one extra word every 600: late sampling clock"),
    "drift_neg": (lambda: _drifting(502, 30, -600), "one word dropped every 600: early sampling clock"),
}


def rx_model_trace(iq, flags, gain):
    res = oqpsk_rx.demodulate(iq, flags, gain)
    return vector_common.sorted_trace(res), res


def write_vectors(outdir, kind, names=None):
    """kind 'tx' or 'rx'. Returns the manifest dict."""
    manifest = {}
    table = TX_CASES if kind == "tx" else RX_CASES
    for name in (names or table):
        common = {"kind": kind, "phy": "802.15.4", "rate_msps": 8}
        if kind == "tx":
            payload, desc = TX_CASES[name]
            stim_name, stim_bytes, records = f"{name}.psdu", payload, tx_model_trace(payload)
            extra = {"payload_octets": len(payload)}
        else:
            iq, flags, gain = RX_CASES[name][0]()
            desc = RX_CASES[name][1]
            stim_name, stim_bytes = f"{name}.rx.bin", vector_common.pack_rx(iq, flags, gain)
            records, res = rx_model_trace(iq, flags, gain)
            extra = {"samples": int(len(iq)), "synced": bool(res["synced"]), "crc_ok": bool(res["crc_ok"]),
                     "timing_steps": int(res["timing_steps"]), "length": res["length"]}
        manifest[name] = vector_common.write_case(outdir, name, stim_name, stim_bytes, records,
                                                  dict(common, description=desc, **extra))
    return manifest


if __name__ == "__main__":
    for kind in ("tx", "rx"):
        for k, v in write_vectors(sys.argv[1], kind).items():
            print(f"{kind} {k:24s} " + " ".join(f"{a}={b}" for a, b in v.items()
                                               if a in ("samples", "synced", "crc_ok", "timing_steps", "length", "payload_octets")))
