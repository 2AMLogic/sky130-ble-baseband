#!/usr/bin/env python3
"""Seeded LE 1M BER sweep over CM-A with the integer non-coherent receiver.

Every point is labelled "simulated, CM-A". A point stops at ``--min-errors``
bit errors or at its packet cap; a capped point is an upper bound, not a
measurement (target-spec "Statistics"). Row verdicts use the 95 %
Clopper-Pearson **upper** bound, and are reported, not asserted.

    python3 sim/sweep/ber_sweep.py --quick            # CI mode, ~1 minute
    python3 sim/sweep/ber_sweep.py                    # full sweep, see sim/README.md
"""

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import cm_a  # noqa: E402
import le1m_rx  # noqa: E402
import packet  # noqa: E402

LABEL = "simulated, CM-A"
FORMAT = 1
CONFIDENCE = 0.95
MIN_ERRORS = 100
TARGET_BER = 1e-3
TARGET_EBN0_DB = 16.0
SPEC_CFO_HZ = 150e3
OUT_OF_SPEC_CFO_HZ = 250e3            # beyond the stretch row: flagged
NEGATIVE_CONTROL_CFO_HZ = 800e3       # far enough out that this receiver visibly fails
PAYLOAD_TYPICAL = 37                  # octets: 360 on-air bits
PAYLOAD_MAX = 255                     # 2120 on-air bits, the 2120 us maximum
EBN0_FULL = (12.0, 14.0, 16.0, 18.0)
DRIFT_HZ = 50e3


# ---------------------------------------------------------------- statistics

def _log_binom_cdf(k, n, p):
    """log P(X <= k) for X ~ Binomial(n, p), 0 < p < 1."""
    if k >= n:
        return 0.0
    lp, lq = math.log(p), math.log1p(-p)
    lg_n1 = math.lgamma(n + 1)
    terms = [lg_n1 - math.lgamma(i + 1) - math.lgamma(n - i + 1) + i * lp + (n - i) * lq
             for i in range(k + 1)]
    top = max(terms)
    return top + math.log(sum(math.exp(t - top) for t in terms))


def _solve(k, n, target):
    """Largest p in (0,1) with P(X <= k | p) = target; the CDF falls with p."""
    lo, hi = 0.0, 1.0
    lt = math.log(target)
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if mid <= 0.0 or mid >= 1.0:
            break
        if _log_binom_cdf(k, n, mid) > lt:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def clopper_pearson(errors, n, confidence=CONFIDENCE):
    """Two-sided exact interval (lower, upper) for ``errors`` of ``n``."""
    if not 0 <= errors <= n or n <= 0:
        raise ValueError("need 0 <= errors <= n and n > 0")
    alpha = 1.0 - confidence
    upper = 1.0 if errors == n else _solve(errors, n, alpha / 2.0)
    lower = 0.0 if errors == 0 else _solve(errors - 1, n, 1.0 - alpha / 2.0)
    return lower, upper


# --------------------------------------------------------------------- seeds

def point_seed(row_id, impairments, point_index, run_index, base_seed):
    """Stable 64-bit seed: SHA-256 of the canonical (row, impairments, point,
    run, base seed) tuple. Never Python's salted ``hash()``."""
    text = json.dumps([row_id, impairments, point_index, run_index, base_seed],
                      sort_keys=True, separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "big")


# --------------------------------------------------------------------- point

def _round(x):
    return float(f"{x:.9e}")


def run_point(row_id, point_index, params, payload_octets, packet_cap, min_errors,
              base_seed, run_index=0, flags=None):
    """Run one sweep point until ``min_errors`` bit errors or ``packet_cap`` packets."""
    desc = dict(params.describe(), payload_octets=payload_octets)
    seed = point_seed(row_id, desc, point_index, run_index, base_seed)
    rng = np.random.Generator(np.random.PCG64(seed))
    errors = bits = packets = sync_misses = crc_failures = clipped = samples = 0
    steps = 0
    while errors < min_errors and packets < packet_cap:
        payload = bytes(rng.integers(0, 256, payload_octets, dtype=np.uint8).tolist())
        header0 = int(rng.integers(0, 256))
        tx, _ = packet.build_frame_bits(payload, header0=header0)
        out = cm_a.generate_packet(tx, params, rng)
        ref = np.array(tx[40:], dtype=np.uint8)        # PDU + CRC
        rx = le1m_rx.demodulate(out.iq, out.flags, out.gain)
        packets += 1
        bits += len(ref)
        clipped += out.clipped
        samples += len(out.iq)
        if not rx["synced"]:
            sync_misses += 1
            errors += len(ref)                          # a missed packet loses every bit
            continue
        got = rx["bits"]
        m = min(len(got), len(ref))
        errors += int((got[:m] != ref[:m]).sum()) + (len(ref) - m)
        crc_failures += 0 if rx["crc_ok"] else 1
        steps += rx["timing_steps"]
    lower, upper = clopper_pearson(errors, bits)
    capped = errors < min_errors
    return {
        "row_id": row_id,
        "point_index": point_index,
        "run_index": run_index,
        "label": LABEL,
        "channel_model": "CM-A",
        "seed": seed,
        "ebn0_db": desc["ebn0_db"],
        "impairments": desc,
        "out_of_spec": bool(flags and flags.get("out_of_spec")),
        "negative_control": bool(flags and flags.get("negative_control")),
        "packets": packets,
        "bits": bits,
        "errors": errors,
        "ber": _round(errors / bits),
        "cp_lower": _round(lower),
        "cp_upper": _round(upper),
        "stopped_by": "packet_cap" if capped else "errors",
        "bound_only": capped,
        "sync_misses": sync_misses,
        "crc_failures": crc_failures,
        "timing_steps": steps,
        "clipped_samples": clipped,
        "samples": samples,
    }


