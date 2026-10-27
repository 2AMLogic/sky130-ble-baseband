"""Shared Icarus build + cocotb run for the verification run_*.py scripts.

The pass/fail rule lives here once: a run that executed no tests is a failure,
so a runner that silently selects nothing cannot report success.
"""

from pathlib import Path

from cocotb_tools.runner import get_results, get_runner


def run_cocotb(top, module, test_dir, build_dir, sources, *, label=None,
               parameters=None, extra_env=None, testcase=None):
    """Build `sources` with `top` as toplevel, run `module`, print the summary
    line and return (total, failed). `label` defaults to the toplevel name."""
    runner = get_runner("icarus")
    build = Path(build_dir)
    runner.build(sources=sources, hdl_toplevel=top, build_dir=build, always=True,
                 timescale=("1ns", "1ps"), parameters=parameters or {})
    results = runner.test(hdl_toplevel=top, test_module=module, test_dir=test_dir,
                          build_dir=build, extra_env=extra_env or {}, testcase=testcase)
    total, failed = get_results(results)
    print(f"cocotb {label or top}: {total} tests, {failed} failed")
    return total, failed


def verdict(total, failed):
    """Process exit status: non-zero on any failure or an empty run."""
    return 1 if failed or total == 0 else 0
