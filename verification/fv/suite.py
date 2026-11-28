"""The bench table of the klt functional-verification suite (issue #202).

One row per run: what to build (an `rtl/baseband.f` block, through
`verification/rtl_sources.py`), which cocotb test module to run, the request
`parameters` / `env` the bench needs, and -- for the negative rows -- the
right-reason pattern a failing run's `error_message` must carry. The request
documents (`manifests/requests/fv/`) are generated from this table by
`make_requests.py`, the committed reports (`manifests/reports/fv/`) are
validated against it by `check_reports.py`, and `run_suite.sh` regenerates
them; this file is the one place the suite is declared.

Run under the repo venv (`$(PYTHON)`): importing `run_mac` and `run_host`
pulls in `cocotb_run`, so the cycle-budget and host-configuration tables
stay defined once, in the runners the cold start already executes. The four
benches whose runners generate stimulus before the simulator starts
(le1m_tx, le1m_rx, oqpsk_tx/rx) run here through a thin wrapper module
(`bench_*.py` in this directory) that performs the same pre-step the
`run_*.py` script does and then re-exports the unmodified `@cocotb.test()`
suite; the benches themselves are not touched.
"""

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFICATION = HERE.parent
ROOT = VERIFICATION.parent

sys.path[:0] = [str(VERIFICATION), str(VERIFICATION / "mac"),
               str(VERIFICATION / "host")]

from rtl_sources import (  # noqa: E402
    block_modules, block_sources, rtl_sources)
import run_host  # noqa: E402
import run_mac  # noqa: E402

REQUESTS_DIR = ROOT / "manifests" / "requests" / "fv"
REPORTS_DIR = ROOT / "manifests" / "reports" / "fv"

# One pinned cocotb seed for every request, so a committed report is
# reproducible from its request (the effective seed is echoed in the report's
# environment.random_seed either way).
RANDOM_SEED = 202

MAC_MODULES = block_modules("mac")


def _repo_rel(paths):
    return [str(Path(p).resolve().relative_to(ROOT)) for p in paths]


# The ratified host configurations (FIFO depth, clocks per microsecond) are
# declared once, in the cold-start host runner; each row is named after the
# runner's own d<depth>_c<clocks> build tag.
HOST_CONFIGS = [(f"host_d{cfg['FIFO_DEPTH']}_c{cfg['CLK_PER_US']}", cfg)
                for cfg in run_host.CONFIGS]

POSITIVE = [
    dict(
        name=name,
        hdl_toplevel="host_top",
        module="test_host",
        search_path=VERIFICATION / "host",
        sources=_repo_rel(block_sources("host")),
        parameters=cfg,
        env={"HOST_FIFO_DEPTH": str(cfg["FIFO_DEPTH"]),
             "HOST_CLK_PER_US": str(cfg["CLK_PER_US"])},
    )
    for name, cfg in HOST_CONFIGS
] + [
    dict(name="le1m_tx", hdl_toplevel="le1m_tx", module="bench_le1m_tx",
         search_path=HERE, sources=_repo_rel(block_sources("le1m_tx")),
         parameters={}, env={}),
    dict(name="le1m_rx", hdl_toplevel="le1m_rx", module="bench_le1m_rx",
         search_path=HERE, sources=_repo_rel(block_sources("le1m_rx")),
         parameters={}, env={}),
    dict(name="oqpsk_tx", hdl_toplevel="oqpsk_tx", module="bench_oqpsk_tx",
         search_path=HERE, sources=_repo_rel(block_sources("oqpsk_tx")),
         parameters={}, env={}),
    dict(name="oqpsk_rx", hdl_toplevel="oqpsk_rx", module="bench_oqpsk_rx",
         search_path=HERE, sources=_repo_rel(block_sources("oqpsk_rx")),
         parameters={}, env={}),
] + [
    dict(
        name=f"mac_{mod}_{mhz}mhz",
        hdl_toplevel=mod,
        module=f"test_{mod}",
        search_path=VERIFICATION / "mac",
        sources=_repo_rel(block_sources("mac")),
        parameters=run_mac.overrides(mhz)[mod],
        env={"MAC_CLK_MHZ": str(mhz)},
    )
    for mhz in (32, 16) for mod in MAC_MODULES
] + [
    dict(name="top", hdl_toplevel="baseband_top", module="test_top",
         search_path=VERIFICATION / "top", sources=_repo_rel(rtl_sources()),
         parameters={}, env={}),
    # spec/timing-and-area.md section 3 turnaround/latency bounds. LATENCY_JSON
    # is relative, so the measurements land in the run's own artifact
    # directory, never at an absolute host path inside the report.
    dict(name="top_latency", hdl_toplevel="baseband_top", module="test_latency",
         search_path=VERIFICATION / "top", sources=_repo_rel(rtl_sources()),
         parameters={}, env={"LATENCY_JSON": "latency.json"}),
]

