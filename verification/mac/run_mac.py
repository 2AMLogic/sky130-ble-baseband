"""Build rtl/mac/ with Icarus and run the lower-MAC cocotb benches.

Usage: python verification/mac/run_mac.py <build_dir> [32|16]
Runs every bench at the given core clock (default 32 MHz; 16 = fallback, which
halves the cycle budgets via parameter overrides). MAC_NEGATIVE=1 makes the
cycle-budget expectations wrong on purpose; the run must then fail.
Exits non-zero if any cocotb test fails.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from cocotb_run import run_cocotb, verdict  # noqa: E402
from rtl_sources import block_modules, block_sources  # noqa: E402

HERE = Path(__file__).resolve().parent


def budgets(mhz: int) -> dict:
    s = {32: 1, 16: 2}[mhz]
    return dict(turn=6144 // s, ldig154=1024 // s, tifs=4800 // s, ldigle=320 // s,
                ackwait=27648 // s, clk_per_us=32 // s)


def overrides(mhz: int) -> dict:
    """Parameter overrides per module; {} means the RTL defaults."""
    b = budgets(mhz)
    return {
        "mac_timer": dict(CYCLES=7),
        "mac_trigger": dict(CLK_PER_US=b["clk_per_us"]),
        "mac_ack_ctrl": dict(TURNAROUND_CYCLES=b["turn"], L_DIG_CYCLES=b["ldig154"]),
        "mac_ackwait": dict(ACKWAIT_CYCLES=b["ackwait"]),
        "mac_le_resp": dict(TIFS_CYCLES=b["tifs"], L_DIG_CYCLES=b["ldigle"]),
        "mac_addr_filter_154": {},
        "mac_le_filter": {},
    }


def benches(mhz: int):
    """(toplevel, test module, parameters) for every module of the mac block.

    The module list comes from rtl/baseband.f, so a module added there is
    benched here without a second list to keep in step -- and fails loudly
    until its bench exists."""
    params = overrides(mhz)
    out = []
    for mod in block_modules("mac"):
        if mod not in params:
            raise SystemExit(
                f"ERROR: rtl/baseband.f declares mac module {mod!r}, which has no "
                f"bench parameters in {__file__}; add an entry (use {{}} for none)")
        out.append((mod, f"test_{mod}", params[mod]))
    return out


def main(build_dir: str, mhz: int) -> int:
    sources = block_sources("mac")
    total_all = failed_all = 0
    for top, module, params in benches(mhz):
        bdir = Path(build_dir) / f"{top}_{mhz}mhz"
        total, failed = run_cocotb(top, module, HERE, bdir, sources,
                                   label=f"mac {top} @ {mhz} MHz", parameters=params,
                                   extra_env={"MAC_CLK_MHZ": str(mhz)})
        total_all += total
        failed_all += failed
    print(f"cocotb mac @ {mhz} MHz: {total_all} tests, {failed_all} failed")
    return verdict(total_all, failed_all)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 32))
