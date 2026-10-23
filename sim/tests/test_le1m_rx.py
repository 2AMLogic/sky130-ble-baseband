"""Integer receiver: controls, arithmetic helpers, trace output."""

import os
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [os.path.join(HERE, "..", "channel"), os.path.join(HERE, "..", "model")]
import cm_a  # noqa: E402
import le1m_rx  # noqa: E402
import packet  # noqa: E402
import traces  # noqa: E402


def _decode(params, seed, payload=37):
    rng = np.random.Generator(np.random.PCG64(seed))
    data = bytes(rng.integers(0, 256, payload, dtype=np.uint8).tolist())
    tx, _ = packet.build_frame_bits(data, header0=int(rng.integers(0, 256)))
    out = cm_a.generate_packet(tx, params, rng)
    rx = le1m_rx.demodulate(out.iq, out.flags, out.gain)
    return np.array(tx[40:], dtype=np.uint8), rx, out


def _errors(ref, rx):
    if not rx["synced"]:
        return len(ref)
    m = min(len(ref), len(rx["bits"]))
    return int((ref[:m] != rx["bits"][:m]).sum()) + len(ref) - m


def test_zero_noise_zero_impairment_ber_is_zero():
    """Infinite Eb/N0, no offset/drift/clock error: BER 0 over many timing phases."""
    total = 0
    for seed in range(40):
        ref, rx, _ = _decode(cm_a.CmAParams(), seed)
        assert rx["synced"] and rx["crc_ok"]
        total += _errors(ref, rx)
    assert total == 0


@pytest.mark.parametrize("cfo,drift,ppm", [(150e3, 0.0, 100.0), (-150e3, 0.0, -100.0),
                                           (150e3, 50e3, 0.0), (-150e3, -50e3, 0.0)])
def test_spec_corners_are_error_free_without_noise(cfo, drift, ppm):
    """Offset, drift and clock extremes at maximum packet length, no noise."""
    for seed in range(4):
        prof = "linear" if drift else "none"
        ref, rx, _ = _decode(cm_a.CmAParams(cfo_hz=cfo, drift_profile=prof, drift_hz=drift,
                                            clock_ppm=ppm), seed, payload=255)
        assert _errors(ref, rx) == 0 and rx["crc_ok"], (seed, _errors(ref, rx))
        assert len(ref) == 2080          # 2120 us packet minus the 40 preamble + access-address bits


def _ber(params, packets, seed0):
    err = bits = 0
    for k in range(packets):
        ref, rx, _ = _decode(params, seed0 + k)
        err += _errors(ref, rx)
        bits += len(ref)
    return err / bits


def test_negative_control_offset_beyond_250khz_raises_ber():
    """Offset far beyond the +/-250 kHz stretch row must raise the BER, and the
    injected offset must really be that large (not clamped)."""
    ok = _ber(cm_a.CmAParams(ebn0_db=16.0, cfo_hz=0.0), 40, 100)
    bad_params = cm_a.CmAParams(ebn0_db=16.0, cfo_hz=800e3)
    bad = _ber(bad_params, 40, 100)
    _, _, out = _decode(bad_params, 100)
    assert out.cfo_hz == 800e3
    assert ok < 1e-2
    assert bad > 10 * max(ok, 1e-3) and bad > 0.1


def test_noise_degrades_ber_monotonically():
    low, high = _ber(cm_a.CmAParams(ebn0_db=8.0), 30, 200), _ber(cm_a.CmAParams(ebn0_db=14.0), 30, 200)
    assert low > high


def test_crc_matches_independent_division_implementation():
    rng = np.random.default_rng(3)
    for n in (16, 100, 2064):
        bits = [int(b) for b in rng.integers(0, 2, n)]
        assert le1m_rx.crc24(bits) == packet.crc24_division(bits)


def test_cordic_angle_accuracy():
    ang = np.linspace(-np.pi + 0.01, np.pi - 0.01, 1001)
    x = np.rint(2000 * np.cos(ang)).astype(np.int64)
    y = np.rint(2000 * np.sin(ang)).astype(np.int64)
    got = le1m_rx.cordic_angle(x, y) * 2 * np.pi / (1 << le1m_rx.ANGLE_BITS)
    err = np.abs((got - ang + np.pi) % (2 * np.pi) - np.pi)
    assert err.max() < 2e-3
    assert le1m_rx.cordic_angle(np.array([0]), np.array([0]))[0] == 0


def test_filter_taps_unity_dc_gain_and_symmetric():
    assert sum(le1m_rx.FIR_TAPS) == 1 << le1m_rx.FIR_SHIFT
    assert le1m_rx.FIR_TAPS == le1m_rx.FIR_TAPS[::-1]


def test_no_signal_gives_no_sync_and_no_bits():
    iq = np.zeros((4000, 2), dtype=np.int8)
    rx = le1m_rx.demodulate(iq)
    assert not rx["synced"] and len(rx["bits"]) == 0 and rx["trace"] == []


def test_truncated_record_is_reported_not_crashed():
    ref, rx, out = _decode(cm_a.CmAParams(), 5)
    cut = out.packet_start + 40 * 8 + 20 + 100
    rx2 = le1m_rx.demodulate(out.iq[:cut], out.flags[:cut], out.gain[:cut])
    assert rx2["synced"] and not rx2["crc_ok"] and 0 < len(rx2["bits"]) < len(ref)


def test_trace_records_are_writable_and_round_trip(tmp_path):
    ref, rx, _ = _decode(cm_a.CmAParams(ebn0_db=20.0), 9)
    fields = {r[1] for r in rx["trace"]}
    assert {"bit", "sync", "tbound", "cfo", "crc", "rssi", "gain"} <= fields
    path = tmp_path / "x.model.trace"
    traces.write_trace(path, rx["trace"])
    assert traces.read_trace(path) == rx["trace"]
    bits = [v for (_, f, v) in rx["trace"] if f == "bit"]
    assert bits == [int(b) for b in rx["bits"]]
    crc = [v for (_, f, v) in rx["trace"] if f == "crc"]
    assert crc == [1]


def test_receiver_is_deterministic():
    _, a, _ = _decode(cm_a.CmAParams(ebn0_db=12.0, draw_cfo=True), 11)
    _, b, _ = _decode(cm_a.CmAParams(ebn0_db=12.0, draw_cfo=True), 11)
    assert a["trace"] == b["trace"]
