#!/usr/bin/env python3
"""Seeded 802.15.4 PER sweep over CM-A with the integer non-coherent receiver.

Every point is labelled "simulated, CM-A". A point stops at ``--min-errors``
packet errors or at its packet cap; a capped point is an upper bound, not a
measurement (target-spec "Statistics"). Row verdicts use the 95 %
Clopper-Pearson **upper** bound, and are reported, not asserted. Seeding, the
interval and the report conventions are ``ber_sweep``'s.

    python3 sim/sweep/per_sweep.py --quick            # CI mode
    python3 sim/sweep/per_sweep.py                    # full sweep, see sim/README.md
    python3 sim/sweep/per_sweep.py --only ROW         # one or more rows
"""

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import ber_sweep  # noqa: E402  (statistics, seeds, report writing)
import cm_a_oqpsk  # noqa: E402
import oqpsk_rx  # noqa: E402
import oqpsk_tx  # noqa: E402

LABEL = ber_sweep.LABEL
FORMAT = 1
CONFIDENCE = ber_sweep.CONFIDENCE
MIN_ERRORS = ber_sweep.MIN_ERRORS
TARGET_PER = 0.01
TARGET_SNR_DB = 5.0
PSDU_TYPICAL = 20                       # octets, FCS included
PSDU_MAX = oqpsk_tx.MAX_PSDU_OCTETS     # 127
SNR_ROW = (-1.0, 1.0, 3.0, 5.0, 7.0, 9.0)
SNR_OFFSET_ROWS = (3.0, 5.0, 7.0)       # stretch, target, fallback
CFO_GRID_HZ = tuple(f * cm_a_oqpsk.CFO_SPEC_HZ / 4.0 for f in range(-4, 5))   # both +-196 kHz ends
CLOCK_GRID_PPM = (-cm_a_oqpsk.CLOCK_SPEC_PPM, 0.0, cm_a_oqpsk.CLOCK_SPEC_PPM)
NEGATIVE_CONTROL_CFO_HZ = 800e3         # far outside +-196 kHz
NEGATIVE_CONTROL_SNR_DB = 9.0           # comfortably above the target SNR


def _p(**kw):
    return cm_a_oqpsk.OqpskParams(**kw)


def run_point(row_id, point_index, params, psdu_octets, packet_cap, min_errors,
              base_seed, run_index=0, flags=None):
    """Run one sweep point until ``min_errors`` packet errors or ``packet_cap`` packets.
    A packet is in error unless it is detected and its PSDU (FCS included) is
    returned bit-exact with the FCS passing."""
    desc = dict(params.describe(), psdu_octets=psdu_octets)
    seed = ber_sweep.point_seed(row_id, desc, point_index, run_index, base_seed)
    rng = np.random.Generator(np.random.PCG64(seed))
    errors = packets = sync_misses = fcs_failures = clipped = samples = 0
    while errors < min_errors and packets < packet_cap:
        body = bytes(rng.integers(0, 256, psdu_octets - 2, dtype=np.uint8).tolist())
        psdu = oqpsk_tx.with_fcs(body)
        out = cm_a_oqpsk.generate_packet(psdu, params, rng)
        rx = oqpsk_rx.demodulate(out.iq, out.flags, out.gain)
        packets += 1
        clipped += out.clipped
        samples += len(out.iq)
        if not rx["synced"]:
            sync_misses += 1
            errors += 1
        elif not rx["crc_ok"] or rx["psdu"] != psdu:
            fcs_failures += 0 if rx["crc_ok"] else 1
            errors += 1
    lower, upper = ber_sweep.clopper_pearson(errors, packets)
    capped = errors < min_errors
    r = ber_sweep._round
    return {
        "row_id": row_id,
        "point_index": point_index,
        "run_index": run_index,
        "label": LABEL,
        "channel_model": "CM-A",
        "seed": seed,
        "snr_db": desc["snr_db"],
        "impairments": desc,
        "out_of_spec": bool(flags and flags.get("out_of_spec")),
        "negative_control": bool(flags and flags.get("negative_control")),
        "packets": packets,
        "errors": errors,
        "per": r(errors / packets),
        "cp_lower": r(lower),
        "cp_upper": r(upper),
        "stopped_by": "packet_cap" if capped else "errors",
        "bound_only": capped,
        "sync_misses": sync_misses,
        "fcs_failures": fcs_failures,
        "clipped_samples": clipped,
        "samples": samples,
    }


