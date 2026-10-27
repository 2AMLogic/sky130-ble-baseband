"""802.15.4 O-QPSK RX reference model: noiseless TX-to-RX loopback, edge cases, golden trace.

The loopback stimulus is made by an ideal frequency modulator standing in for
the front end (phase += 64 * tx_dev per sample, in turns/2**16; I/Q rounded to
int8). Noise, frequency offset and clock drift are other issues; nothing here
is an error-rate claim.
"""

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import oqpsk_rx as rx  # noqa: E402
import oqpsk_tx as tx  # noqa: E402
import traces  # noqa: E402

GOLDEN = os.path.join(HERE, "..", "model", "golden", "rx_154_loopback_psdu20.trace")
modulate = tx.modulate


def loopback(psdu, **kw):
    sfd = kw.pop("sfd", tx.DEFAULT_SFD)
    return rx.demodulate(modulate(tx.tx_dev_words(psdu, sfd), **kw))


@pytest.mark.parametrize("payload_len", [1, 18, 125])
def test_loopback_returns_payload_with_fcs_pass(payload_len):
    rng = np.random.Generator(np.random.PCG64(payload_len))
    psdu = tx.with_fcs(bytes(rng.integers(0, 256, payload_len, dtype=np.uint8).tolist()))
    r = loopback(psdu)
    assert r["synced"] and r["length"] == len(psdu)
    assert r["psdu"] == psdu
    assert r["crc_ok"]


@pytest.mark.parametrize("lead", range(0, 8))
def test_loopback_any_timing_phase(lead):
    psdu = tx.with_fcs(bytes(range(20)))
    r = loopback(psdu, lead=lead + 40)
    assert r["psdu"] == psdu and r["crc_ok"]


def test_one_octet_psdu_has_no_fcs():
    r = loopback(b"\x5a")
    assert r["synced"] and r["psdu"] == b"\x5a"
    assert not r["crc_ok"]
    assert [v for _, f, v in r["trace"] if f == "crc"] == [0]


def test_bad_fcs_reports_crc_zero_but_syncs():
    psdu = bytearray(tx.with_fcs(bytes(range(20))))
    psdu[3] ^= 0x10
    r = loopback(bytes(psdu))
    assert r["synced"] and r["psdu"] == bytes(psdu)
    assert not r["crc_ok"]
    crc = [v for _, f, v in r["trace"] if f == "crc"]
    assert crc == [0]


def test_corrupted_sfd_reports_no_sync():
    r = loopback(tx.with_fcs(bytes(range(20))), sfd=0xA6)
    assert not r["synced"]
    assert not any(f == "sync" for _, f, _ in r["trace"])
    assert r["psdu"] == b"" and not r["crc_ok"]


def test_no_signal_no_sync():
    r = rx.demodulate(np.zeros((4000, 2), dtype=np.int8))
    assert not r["synced"]


def test_truncated_capture_does_not_crc():
    iq = modulate(tx.tx_dev_words(tx.with_fcs(bytes(range(40)))))
    r = rx.demodulate(iq[: len(iq) // 2])
    assert r["synced"] and not r["crc_ok"]
    assert not any(f == "crc" for _, f, _ in r["trace"])


def test_trace_taps_and_order():
    psdu = tx.with_fcs(bytes(range(1, 19)))
    r = loopback(psdu)
    tr = r["trace"]
    assert [i for i, _, _ in tr] == sorted(i for i, _, _ in tr)
    octets = [v for _, f, v in tr if f == "octet"]
    assert bytes(octets) == psdu
    sync = [i for i, f, _ in tr if f == "sync"]
    assert sync == [r["sync_index"]]
    assert min(i for i, f, _ in tr if f == "octet") > sync[0]
    tb = [v for _, f, v in tr if f == "tbound"]
    nchips = 32 * (2 + 2 * len(psdu))
    assert tb[:16] == list(range(16)) and tb[-16:] == list(range(nchips - 16, nchips))
    assert {f for _, f, _ in tr} <= {"sync", "octet", "tbound", "crc", "rssi", "gain"}
    traces.write_trace(os.devnull, tr)                  # parses under the 0007 format rules


def test_gain_replay_records():
    iq = modulate(tx.tx_dev_words(tx.with_fcs(b"abc")))
    flags = np.zeros(len(iq), dtype=np.uint8)
    gain = np.full(len(iq), 32, dtype=np.uint8)
    flags[5] = 2
    r = rx.demodulate(iq, flags, gain)
    assert (5, "gain", 32) in r["trace"]


def test_golden_trace_regenerates_byte_identically(tmp_path):
    psdu = tx.with_fcs(bytes(range(1, 19)))
    r = loopback(psdu)
    out = tmp_path / "rx.trace"
    traces.write_trace(str(out), r["trace"])
    assert out.read_text() == open(GOLDEN).read()
    assert r["crc_ok"]
