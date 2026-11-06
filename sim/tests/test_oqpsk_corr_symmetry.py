"""Weight-matrix symmetry behind rtl/oqpsk/oqpsk_rx_corr.v: W[m+8][j] == -W[m][j].

The matrix is built exactly as the RTL function build_wneg does (same chip table
BASE, same chip_of index arithmetic mod 32, same transition rule), so the test
checks the structure the RTL relies on, not a separate model. chip_of flips the
odd-index chips when s[3] is set; each weight is a transition between chip k and
k-1, exactly one of which is odd, so `same` inverts and the weight negates. That
gives corr[m+8] = -corr[m], and |corr| <= 31 * 2^17 < 2^22 so the 23-bit
negation cannot overflow.
"""

import pytest

BASE = 0b11011001110000110101001000101110   # oqpsk_rx_corr.v localparam BASE
NTAPS = 31


def chip_of(s, ci, base=BASE):
    idx = (ci - ((s & 7) << 2)) & 31
    return ((base >> (31 - idx)) & 1) ^ (((s >> 3) & 1) & (ci & 1))


def build_w(base=BASE):
    """W[m][j] in {+1, -1}; mirrors build_wneg (bit set -> -1)."""
    w = []
    for m in range(16):
        row = []
        for j in range(NTAPS):
            k = j + 1
            same = chip_of(m, k, base) == chip_of(m, k - 1, base)
            neg = (not same) if (k & 1) else same
            row.append(-1 if neg else 1)
        w.append(row)
    return w


def symmetric(w):
    return all(w[m + 8][j] == -w[m][j] for m in range(8) for j in range(NTAPS))


def test_w_m_plus_8_is_negated():
    assert symmetric(build_w())


def test_perturbed_table_fails():
    # Perturbing the odd-chip flip rule (s[3] no longer flips odd chips) breaks it.
    def no_flip(s, ci, base=BASE):
        idx = (ci - ((s & 7) << 2)) & 31
        return (base >> (31 - idx)) & 1
    w = []
    for m in range(16):
        w.append([])
        for j in range(NTAPS):
            k = j + 1
            same = no_flip(m, k) == no_flip(m, k - 1)
            w[m].append(-1 if ((not same) if (k & 1) else same) else 1)
    assert not symmetric(w)


@pytest.mark.parametrize("bit", range(32))
def test_single_bit_chip_table_flip_is_not_silently_symmetric(bit):
    # The symmetry comes from the s[3] rule, not the table contents, so it must
    # hold for any table; flipping a bit must therefore not change the verdict.
    assert symmetric(build_w(BASE ^ (1 << bit)))


def test_negation_bound_fits_23_bits():
    assert NTAPS * (1 << 17) < (1 << 22)