# ---------------------------------------------------------------------- grid

def _negative_control():
    return ("negative_control", _p(snr_db=NEGATIVE_CONTROL_SNR_DB, cfo_hz=NEGATIVE_CONTROL_CFO_HZ),
            PSDU_TYPICAL, {"out_of_spec": True, "negative_control": True})


def full_grid():
    """(row_id, params, psdu_octets, flags) for the ratified-row sweep."""
    pts = []
    for snr in SNR_ROW:
        pts.append(("per_snr", _p(snr_db=snr), PSDU_TYPICAL, None))
    for snr in SNR_OFFSET_ROWS:
        for cfo in CFO_GRID_HZ:
            pts.append(("per_cfo", _p(snr_db=snr, cfo_hz=cfo), PSDU_TYPICAL, None))
    for snr in SNR_OFFSET_ROWS:
        for ppm in CLOCK_GRID_PPM:
            pts.append(("per_clock", _p(snr_db=snr, clock_ppm=ppm), PSDU_MAX, None))
    # Appended last: existing point indices, and so their seeds, must not move.
    pts.append(_negative_control())
    return pts


def quick_grid():
    ext = cm_a_oqpsk.CFO_SPEC_HZ
    pts = [("per_snr", _p(snr_db=snr), PSDU_TYPICAL, None) for snr in (3.0, 9.0)]
    pts += [("per_cfo", _p(snr_db=TARGET_SNR_DB, cfo_hz=cfo), PSDU_TYPICAL, None)
            for cfo in (-ext, 0.0, ext)]
    pts += [("per_clock", _p(snr_db=TARGET_SNR_DB, clock_ppm=ppm), PSDU_MAX, None)
            for ppm in (-cm_a_oqpsk.CLOCK_SPEC_PPM, cm_a_oqpsk.CLOCK_SPEC_PPM)]
    pts.append(_negative_control())
    return pts


def _flag_out_of_spec(params, flags):
    flags = dict(flags or {})
    if not params.draw_cfo and abs(params.cfo_hz) > cm_a_oqpsk.CFO_SPEC_HZ + 1e-6:
        flags["out_of_spec"] = True
    if not params.draw_clock and abs(params.clock_ppm) > cm_a_oqpsk.CLOCK_SPEC_PPM:
        flags["out_of_spec"] = True
    return flags


# ------------------------------------------------------------------- summary

def row_summary(points):
    """Per-row report at the ratified SNR. Reported, never asserted."""
    rows = {}
    for p in points:
        if p["negative_control"] or p["out_of_spec"] or p["snr_db"] != TARGET_SNR_DB:
            continue
        r = rows.setdefault(p["row_id"], {"points": 0, "worst_cp_upper": 0.0,
                                          "all_points_measured": True})
        r["points"] += 1
        r["worst_cp_upper"] = max(r["worst_cp_upper"], p["cp_upper"])
        r["all_points_measured"] &= not p["bound_only"]
    for r in rows.values():
        r["snr_db"] = TARGET_SNR_DB
        r["target_per"] = TARGET_PER
        r["upper_bound_meets_target"] = r["worst_cp_upper"] < TARGET_PER
        r["note"] = ("reported by this run; a capped point is an upper bound, not a measurement; "
                     "ratified-row claims need a separate evidence record")
    return {k: rows[k] for k in sorted(rows)}


