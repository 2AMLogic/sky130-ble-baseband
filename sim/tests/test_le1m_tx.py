"""Tests for the LE 1M TX reference model and the trace format.

Reference sources are the Core Specification, Vol 6 Part B (section numbers
only). No published sample vector was available when these were written, so
the pinned known-answer values below are UNVERIFIED against a spec-published
vector: they are produced by the independent bit-level reference
implementations in this file (written from the spec's register description,
not from the model code) and pinned. Replace with a published vector when one
is cited. CRC_NEGATIVE=1 flips the CRC init handed to the model; the CRC
known-answer test must then fail (see `make model-test`).
"""

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "model"))
import le1m_tx as m  # noqa: E402
import traces  # noqa: E402

PDU = bytes.fromhex("4209010203040506020106")
CRC_PINNED = 0xC5D88C  # unverified pin, see module docstring
WHITEN_CH37_PINNED = [1, 0, 1, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1]  # unverified pin


def ref_whiten_positions(bits, channel):
    """Vol 6 Part B 3.2 as an explicit position array: pos0=1, pos1..6 = channel MSB..LSB."""
    pos = [1] + [(channel >> (5 - i)) & 1 for i in range(6)]
    out = []
    for b in bits:
        o = pos[6]
        out.append(b ^ o)
        pos = [o, pos[0], pos[1], pos[2], pos[3] ^ o, pos[4], pos[5]]
    return out


def ref_crc_positions(pdu, init):
    """Vol 6 Part B 3.1.1 as an explicit position array (position 0 = init LSB)."""
    pos = [(init >> i) & 1 for i in range(24)]
    taps = {0, 1, 3, 4, 6, 9, 10}
    for bit in m.bytes_to_bits(pdu):
        fb = pos[23] ^ bit
        pos = [(fb if i == 0 else pos[i - 1] ^ (fb if i in taps else 0)) for i in range(24)]
    return sum(b << i for i, b in enumerate(pos))


CRC_INIT_UNDER_TEST = m.DEFAULT_CRC_INIT ^ (1 if os.environ.get("CRC_NEGATIVE") else 0)


def test_crc24_kat():
    expected = ref_crc_positions(PDU, 0x555555)
    got = m.crc24(PDU, CRC_INIT_UNDER_TEST)
    assert got == expected == CRC_PINNED, f"crc24 KAT mismatch: got {got:06x} expected {expected:06x}"


def test_crc24_residue_zero():
    # Running the register over PDU + transmitted CRC returns it to zero (Vol 6 Part B 3.1.1).
    for pdu in (b"", b"\x00", PDU, bytes(range(40))):
        crc = m.crc24(pdu)
        state = 0x555555
        poly = m.CRC_POLY
        for b in m.bytes_to_bits(pdu) + m.crc_bits(crc):
            fb = ((state >> 23) & 1) ^ b
            state = (state << 1) & 0xFFFFFF
            if fb:
                state ^= poly
        assert state == 0


def test_whiten_kat():
    zeros = [0] * 40
    for ch in (0, 37, 38, 39):
        assert m.whiten(zeros, ch) == ref_whiten_positions(zeros, ch)
    assert m.whiten(zeros, 37)[:16] == WHITEN_CH37_PINNED


def test_whiten_involution_and_period():
    data = [1, 0, 1, 1, 0, 0, 1] * 30
    for ch in (0, 17, 37, 39):
        assert m.whiten(m.whiten(data, ch), ch) == data
    seq = m.whiten([0] * 254, 37)
    assert seq[:127] == seq[127:] and seq[:127] != seq[1:128]  # primitive x^7+x^4+1: period 127


def test_preamble_selection():
    assert m.frame(b"", 37)[:8] == m.bytes_to_bits(b"\xaa")        # AA bit 0 = 0 (0x8E89BED6)
    assert m.frame(b"", 37, 0x8E89BED7)[:8] == m.bytes_to_bits(b"\x55")


def test_frame_layout():
    bits = m.frame(PDU, 37)
    assert len(bits) == 8 + 32 + 8 * len(PDU) + 24
    assert bits[8:40] == m.bytes_to_bits(bytes.fromhex("D6BE898E"))
    tail = m.whiten(m.bytes_to_bits(PDU) + m.crc_bits(m.crc24(PDU)), 37)
    assert bits[40:] == tail


