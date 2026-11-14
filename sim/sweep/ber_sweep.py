#!/usr/bin/env python3
"""Seeded LE 1M BER sweep over CM-A with the integer non-coherent receiver.

Every point is labelled "simulated, CM-A". A point stops at ``--min-errors``
bit errors or at its packet cap; a capped point is an upper bound, not a
measurement (target-spec "Statistics"). Row verdicts use the 95 %
Clopper-Pearson **upper** bound, and are reported, not asserted. The CLI, the
stop rule, the seeding, the point-record envelope, the row verdict, the report
preamble and the shard/merge harness are ``sweep_common``'s.

    python3 sim/sweep/ber_sweep.py --quick            # CI mode, ~1 minute
    python3 sim/sweep/ber_sweep.py                    # full sweep, see sim/README.md
    python3 sim/sweep/ber_sweep.py --only ROW         # one shard: results/<date>-<sha>/shards/ROW.json
    python3 sim/sweep/ber_sweep.py --merge DIR        # assemble shards into ber.json
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import cm_a  # noqa: E402
import le1m_rx  # noqa: E402
import packet  # noqa: E402
import sweep_common  # noqa: E402

TARGET_BER = 1e-3
TARGET_EBN0_DB = 16.0
SPEC_CFO_HZ = 150e3
OUT_OF_SPEC_CFO_HZ = 250e3            # beyond the stretch row: flagged
NEGATIVE_CONTROL_CFO_HZ = 800e3       # far enough out that this receiver visibly fails
PAYLOAD_TYPICAL = 37                  # octets: 360 on-air bits
PAYLOAD_MAX = 255                     # 2120 on-air bits, the 2120 us maximum
EBN0_FULL = (12.0, 14.0, 16.0, 18.0)
DRIFT_HZ = 50e3
QUICK_MAX_LENGTH_PACKET_CAP = 6


# --------------------------------------------------------------------- point

def run_point(row_id, point_index, params, payload_octets, packet_cap, min_errors,
              base_seed, run_index=0, flags=None):
    """Run one sweep point until ``min_errors`` bit errors or ``packet_cap`` packets."""
    desc = dict(params.describe(), payload_octets=payload_octets)
    seed = sweep_common.point_seed(row_id, desc, point_index, run_index, base_seed)
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
    return sweep_common.point_record(
        row_id=row_id, point_index=point_index, run_index=run_index, seed=seed, desc=desc,
        flags=flags, x_key="ebn0_db", rate_key="ber", packets=packets, errors=errors,
        trials=bits, min_errors=min_errors, sync_misses=sync_misses, clipped_samples=clipped,
        samples=samples,
        extra={"bits": bits, "crc_failures": crc_failures, "timing_steps": steps})


# ---------------------------------------------------------------------- grid

def _p(**kw):
    return cm_a.CmAParams(**kw)


def _negative_control():
    return ("negative_control", _p(ebn0_db=16.0, cfo_hz=NEGATIVE_CONTROL_CFO_HZ),
            PAYLOAD_TYPICAL, {"out_of_spec": True, "negative_control": True})


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
    # Appended last: existing point indices, and so their seeds, must not move.
    pts.append(_negative_control())
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
    pts.append(_negative_control())
    return pts


def _flag_out_of_spec(params, flags):
    """Only a fixed offset past the stretch row puts an LE 1M point out of spec.

    ``clock_limit_ppm=None``: the +-100 ppm of ``le1m_clock`` is the declared
    extreme of the sweep, not a threshold to exceed, so this sweep has no
    out-of-spec clock row. The CFO guard fires on no current grid point other
    than the negative control (which flags itself) and is kept for a future
    out-of-spec row.
    """
    return sweep_common.flag_out_of_spec(params, flags, cfo_limit_hz=OUT_OF_SPEC_CFO_HZ,
                                         clock_limit_ppm=None)


# ------------------------------------------------------------------- summary

def row_summary(points):
    """Per-row report at the ratified Eb/N0. Reported, never asserted.

    ``inclusive=True``: LE 1M's documented verdict is ``<= 1e-3``
    (sim/README.md), unlike the PER sweep's ``< 1 %``."""
    return sweep_common.row_summary(points, x_key="ebn0_db", x_target=TARGET_EBN0_DB,
                                    target_field="target_ber", target=TARGET_BER,
                                    inclusive=True)


def build_report(points, args, sha):
    return dict(
        sweep_common.report_preamble(args, sha),
        channel={"rx_rate_msps": cm_a.FS // 1_000_000, "rx_bits": cm_a.RX_BITS,
                 "agc": f"settled gain from whole-record rms of the noisy signal, "
                        f"target {cm_a.AGC_TARGET_RMS} LSB rms, 1.5 dB steps",
                 "noise": "complex white, full 8 MHz band, variance from Eb/N0"},
        receiver={"model": "sim/model/le1m_rx.py", "arithmetic": "integer",
                  "sync_threshold": f"{le1m_rx.SYNC_NUM}/{1 << le1m_rx.SYNC_DEN_SHIFT}",
                  "missed_packet_counts_as": "every PDU+CRC bit in error"},
        points=points,
        rows=row_summary(points),
    )


def _progress(idx, row_id, params, pt):
    print(f"{row_id:16s} #{idx:<3d} ebn0={pt['ebn0_db']!s:>5} errors={pt['errors']:<5d} "
          f"bits={pt['bits']:<8d} ber={pt['ber']:.3e} cp_upper={pt['cp_upper']:.3e} "
          f"{'CAPPED' if pt['bound_only'] else 'measured'}"
          f"{' OUT-OF-SPEC' if pt['out_of_spec'] else ''}", flush=True)


def main(argv=None):
    ap = sweep_common.build_parser(
        __doc__,
        max_length_help="packets per max-length (2120 us) point (default: quick "
                        f"{QUICK_MAX_LENGTH_PACKET_CAP}, full "
                        f"{sweep_common.FULL_MAX_LENGTH_PACKET_CAP})",
        out_help="ber.json path (default sim/results/<date>-<sha>/ber.json; a single "
                 "--only row defaults to .../shards/<row>.json)",
        merge_help="merge the shard files in DIR into one full ber.json (writes --out, "
                   "default DIR/../ber.json); runs no simulation")
    args = ap.parse_args(argv)
    if args.merge:
        try:
            report = sweep_common.merge_shards(args.merge, full_grid=full_grid,
                                               build_report=build_report)
        except sweep_common.MergeError as e:
            print(f"merge refused: {e}", file=sys.stderr)
            return 1
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.merge)), "ber.json")
        sweep_common.write_report(report, out)
        print(f"merged {len(report['points'])} points into {out}")
        return 0
    sweep_common.apply_cap_defaults(args, quick_max_length_cap=QUICK_MAX_LENGTH_PACKET_CAP)

    grid = quick_grid() if args.quick else full_grid()
    sweep_common.check_only_rows(ap, args.only, grid)
    points = sweep_common.run_grid(grid, args, run_point=run_point,
                                   max_length_payload=PAYLOAD_MAX,
                                   flag_point=_flag_out_of_spec, progress=_progress)

    sha = sweep_common.git_sha()
    out = sweep_common.resolve_out(args, sha, "ber.json", shardable=True)
    report = build_report(points, args, sha)
    sweep_common.write_report(report, out)
    for row_id, r in report["rows"].items():
        print(f"row {row_id}: worst cp_upper at {TARGET_EBN0_DB:g} dB = {r['worst_cp_upper']:.3e}; "
              f"upper bound meets {TARGET_BER:g}: {r['upper_bound_meets_target']} "
              f"(reported, not asserted)")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
