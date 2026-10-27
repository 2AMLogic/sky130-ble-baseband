"""Build rtl/mac/ with Icarus and run the lower-MAC cocotb benches.

Usage: python verification/mac/run_mac.py <build_dir> [32|16]
Runs every bench at the given core clock (default 32 MHz; 16 = fallback, which
halves the cycle budgets via parameter overrides). MAC_NEGATIVE=1 makes the
cycle-budget expectations wrong on purpose; the run must then fail.
Exits non-zero if any cocotb test fails.
"""

import sys
from pathlib import Path

from cocotb_tools.runner import get_results, get_runner

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RTL = ROOT / "rtl/mac"


def budgets(mhz: int) -> dict:
    s = {32: 1, 16: 2}[mhz]
    return dict(turn=6144 // s, ldig154=1024 // s, tifs=4800 // s, ldigle=320 // s,
                ackwait=27648 // s, clk_per_us=32 // s)


def benches(mhz: int):
    b = budgets(mhz)
    # (toplevel, test module, parameters)
    return [
        ("mac_timer", "test_mac_timer", dict(CYCLES=7)),
        ("mac_trigger", "test_mac_trigger", dict(CLK_PER_US=b["clk_per_us"])),
        ("mac_ack_ctrl", "test_mac_ack_ctrl",
         dict(TURNAROUND_CYCLES=b["turn"], L_DIG_CYCLES=b["ldig154"])),
        ("mac_ackwait", "test_mac_ackwait", dict(ACKWAIT_CYCLES=b["ackwait"])),
        ("mac_le_resp", "test_mac_le_resp",
         dict(TIFS_CYCLES=b["tifs"], L_DIG_CYCLES=b["ldigle"])),
        ("mac_addr_filter_154", "test_mac_addr_filter_154", {}),
        ("mac_le_filter", "test_mac_le_filter", {}),
    ]


def main(build_dir: str, mhz: int) -> int:
    sources = sorted(RTL.glob("*.v"))
    total_all = failed_all = 0
    for top, module, params in benches(mhz):
        bdir = Path(build_dir) / f"{top}_{mhz}mhz"
        runner = get_runner("icarus")
        runner.build(sources=sources, hdl_toplevel=top, build_dir=bdir, always=True,
                     timescale=("1ns", "1ps"), parameters=params)
        results = runner.test(hdl_toplevel=top, test_module=module, test_dir=HERE,
                              build_dir=bdir, extra_env={"MAC_CLK_MHZ": str(mhz)})
        total, failed = get_results(results)
        print(f"cocotb mac {top} @ {mhz} MHz: {total} tests, {failed} failed")
        total_all += total
        failed_all += failed
    print(f"cocotb mac @ {mhz} MHz: {total_all} tests, {failed_all} failed")
    return 1 if failed_all or total_all == 0 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 32))
