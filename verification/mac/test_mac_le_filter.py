"""LE own-address / AA compare truth table."""

import itertools

import cocotb
from cocotb.triggers import Timer

OWN_AA = 0x8E89BED6
OWN_ADDR = 0xC0FFEE123456


@cocotb.test()
async def truth_table(dut):
    dut.own_aa.value = OWN_AA
    dut.own_addr.value = OWN_ADDR
    n = 0
    aas = [OWN_AA, OWN_AA ^ 1, OWN_AA ^ 0x80000000, 0]
    addrs = [OWN_ADDR, OWN_ADDR ^ 1, OWN_ADDR ^ (1 << 47), 0]
    for own_type, aa, pdu, rxadd, adv in itertools.product(
            (0, 1), aas, range(16), (0, 1), addrs):
        dut.own_addr_type.value = own_type
        dut.rx_aa.value = aa
        dut.pdu_type.value = pdu
        dut.rx_rxadd.value = rxadd
        dut.adv_a.value = adv
        await Timer(1, "ns")
        aa_ok = aa == OWN_AA
        checked = pdu in (3, 5)          # SCAN_REQ, CONNECT_IND
        a_ok = adv == OWN_ADDR and rxadd == own_type
        got = (int(dut.aa_match.value), int(dut.addr_checked.value),
               int(dut.addr_match.value), int(dut.accept.value))
        want = (aa_ok, checked, a_ok, aa_ok and (not checked or a_ok))
        assert got == tuple(int(x) for x in want), (
            f"type={own_type} aa={aa:#x} pdu={pdu} rxadd={rxadd} adv={adv:#x}: got {got} expected={want}")
        n += 1
    assert n == 2 * 4 * 16 * 2 * 4
