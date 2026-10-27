"""802.15.4 O-QPSK TX reference model: spreading, FCS, MSK sign mapping, golden trace.

Reference: IEEE 802.15.4 2.4 GHz O-QPSK PHY (clause numbers unverified, see
sim/model/README.md). The CRC-16 known answer is the published check value of
CRC-16/KERMIT for "123456789" (0x2189), independent of the spec text; the chip
table is checked structurally and the sign mapping against a floating-point
half-sine waveform built here only as an independent oracle (never as the model).
"""

import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
import oqpsk_tx as m  # noqa: E402
import traces  # noqa: E402

GOLDEN = os.path.join(HERE, "..", "model", "golden", "tx_154_psdu20.trace")
PAYLOAD = bytes(range(1, 19))                 # 18 octets + FCS = 20-octet PSDU


def test_crc16_kat():
    assert m.crc16_fcs(b"123456789") == 0x2189


def test_fcs_is_residue_free():
    psdu = m.with_fcs(PAYLOAD)
    assert len(psdu) == 20
    assert m.crc16_fcs(psdu) == 0


def test_chip_table_structure():
    t = m.CHIP_TABLE
    assert len(set(t)) == 16
    assert all(len(r) == 32 for r in t)
    for s in range(1, 8):                      # right rotation by 4 chips per symbol
        assert t[s] == t[s - 1][-4:] + t[s - 1][:-4]
    for s in range(8):                         # symbols 8..15: odd chips inverted
        assert t[s + 8] == tuple(c ^ (k & 1) for k, c in enumerate(t[s]))
    assert "".join(map(str, t[0])) == "11011001110000110101001000101110"


def test_ppdu_layout():
    p = m.ppdu_octets(b"\x11\x22\x33")
    assert p == bytes([0, 0, 0, 0, 0xA7, 3, 0x11, 0x22, 0x33])
    assert m.symbols_of(b"\xA7") == [7, 10]
    with pytest.raises(ValueError):
        m.ppdu_octets(bytes(128))


def test_word_count_and_levels():
    psdu = m.with_fcs(PAYLOAD)
    words = m.tx_dev_words(psdu)
    nchips = 32 * 2 * (4 + 1 + 1 + len(psdu))
    assert len(words) == m.SPS_CHIP * (nchips + 1)
    assert set(words) <= {-64, 0, 64}
    assert words[:4] == [0] * 4 and words[-4:] == [0] * 4      # no phase change at the ends
    assert all(w != 0 for w in words[4:-4])
    for k in range(0, len(words), 4):                           # constant within a chip interval
        assert len(set(words[k:k + 4])) == 1


def _half_sine_phase_signs(chips):
    """Oracle: float half-sine O-QPSK, sign of the phase change over each chip interval."""
    n = len(chips)
    c = [1 if x else -1 for x in chips]
    def sig(u):                                # u in chips
        i = q = 0.0
        for k in range(n):
            start = k                          # chip k pulse spans [k, k+2) chips on its rail
            if start <= u < start + 2:
                v = c[k] * math.sin(math.pi * (u - start) / 2)
                if k % 2 == 0:
                    i += v
                else:
                    q += v
        return complex(i, q)

    out = []
    for k in range(n + 1):
        z0, z1 = sig(k + 1e-9), sig(k + 1 - 1e-9)
        if abs(z0) < 1e-6 or abs(z1) < 1e-6 or k == 0 or k == n:
            out.append(0)
            continue
        d = math.atan2((z1 * z0.conjugate()).imag, (z1 * z0.conjugate()).real)
        assert abs(abs(d) - math.pi / 2) < 1e-3
        out.append(1 if d > 0 else -1)
    return out


@pytest.mark.parametrize("symbol", range(16))
def test_sign_mapping_matches_half_sine_waveform(symbol):
    chips = list(m.CHIP_TABLE[symbol]) + list(m.CHIP_TABLE[(symbol * 5 + 3) % 16])
    assert m.chip_dev_signs(chips) == _half_sine_phase_signs(chips)


def test_golden_trace_regenerates_byte_identically(tmp_path):
    out = tmp_path / "t.trace"
    m.main(["--psdu", PAYLOAD.hex(), "--append-fcs", "--out", str(out)])
    assert out.read_text() == open(GOLDEN).read()
    recs = traces.read_trace(GOLDEN)
    assert recs[0] == (0, "txact", 1)
    assert recs[-1][1:] == ("txact", 0)


def test_trace_values_are_two_complement():
    words = m.tx_dev_words(m.with_fcs(PAYLOAD))
    txdev = [v for _, f, v in m.trace_records(words) if f == "txdev"]
    assert txdev == [traces.to_unsigned(w, 8) for w in words]
