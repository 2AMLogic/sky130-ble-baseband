#!/usr/bin/env python3
"""Seeded 802.15.4 PER sweep over CM-A with the integer non-coherent receiver.

Every point is labelled "simulated, CM-A". A point stops at ``--min-errors``
packet errors or at its packet cap; a capped point is an upper bound, not a
measurement (target-spec "Statistics"). Row verdicts use the 95 %
Clopper-Pearson **upper** bound, and are reported, not asserted. The CLI, the
stop rule, the seeding, the point-record envelope, the row verdict and the
report preamble are ``sweep_common``'s.

    python3 sim/sweep/per_sweep.py --quick            # CI mode
    python3 sim/sweep/per_sweep.py                    # full sweep, see sim/README.md
    python3 sim/sweep/per_sweep.py --only ROW         # one or more rows
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [HERE, os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import cm_a  # noqa: E402  (the shared CM-A receive chain: RX width, AGC target)
import cm_a_oqpsk  # noqa: E402
import oqpsk_rx  # noqa: E402
import oqpsk_tx  # noqa: E402
import sweep_common  # noqa: E402

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
QUICK_MAX_LENGTH_PACKET_CAP = 10


def _p(**kw):
    return cm_a_oqpsk.OqpskParams(**kw)


def run_point(row_id, point_index, params, psdu_octets, packet_cap, min_errors,
              base_seed, run_index=0, flags=None):
    """Run one sweep point until ``min_errors`` packet errors or ``packet_cap`` packets.
    A packet is in error unless it is detected and its PSDU (FCS included) is
    returned bit-exact with the FCS passing."""
    desc = dict(params.describe(), psdu_octets=psdu_octets)
    seed = sweep_common.point_seed(row_id, desc, point_index, run_index, base_seed)
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
    return sweep_common.point_record(
        row_id=row_id, point_index=point_index, run_index=run_index, seed=seed, desc=desc,
        flags=flags, x_key="snr_db", rate_key="per", packets=packets, errors=errors,
        trials=packets, min_errors=min_errors, sync_misses=sync_misses, clipped_samples=clipped,
        samples=samples, extra={"fcs_failures": fcs_failures})


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
    """Either a fixed offset past +-196 kHz or a fixed chip clock past +-80 ppm
    puts an 802.15.4 point out of spec. The 1e-6 Hz slack keeps the pinned
    +-CFO_SPEC_HZ grid ends in spec against float rounding."""
    return sweep_common.flag_out_of_spec(
        params, flags, cfo_limit_hz=cm_a_oqpsk.CFO_SPEC_HZ + 1e-6,
        clock_limit_ppm=cm_a_oqpsk.CLOCK_SPEC_PPM)


# ------------------------------------------------------------------- summary

def row_summary(points):
    """Per-row report at the ratified SNR. Reported, never asserted.

    ``inclusive=False``: 802.15.4's documented verdict is ``< 1 %``
    (sim/README.md), unlike the BER sweep's ``<= 1e-3``."""
    return sweep_common.row_summary(points, x_key="snr_db", x_target=TARGET_SNR_DB,
                                    target_field="target_per", target=TARGET_PER,
                                    inclusive=False)


def control_summary(points):
    """The negative control must fail the row: its upper bound is >= the target."""
    ctl = [p for p in points if p["negative_control"]]
    if not ctl:
        return None
    return {"row_id": ctl[0]["row_id"], "cp_upper": ctl[0]["cp_upper"], "target_per": TARGET_PER,
            "fails_row": bool(ctl[0]["cp_upper"] >= TARGET_PER)}


def build_report(points, args, sha):
    return dict(
        sweep_common.report_preamble(args, sha),
        channel={"rx_rate_msps": cm_a_oqpsk.FS // 1_000_000, "rx_bits": cm_a.RX_BITS,
                 "agc": f"settled gain from whole-record rms of the noisy signal, "
                        f"target {cm_a.AGC_TARGET_RMS} LSB rms, 1.5 dB steps",
                 "noise": "complex white, full 8 MHz band; SNR defined in a 2 MHz noise bandwidth"},
        receiver={"model": "sim/model/oqpsk_rx.py", "arithmetic": "integer",
                  "packet_error": "not synced, FCS fail, or PSDU not returned exactly"},
        points=points,
        rows=row_summary(points),
        negative_control=control_summary(points),
    )


def _progress(idx, row_id, params, pt):
    print(f"{row_id:16s} #{idx:<3d} snr={pt['snr_db']!s:>5} cfo={params.cfo_hz:>9.0f} "
          f"errors={pt['errors']:<5d} packets={pt['packets']:<6d} per={pt['per']:.3e} "
          f"cp_upper={pt['cp_upper']:.3e} {'CAPPED' if pt['bound_only'] else 'measured'}"
          f"{' OUT-OF-SPEC' if pt['out_of_spec'] else ''}", flush=True)


def main(argv=None):
    ap = sweep_common.build_parser(
        __doc__,
        max_length_help="packets per 127-octet point (default: quick "
                        f"{QUICK_MAX_LENGTH_PACKET_CAP}, full "
                        f"{sweep_common.FULL_MAX_LENGTH_PACKET_CAP})",
        out_help="per.json path (default sim/results/<date>-<sha>/per.json)")
    args = ap.parse_args(argv)
    sweep_common.apply_cap_defaults(args, quick_max_length_cap=QUICK_MAX_LENGTH_PACKET_CAP)

    grid = quick_grid() if args.quick else full_grid()
    sweep_common.check_only_rows(ap, args.only, grid)
    points = sweep_common.run_grid(grid, args, run_point=run_point,
                                   max_length_payload=PSDU_MAX,
                                   flag_point=_flag_out_of_spec, progress=_progress)

    sha = sweep_common.git_sha()
    out = sweep_common.resolve_out(args, sha, "per.json", shardable=False)
    report = build_report(points, args, sha)
    sweep_common.write_report(report, out)
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