_BY_NAME = {b["name"]: b for b in POSITIVE}

# One negative control per run of every group whose bench declares one, at the
# same granularity the Makefile's own negative targets use (host: both
# configurations; mac: every module at the 32 MHz target counts). `reason` is
# the pattern a failing test's error_message must carry -- the same
# right-reason rule `make test-*-negative` greps the log for.
_NEGATIVE_ENV = {
    "host": "HOST_NEGATIVE",
    "le1m_tx": "LE1M_TX_NEGATIVE",
    "le1m_rx": "LE1M_RX_NEGATIVE",
    "oqpsk_tx": "OQPSK_NEGATIVE",
    "oqpsk_rx": "OQPSK_NEGATIVE",
    "mac": "MAC_NEGATIVE",
    "top": "TOP_NEGATIVE",
    "top_latency": "LATENCY_NEGATIVE",
}

def _negative_env_key(name):
    """Which *_NEGATIVE variable the bench of `name` reads."""
    if name.startswith("top"):
        return _NEGATIVE_ENV[name]
    for group in ("le1m_rx", "le1m_tx", "oqpsk_tx", "oqpsk_rx", "host", "mac"):
        if name.startswith(group):
            return _NEGATIVE_ENV[group]
    raise KeyError(name)


# The mac benches that read MAC_NEGATIVE (the cycle-budget tests); the other
# four mac modules declare no corruption variable, so they have no negative
# control to run -- the Makefile's own mac-test-negative fails through these
# same three.
_MAC_NEGATIVE_MODULES = ("mac_ack_ctrl", "mac_ackwait", "mac_le_resp")


def _has_negative(b):
    name = b["name"]
    if name.startswith("host") or name in ("le1m_rx", "le1m_tx", "oqpsk_tx",
                                           "oqpsk_rx", "top", "top_latency"):
        return True
    return any(name == f"mac_{m}_32mhz" for m in _MAC_NEGATIVE_MODULES)


NEGATIVE = [
    dict(name=f"{b['name']}.negative", base=b["name"],
         env={_negative_env_key(b["name"]): "1"},
         reason=r"expected=|tx trace mismatch")
    for b in POSITIVE if _has_negative(b)
]


def request(bench, extra_env=None):
    """The klt functional-verification request document of one row."""
    def from_requests(path):
        return Path(os.path.relpath(Path(path).resolve(), REQUESTS_DIR)).as_posix()

    req = {
        "schema": "klt.functional_verification.request/1",
        "engine": "icarus",
        "sources": [from_requests(s) for s in bench["sources"]],
        "hdl_toplevel": bench["hdl_toplevel"],
        "testbench": {
            "module": bench["module"],
            "search_path": from_requests(bench["search_path"]),
        },
        "options": {"timescale": ["1ns", "1ps"], "random_seed": RANDOM_SEED},
    }
    if bench["parameters"]:
        req["parameters"] = bench["parameters"]
    env = dict(bench["env"])
    env.update(extra_env or {})
    if env:
        req["env"] = env
    return req


def positive_by_name(name):
    return _BY_NAME[name]
