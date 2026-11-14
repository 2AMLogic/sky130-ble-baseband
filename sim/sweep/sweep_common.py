#!/usr/bin/env python3
"""Scaffolding shared by every seeded error-rate sweep in this repo.

One copy of the parts that are not PHY-specific: the exact binomial interval,
the seed derivation, the CLI and its packet-cap defaults, the grid-run loop,
the point-record envelope, the per-row verdict, the report preamble, and the
shard/merge harness. A driver (``ber_sweep``, ``per_sweep``) keeps only what is
genuinely its own: its constants, its grids, its measurement loop and its
PHY-specific report sections.

Nothing here decides a *policy* question. The two documented asymmetries
between the drivers are parameters, not branches:

* the row verdict's inclusivity -- LE 1M reports ``worst_cp_upper <= 1e-3``
  (sim/README.md), 802.15.4 reports ``worst_cp_upper < 1 %`` -- is the
  ``inclusive`` argument of :func:`row_summary`;
* which impairments can put a point out of spec is the ``cfo_limit_hz`` /
  ``clock_limit_ppm`` pair of :func:`flag_out_of_spec`, both required, so a new
  driver has to state what it means rather than inherit someone else's limits.

Every report field name, grid order, point index and ``describe()`` key is the
drivers'; this module must not rename any of them. ``point_seed`` hashes the
impairment description and the grid index, so a renamed key or a reordered grid
moves every seed downstream of it.
"""

import argparse
import hashlib
import json
import math
import os
import subprocess

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)

LABEL = "simulated, CM-A"
CHANNEL_MODEL = "CM-A"
FORMAT = 1
CONFIDENCE = 0.95
MIN_ERRORS = 100
QUICK_PACKET_CAP = 40
FULL_PACKET_CAP = 20000
FULL_MAX_LENGTH_PACKET_CAP = 3000
NOTE = ("reported by this run; a capped point is an upper bound, not a measurement; "
        "ratified-row claims need a separate evidence record")


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


def _round(x):
    return float(f"{x:.9e}")


# ------------------------------------------------------------- point records

def point_record(*, row_id, point_index, run_index, seed, desc, flags, x_key, rate_key,
                 packets, errors, trials, min_errors, sync_misses, clipped_samples,
                 samples, extra=None):
    """The part of one sweep point that is the same for every PHY.

    ``trials`` is the denominator of the rate and of the interval -- on-air bits
    for a BER sweep, packets for a PER sweep. ``extra`` carries the driver's own
    keys (``bits``/``crc_failures``/``timing_steps``, ``fcs_failures``); it is
    applied last, so a driver can neither silently drop a shared key nor get a
    PHY-specific one renamed here.
    """
    lower, upper = clopper_pearson(errors, trials)
    capped = errors < min_errors
    record = {
        "row_id": row_id,
        "point_index": point_index,
        "run_index": run_index,
        "label": LABEL,
        "channel_model": CHANNEL_MODEL,
        "seed": seed,
        x_key: desc[x_key],
        "impairments": desc,
        "out_of_spec": bool(flags and flags.get("out_of_spec")),
        "negative_control": bool(flags and flags.get("negative_control")),
        "packets": packets,
        "errors": errors,
        rate_key: _round(errors / trials),
        "cp_lower": _round(lower),
        "cp_upper": _round(upper),
        "stopped_by": "packet_cap" if capped else "errors",
        "bound_only": capped,
        "sync_misses": sync_misses,
        "clipped_samples": clipped_samples,
        "samples": samples,
    }
    record.update(extra or {})
    return record


# ----------------------------------------------------------------- out of spec

def flag_out_of_spec(params, flags, *, cfo_limit_hz, clock_limit_ppm):
    """Mark a grid point out of spec when a fixed impairment exceeds its limit.

    Both limits are required and either may be ``None`` to mean "this sweep
    declares no out-of-spec row for that impairment". A drawn impairment
    (``draw_cfo`` / ``draw_clock``) is never flagged: the draw stays inside its
    own declared range, and the description records "uniform", not a value.
    """
    flags = dict(flags or {})
    if cfo_limit_hz is not None and not params.draw_cfo and abs(params.cfo_hz) > cfo_limit_hz:
        flags["out_of_spec"] = True
    if (clock_limit_ppm is not None and not params.draw_clock
            and abs(params.clock_ppm) > clock_limit_ppm):
        flags["out_of_spec"] = True
    return flags


