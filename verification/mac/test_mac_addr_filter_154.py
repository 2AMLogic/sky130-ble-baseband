"""15.4 address filter truth table (exhaustive over representative classes)."""

import itertools

import cocotb
from cocotb.triggers import Timer

OWN_PAN, OWN_EXT = 0x1A2B, 0x0123456789ABCDEF
PANS = {"own": OWN_PAN, "bcast": 0xFFFF, "other": 0x1A2C}
OWN_SHORTS = {"normal": 0x4321, "unassigned": 0xFFFE, "bcast": 0xFFFF}
SHORT_ADDRS = [0x4321, 0xFFFF, 0xFFFE, 0x4322, 0x0000]
EXTS = {"own": OWN_EXT, "flip_lo": OWN_EXT ^ 1, "flip_hi": OWN_EXT ^ (1 << 63),
        "bcast_like": 0xFFFF_FFFF_FFFF_FFFF}


def oracle(promisc, own_short, mode, pan_v, addr):
    """Rule table written case by case, independent of the RTL's gate form."""
    pan_ok = pan_v in (OWN_PAN, 0xFFFF)
    uni = bcast = False
    if mode == 2:
        a = addr & 0xFFFF
        if a == 0xFFFF:
            bcast = pan_ok
        elif a == own_short and own_short not in (0xFFFE, 0xFFFF):
            uni = pan_ok
    elif mode == 3:
        uni = pan_ok and addr == OWN_EXT
    no_dest = mode == 0
    return dict(accept=promisc or uni or bcast or no_dest, unicast_me=uni, bcast=bcast,
                no_dest=no_dest, ack_eligible=uni and not promisc)


@cocotb.test()
async def truth_table(dut):
    dut.own_pan.value = OWN_PAN
    dut.own_ext.value = OWN_EXT
    n = 0
    for promisc, (_, own_short), mode, pan_v in itertools.product(
            (0, 1), OWN_SHORTS.items(), range(4), PANS.values()):
        addrs = SHORT_ADDRS if mode == 2 else list(EXTS.values()) if mode == 3 else [0]
        if mode == 2 and own_short not in SHORT_ADDRS:
            addrs = addrs + [own_short]
        for a in addrs:
            dut.promiscuous.value = promisc
            dut.own_short.value = own_short
            dut.dest_mode.value = mode
            dut.dest_pan.value = pan_v
            dut.dest_addr.value = a
            await Timer(1, "ns")
            want = oracle(bool(promisc), own_short, mode, pan_v, a)
            got = {k: bool(int(getattr(dut, k).value)) for k in want}
            assert got == want, (f"promisc={promisc} own_short={own_short:#x} mode={mode} "
                                 f"pan={pan_v:#x} addr={a:#x}: got {got} expected={want}")
            n += 1
    dut._log.info(f"{n} filter cases checked")
    assert n == 198  # size of the enumerated domain; guards against it silently shrinking


@cocotb.test()
async def spot_checks(dut):
    dut.own_pan.value = OWN_PAN
    dut.own_ext.value = OWN_EXT
    dut.own_short.value = 0x4321
    dut.promiscuous.value = 0
    # reserved mode rejected; promiscuous accepts it but never ACKs
    dut.dest_mode.value = 1
    dut.dest_pan.value = OWN_PAN
    dut.dest_addr.value = 0x4321
    await Timer(1, "ns")
    assert int(dut.accept.value) == 0
    dut.promiscuous.value = 1
    await Timer(1, "ns")
    assert int(dut.accept.value) == 1 and int(dut.ack_eligible.value) == 0