# ---------------------------------------------------------------------- grid

def _p(**kw):
    return cm_a.CmAParams(**kw)


def full_grid():
    """(row_id, params, payload_octets, flags) for the ratified-row sweep."""
    pts = []
    for e in EBN0_FULL:
        for off in (-150e3, -100e3, -50e3, 0.0, 50e3, 100e3, 150e3):
            pts.append(("le1m_cfo", _p(ebn0_db=e, cfo_hz=off), PAYLOAD_TYPICAL, None))
    for e in EBN0_FULL:
        for off in (-SPEC_CFO_HZ, 0.0, SPEC_CFO_HZ):
            for profile in ("linear", "stepped"):
                for sign in (-1.0, 1.0):
                    pts.append(("le1m_drift", _p(ebn0_db=e, cfo_hz=off, drift_profile=profile,
                                                 drift_hz=sign * DRIFT_HZ), PAYLOAD_TYPICAL, None))
    for e in EBN0_FULL:
        for ppm in (-100.0, 0.0, 100.0):
            pts.append(("le1m_clock", _p(ebn0_db=e, cfo_hz=0.0, clock_ppm=ppm), PAYLOAD_MAX, None))
    for e in EBN0_FULL:
        pts.append(("le1m_uniform", _p(ebn0_db=e, draw_cfo=True, draw_clock=True), PAYLOAD_TYPICAL, None))
    return pts


def quick_grid():
    pts = []
    for e in (10.0, 16.0):
        for off in (0.0, SPEC_CFO_HZ, -SPEC_CFO_HZ):
            pts.append(("le1m_cfo", _p(ebn0_db=e, cfo_hz=off), PAYLOAD_TYPICAL, None))
    pts.append(("le1m_drift", _p(ebn0_db=16.0, cfo_hz=SPEC_CFO_HZ, drift_profile="linear",
                                 drift_hz=DRIFT_HZ), PAYLOAD_TYPICAL, None))
    pts.append(("le1m_drift", _p(ebn0_db=16.0, cfo_hz=-SPEC_CFO_HZ, drift_profile="stepped",
                                 drift_hz=-DRIFT_HZ), PAYLOAD_TYPICAL, None))
    for ppm in (-100.0, 100.0):
        pts.append(("le1m_clock", _p(ebn0_db=16.0, clock_ppm=ppm), PAYLOAD_MAX, None))
    pts.append(("negative_control", _p(ebn0_db=16.0, cfo_hz=NEGATIVE_CONTROL_CFO_HZ),
                PAYLOAD_TYPICAL, {"out_of_spec": True, "negative_control": True}))
    return pts


def _flag_out_of_spec(row_id, params, flags):
    flags = dict(flags or {})
    if not params.draw_cfo and abs(params.cfo_hz) > OUT_OF_SPEC_CFO_HZ:
        flags["out_of_spec"] = True
    return flags


# ------------------------------------------------------------------- summary

def row_summary(points):
    """Per-row report at the ratified Eb/N0. Reported, never asserted."""
    rows = {}
    for p in points:
        if p["negative_control"] or p["out_of_spec"] or p["ebn0_db"] != TARGET_EBN0_DB:
            continue
        r = rows.setdefault(p["row_id"], {"points": 0, "worst_cp_upper": 0.0,
                                          "all_points_measured": True})
        r["points"] += 1
        r["worst_cp_upper"] = max(r["worst_cp_upper"], p["cp_upper"])
        r["all_points_measured"] &= not p["bound_only"]
    for r in rows.values():
        r["ebn0_db"] = TARGET_EBN0_DB
        r["target_ber"] = TARGET_BER
        r["upper_bound_meets_target"] = r["worst_cp_upper"] <= TARGET_BER
        r["note"] = ("reported by this run; a capped point is an upper bound, not a measurement; "
                     "ratified-row claims need a separate evidence record")
    return {k: rows[k] for k in sorted(rows)}