# ------------------------------------------------------------------- summary

def row_summary(points, *, x_key, x_target, target_field, target, inclusive):
    """Per-row report at the ratified operating point. Reported, never asserted.

    ``inclusive`` selects ``<= target`` (LE 1M's documented <= 1e-3) or
    ``< target`` (802.15.4's documented < 1 %). Negative-control and
    out-of-spec points are excluded from every row.
    """
    rows = {}
    for p in points:
        if p["negative_control"] or p["out_of_spec"] or p[x_key] != x_target:
            continue
        r = rows.setdefault(p["row_id"], {"points": 0, "worst_cp_upper": 0.0,
                                          "all_points_measured": True})
        r["points"] += 1
        r["worst_cp_upper"] = max(r["worst_cp_upper"], p["cp_upper"])
        r["all_points_measured"] &= not p["bound_only"]
    for r in rows.values():
        r[x_key] = x_target
        r[target_field] = target
        r["upper_bound_meets_target"] = bool(r["worst_cp_upper"] <= target if inclusive
                                             else r["worst_cp_upper"] < target)
        r["note"] = NOTE
    return {k: rows[k] for k in sorted(rows)}


# ---------------------------------------------------------------------- CLI

def build_parser(doc, *, max_length_help, out_help, merge_help=None):
    """The sweep CLI. ``merge_help`` adds ``--merge`` for a sharded sweep."""
    ap = argparse.ArgumentParser(description=doc, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="few points, small packet caps (CI)")
    ap.add_argument("--seed", type=int, default=1, help="base seed mixed into every point seed")
    ap.add_argument("--run-index", type=int, default=0)
    ap.add_argument("--min-errors", type=int, default=MIN_ERRORS)
    ap.add_argument("--packet-cap", type=int, default=None,
                    help=f"packets per point (default: quick {QUICK_PACKET_CAP}, "
                         f"full {FULL_PACKET_CAP})")
    ap.add_argument("--max-length-packet-cap", type=int, default=None, help=max_length_help)
    ap.add_argument("--only", action="append", default=[], help="run only this row id (repeatable)")
    ap.add_argument("--out", default=None, help=out_help)
    if merge_help is not None:
        ap.add_argument("--merge", metavar="DIR", default=None, help=merge_help)
    return ap


def apply_cap_defaults(args, *, quick_max_length_cap):
    """Fill the two packet caps the driver left at ``None``."""
    if args.packet_cap is None:
        args.packet_cap = QUICK_PACKET_CAP if args.quick else FULL_PACKET_CAP
    if args.max_length_packet_cap is None:
        args.max_length_packet_cap = (quick_max_length_cap if args.quick
                                      else FULL_MAX_LENGTH_PACKET_CAP)


def check_only_rows(ap, only, grid):
    """``ap.error`` (exit 2) on a ``--only`` row id this grid does not have."""
    unknown = sorted(set(only) - {g[0] for g in grid})
    if unknown:
        ap.error(f"unknown row id(s): {', '.join(unknown)}")


# --------------------------------------------------------------- grid runner

def run_grid(grid, args, *, run_point, max_length_payload, flag_point, progress):
    """Run the selected grid points in index order, returning their records.

    The grid index is the point index -- it is part of every seed, so a skipped
    (``--only``) point must not renumber the ones that follow it.
    """
    points = []
    for idx, (row_id, params, payload, flags) in enumerate(grid):
        if args.only and row_id not in args.only:
            continue
        cap = args.max_length_packet_cap if payload == max_length_payload else args.packet_cap
        pt = run_point(row_id, idx, params, payload, cap, args.min_errors, args.seed,
                       args.run_index, flag_point(params, flags))
        points.append(pt)
        progress(idx, row_id, params, pt)
    return points


# -------------------------------------------------------------------- report