def control_summary(points):
    """The negative control must fail the row: its upper bound is >= the target."""
    ctl = [p for p in points if p["negative_control"]]
    if not ctl:
        return None
    return {"row_id": ctl[0]["row_id"], "cp_upper": ctl[0]["cp_upper"], "target_per": TARGET_PER,
            "fails_row": bool(ctl[0]["cp_upper"] >= TARGET_PER)}


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
        "channel": {"rx_rate_msps": cm_a_oqpsk.FS // 1_000_000, "rx_bits": ber_sweep.cm_a.RX_BITS,
                    "agc": f"settled gain from whole-record rms of the noisy signal, "
                           f"target {ber_sweep.cm_a.AGC_TARGET_RMS} LSB rms, 1.5 dB steps",
                    "noise": "complex white, full 8 MHz band; SNR defined in a 2 MHz noise bandwidth"},
        "receiver": {"model": "sim/model/oqpsk_rx.py", "arithmetic": "integer",
                     "packet_error": "not synced, FCS fail, or PSDU not returned exactly"},
        "points": points,
        "rows": row_summary(points),
        "negative_control": control_summary(points),
    }


def default_out(sha):
    return os.path.join(os.path.dirname(ber_sweep.default_out(sha)), "per.json")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="few points, small packet caps (CI)")
    ap.add_argument("--seed", type=int, default=1, help="base seed mixed into every point seed")
    ap.add_argument("--run-index", type=int, default=0)
    ap.add_argument("--min-errors", type=int, default=MIN_ERRORS)
    ap.add_argument("--packet-cap", type=int, default=None,
                    help="packets per point (default: quick 40, full 20000)")
    ap.add_argument("--max-length-packet-cap", type=int, default=None,
                    help="packets per 127-octet point (default: quick 10, full 3000)")
    ap.add_argument("--only", action="append", default=[], help="run only this row id (repeatable)")
    ap.add_argument("--out", default=None, help="per.json path (default sim/results/<date>-<sha>/per.json)")
    args = ap.parse_args(argv)
    if args.packet_cap is None:
        args.packet_cap = 40 if args.quick else 20000
    if args.max_length_packet_cap is None:
        args.max_length_packet_cap = 10 if args.quick else 3000

    grid = quick_grid() if args.quick else full_grid()
    unknown = sorted(set(args.only) - {g[0] for g in grid})
    if unknown:
        ap.error(f"unknown row id(s): {', '.join(unknown)}")
    points = []
    for idx, (row_id, params, psdu, flags) in enumerate(grid):
        if args.only and row_id not in args.only:
            continue
        cap = args.max_length_packet_cap if psdu == PSDU_MAX else args.packet_cap
        flags = _flag_out_of_spec(params, flags)
        pt = run_point(row_id, idx, params, psdu, cap, args.min_errors, args.seed,
                       args.run_index, flags)
        points.append(pt)
        print(f"{row_id:16s} #{idx:<3d} snr={pt['snr_db']!s:>5} cfo={params.cfo_hz:>9.0f} "
              f"errors={pt['errors']:<5d} packets={pt['packets']:<6d} per={pt['per']:.3e} "
              f"cp_upper={pt['cp_upper']:.3e} {'CAPPED' if pt['bound_only'] else 'measured'}"
              f"{' OUT-OF-SPEC' if pt['out_of_spec'] else ''}", flush=True)

    sha = ber_sweep.git_sha()
    out = args.out or default_out(sha)
    report = build_report(points, args, sha)
    ber_sweep.write_report(report, out)
    for row_id, r in report["rows"].items():
        print(f"row {row_id}: worst cp_upper at {TARGET_SNR_DB:g} dB = {r['worst_cp_upper']:.3e}; "
              f"upper bound below {TARGET_PER:g}: {r['upper_bound_meets_target']} (reported, not asserted)")
    ctl = report["negative_control"]
    if ctl:
        print(f"negative control: cp_upper {ctl['cp_upper']:.3e}, fails the row: {ctl['fails_row']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