def git_sha():
    try:
        root = subprocess.check_output(["git", "-C", SIM, "rev-parse", "--show-toplevel"],
                                       text=True, stderr=subprocess.DEVNULL).strip()
        sha = subprocess.check_output(["git", "-C", root, "rev-parse", "--short=12", "HEAD"],
                                      text=True, stderr=subprocess.DEVNULL).strip()
        dirty = subprocess.check_output(
            ["git", "-C", root, "status", "--porcelain", "--", "sim", ":!sim/results"],
            text=True, stderr=subprocess.DEVNULL).strip()
        return sha + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def default_out(sha):
    import datetime
    day = datetime.date.today().isoformat()
    return os.path.join(SIM, "results", f"{day}-{sha}", "ber.json")


def build_report(points, args, sha):
    return {
        "format": FORMAT,
        "label": LABEL,
        "channel_model": "CM-A",
        "mode": "quick" if args.quick else "full",
        "sim_git_sha": sha,
        "prng": {"family": "PCG64", "numpy_version": np.__version__},
        "base_seed": args.seed,
        "stop_rule": {"min_errors": args.min_errors, "packet_cap": args.packet_cap,
                      "max_length_packet_cap": args.max_length_packet_cap,
                      "confidence": CONFIDENCE, "interval": "Clopper-Pearson, two-sided",
                      "capped_point": "upper bound, not a measurement"},
        "channel": {"rx_rate_msps": cm_a.FS // 1_000_000, "rx_bits": cm_a.RX_BITS,
                    "agc": f"settled gain from whole-record rms of the noisy signal, "
                           f"target {cm_a.AGC_TARGET_RMS} LSB rms, 1.5 dB steps",
                    "noise": "complex white, full 8 MHz band, variance from Eb/N0"},
        "receiver": {"model": "sim/model/le1m_rx.py", "arithmetic": "integer",
                     "sync_threshold": f"{le1m_rx.SYNC_NUM}/{1 << le1m_rx.SYNC_DEN_SHIFT}",
                     "missed_packet_counts_as": "every PDU+CRC bit in error"},
        "points": points,
        "rows": row_summary(points),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="few points, small packet caps (CI)")
    ap.add_argument("--seed", type=int, default=1, help="base seed mixed into every point seed")
    ap.add_argument("--run-index", type=int, default=0)
    ap.add_argument("--min-errors", type=int, default=MIN_ERRORS)
    ap.add_argument("--packet-cap", type=int, default=None,
                    help="packets per point (default: quick 40, full 20000)")
    ap.add_argument("--max-length-packet-cap", type=int, default=None,
                    help="packets per max-length (2120 us) point (default: quick 6, full 3000)")
    ap.add_argument("--only", action="append", default=[], help="run only this row id (repeatable)")
    ap.add_argument("--out", default=None, help="ber.json path (default sim/results/<date>-<sha>/ber.json)")
    args = ap.parse_args(argv)
    if args.packet_cap is None:
        args.packet_cap = 40 if args.quick else 20000
    if args.max_length_packet_cap is None:
        args.max_length_packet_cap = 6 if args.quick else 3000

    grid = quick_grid() if args.quick else full_grid()
    points = []
    for idx, (row_id, params, payload, flags) in enumerate(grid):
        if args.only and row_id not in args.only:
            continue
        cap = args.max_length_packet_cap if payload == PAYLOAD_MAX else args.packet_cap
        flags = _flag_out_of_spec(row_id, params, flags)
        pt = run_point(row_id, idx, params, payload, cap, args.min_errors, args.seed,
                       args.run_index, flags)
        points.append(pt)
        print(f"{row_id:16s} #{idx:<3d} ebn0={pt['ebn0_db']!s:>5} errors={pt['errors']:<5d} "
              f"bits={pt['bits']:<8d} ber={pt['ber']:.3e} cp_upper={pt['cp_upper']:.3e} "
              f"{'CAPPED' if pt['bound_only'] else 'measured'}"
              f"{' OUT-OF-SPEC' if pt['out_of_spec'] else ''}", flush=True)

    sha = git_sha()
    out = args.out or default_out(sha)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    report = build_report(points, args, sha)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1, sort_keys=True)
        f.write("\n")
    for row_id, r in report["rows"].items():
        print(f"row {row_id}: worst cp_upper at {TARGET_EBN0_DB:g} dB = {r['worst_cp_upper']:.3e}; "
              f"upper bound meets {TARGET_BER:g}: {r['upper_bound_meets_target']} "
              f"(reported, not asserted)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