def report_preamble(args, sha):
    """The report header every sweep writes, from the parsed arguments."""
    return {
        "format": FORMAT,
        "label": LABEL,
        "channel_model": CHANNEL_MODEL,
        "mode": "quick" if args.quick else "full",
        "sim_git_sha": sha,
        "prng": {"family": "PCG64", "numpy_version": np.__version__},
        "base_seed": args.seed,
        "stop_rule": {"min_errors": args.min_errors, "packet_cap": args.packet_cap,
                      "max_length_packet_cap": args.max_length_packet_cap,
                      "confidence": CONFIDENCE, "interval": "Clopper-Pearson, two-sided",
                      "capped_point": "upper bound, not a measurement"},
    }


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


def results_dir(sha):
    import datetime
    day = datetime.date.today().isoformat()
    return os.path.join(SIM, "results", f"{day}-{sha}")


def default_out(sha, filename):
    return os.path.join(results_dir(sha), filename)


def shard_out(sha, row_id):
    """Deterministic shard path for one row, beside where the report would go."""
    return os.path.join(results_dir(sha), "shards", f"{row_id}.json")


def resolve_out(args, sha, filename, *, shardable):
    """``--out`` wins; otherwise a single-row ``--only`` run of a sharded sweep
    writes its shard file, and anything else writes the report itself."""
    if args.out:
        return args.out
    if shardable and len(set(args.only)) == 1:
        return shard_out(sha, args.only[0])
    return default_out(sha, filename)


def write_report(report, out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------- shards and merge

class MergeError(Exception):
    pass


def merge_shards(shard_dir, *, full_grid, build_report):
    """Assemble the full-grid report from per-row shard files in ``shard_dir``.

    ``full_grid`` and ``build_report`` are the calling driver's, so the merge
    recomputes ``rows`` with that driver's own verdict rule.

    Refuses (MergeError naming the row where there is one) on a missing,
    duplicate or partial row, on shards that disagree on seed / run index /
    mode / stop rule / SHA, and on a dirty-SHA or quick-mode shard."""
    names = sorted(n for n in os.listdir(shard_dir) if n.endswith(".json"))
    if not names:
        raise MergeError(f"no shard files in {shard_dir}")
    shards = []
    for n in names:
        with open(os.path.join(shard_dir, n), encoding="utf-8") as f:
            shards.append((n, json.load(f)))
    first = shards[0][1]
    for n, rep in shards:
        if rep.get("mode") != "full":
            raise MergeError(f"{n}: mode is {rep.get('mode')!r}, only full-mode shards merge")
        if str(rep.get("sim_git_sha", "")).endswith("-dirty") or rep.get("sim_git_sha") == "unknown":
            raise MergeError(f"{n}: sim_git_sha {rep.get('sim_git_sha')!r} is not a clean commit")
        for key in ("base_seed", "stop_rule", "sim_git_sha", "mode"):
            if rep.get(key) != first.get(key):
                raise MergeError(f"{n}: {key} {rep.get(key)!r} disagrees with "
                                 f"{shards[0][0]} ({first.get(key)!r})")
    runs = {p["run_index"] for _, rep in shards for p in rep["points"]}
    if len(runs) != 1:
        raise MergeError(f"shards disagree on run_index: {sorted(runs)}")

    owner, points = {}, []
    for n, rep in shards:
        for row in {p["row_id"] for p in rep["points"]}:
            if row in owner:
                raise MergeError(f"duplicate row {row}: in {owner[row]} and {n}")
            owner[row] = n
        points.extend(rep["points"])
    want = {}
    for idx, (row, *_rest) in enumerate(full_grid()):
        want.setdefault(row, set()).add(idx)
    for row in want:
        have = {p["point_index"] for p in points if p["row_id"] == row}
        if row not in owner:
            raise MergeError(f"missing row {row}")
        if have != want[row]:
            raise MergeError(f"row {row}: point indices {sorted(have)} != expected {sorted(want[row])}")
    for row in owner:
        if row not in want:
            raise MergeError(f"unexpected row {row}")
    points.sort(key=lambda p: p["point_index"])
    sr = first["stop_rule"]
    args = argparse.Namespace(quick=False, seed=first["base_seed"], min_errors=sr["min_errors"],
                              packet_cap=sr["packet_cap"],
                              max_length_packet_cap=sr["max_length_packet_cap"])
    return build_report(points, args, first["sim_git_sha"])