def test_taps_gaussian_bt05():
    taps = m.GAUSS_TAPS
    assert sum(taps) == 32 << m.TAP_SHIFT
    assert list(taps) == list(reversed(taps))
    sigma = m.SPS * math.sqrt(math.log(2)) / (2 * math.pi * 0.5)   # BT = 0.5
    ideal = [math.exp(-((n - 16) ** 2) / (2 * sigma ** 2)) for n in range(len(taps))]
    scale = (32 << m.TAP_SHIFT) / sum(ideal)
    assert max(abs(t - i * scale) for t, i in zip(taps, ideal)) < 1


@pytest.mark.parametrize("bit", [0, 1])
def test_deviation_exactly_32_on_long_runs(bit):
    words = m.gaussian_shape([bit] * 12)
    n = len(m.GAUSS_TAPS)
    settled = words[n - 1 : 12 * m.SPS]
    assert settled and set(settled) == {32 if bit else -32}


def test_alternating_bits_stay_in_int8():
    words = m.gaussian_shape([1, 0] * 200)
    assert all(-128 <= w <= 127 for w in words)
    assert max(words) < 32 and min(words) > -32


def test_drains_to_zero_and_word_count():
    for pdu in (b"", PDU, bytes(range(256)) + b"\x01"):
        bits = m.frame(pdu, 5)
        words = m.gaussian_shape(bits)
        assert len(words) == 8 * len(bits) + len(m.GAUSS_TAPS) - 1
        assert words[-1] == 0 and words[0] == 0


def test_max_pdu_and_channel_limits():
    assert len(m.frame(bytes(257), 0)) == 8 + 32 + 8 * 257 + 24
    with pytest.raises(ValueError):
        m.frame(bytes(258), 0)
    for ch in (0, 39):
        m.frame(PDU, ch)
    for ch in (-1, 40):
        with pytest.raises(ValueError):
            m.frame(PDU, ch)


def test_trace_round_trip(tmp_path):
    words = m.tx_dev_words(PDU, 37)
    recs = list(m.trace_records(words))
    path = tmp_path / "t.trace"
    traces.write_trace(path, recs)
    back = traces.read_trace(path)
    assert back == recs
    assert [traces.to_signed(v, 8) for _, f, v in back if f == "txdev"] == words
    assert [(i, v) for i, f, v in back if f == "txact"] == [(0, 1), (len(words) + 1, 0)]


def test_cli_writes_golden_equivalent(tmp_path):
    out = tmp_path / "g.trace"
    m.main(["--pdu", PDU.hex(), "--channel", "37", "--out", str(out)])
    golden = os.path.join(os.path.dirname(__file__), "..", "model", "golden", "tx_adv_ch37.trace")
    assert open(out).read() == open(golden).read()


def test_trace_field_agnostic(tmp_path):
    path = tmp_path / "rx.trace"
    recs = [(3, "bit", 1), (3, "rssi", 0x7F), (9, "sync", 1), (9, "cfo", 0xFFF0)]
    traces.write_trace(path, recs)
    assert traces.read_trace(path) == recs


@pytest.mark.parametrize("line", [
    "5 txdev", "x txdev 1f", "5 nofield 1", "5 txdev 0x1f", "5 txdev zz", "-1 txdev 0",
    "5  txdev 1", "", " 5 txdev 1",
])
def test_unparsable_line_raises(tmp_path, line):
    path = tmp_path / "bad.trace"
    path.write_text("0 txact 1\n" + line + "\n")
    with pytest.raises(traces.TraceError):
        traces.read_trace(path)


def test_trace_rejects_decreasing_index_and_missing_newline(tmp_path):
    path = tmp_path / "bad.trace"
    path.write_text("5 txdev 1\n4 txdev 1\n")
    with pytest.raises(traces.TraceError):
        traces.read_trace(path)
    path.write_text("5 txdev 1")
    with pytest.raises(traces.TraceError):
        traces.read_trace(path)
    with pytest.raises(traces.TraceError):
        traces.write_trace(path, [(1, "nofield", 0)])


