#!/usr/bin/env python3
"""802.15.4 PER sensitivity budget: where the reference receiver's dB go (issue #137).

The committed `per_snr` row misses the ratified PER ceiling: PER < 1 % (95 %
Clopper-Pearson upper bound) is first reached at the 9 dB grid point against a
5 dB target and a 7 dB fallback (`spec/target-spec.md`, "Demodulator
performance"). This script attributes the gap. It changes no committed
behaviour: the receiver's acquisition constants are module globals read at
call time, so each variant overrides them from outside (`oqpsk_rx.MIN_AMPLITUDE`,
`ACCEPT_NUM`/`ACCEPT_DEN_SHIFT`, `PREAMBLE_RUN`) and every run asserts the
override actually took effect before trusting a delta.

What it measures, per acceptance criterion of issue #137:

1. Error-class split at the `per_snr` points: `sync_misses`, `fcs_failures`,
   and the residual `errors - sync_misses - fcs_failures` (a packet that syncs,
   passes FCS and still returns a wrong PSDU lands only in the residual).
2. The acquisition gate's contribution, one constant at a time: each variant's
   PER and CP upper bound at 5/7/8/9 dB against the unmodified baseline, and
   the SNR at which it first reaches PER < 1 % within the stated cap.
3. The AGC / 8-bit quantization contribution: the same packets through the
   integer model with the input quantization refined to 1/2**FRAC_BITS LSB.
   The scaling choice: float IQ (pre-gain, `ChannelOutput.float_iq`) is scaled
   by the recorded AGC gain and by 2**FRAC_BITS, and `FIR_OUT_BITS` is raised
   to 9 + FRAC_BITS so the channel FIR does not clip the finer grid. The
   delay-and-multiply discriminator is a CORDIC *angle*, invariant to positive
   scaling, so every downstream threshold keeps its meaning. FRAC_BITS=0
   reproduces the committed int8 path bit-exactly (asserted at startup and
   per packet).
4. The crossing bracket, finer than the committed 2 dB grid: baseline points
   at 7.5, 8 and 8.5 dB.

Every point is labelled "simulated, CM-A" (``ber_sweep.LABEL``), carries its
seed, run index, packet cap and stop rule, and marks a capped point
`bound_only`: an upper bound, not a measurement. Statistics and seed derivation
are ``ber_sweep``'s (``clopper_pearson``, ``point_seed``), so a point with the
committed constants and caps reproduces the committed sweep exactly; the
script asserts that against the committed 5/7/9 dB reference before any
variant delta is reported. Same-machine identity only (sim/README.md
"Determinism").

Runs single-threaded, pure Python/NumPy: not a SPICE grid, nothing is
submitted anywhere.

    python3 sim/analysis/oqpsk_sensitivity_budget.py --quick     # smoke (< 1 min)
    python3 sim/analysis/oqpsk_sensitivity_budget.py            # full budget
    python3 sim/analysis/oqpsk_sensitivity_budget.py --out PATH # JSON report path
"""

import argparse
import datetime
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SIM = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(SIM, "sweep"), os.path.join(SIM, "channel"), os.path.join(SIM, "model")]
import ber_sweep  # noqa: E402
import cm_a  # noqa: E402
import cm_a_oqpsk  # noqa: E402
import le1m_rx  # noqa: E402
import oqpsk_rx  # noqa: E402
import per_sweep  # noqa: E402

FORMAT = 1
LABEL = ber_sweep.LABEL
ROW_ID = "per_snr"
PSDU_OCTETS = per_sweep.PSDU_TYPICAL

# Committed grid indices first (seeds must match the committed sweep), then
# this analysis's finer points; desc carries snr_db, so seeds are unique anyway.
SNR_POINT_INDEX = {-1.0: 0, 1.0: 1, 3.0: 2, 5.0: 3, 7.0: 4, 9.0: 5,
                   7.5: 6, 8.0: 7, 8.5: 8}
BASELINE_SNRS = (-1.0, 1.0, 3.0, 5.0, 7.0, 7.5, 8.0, 8.5, 9.0)
BRACKET_SNRS = (7.5, 8.0, 8.5)          # AC 4: tighten the (7, 9] dB crossing bracket
VARIANT_SNRS = (5.0, 7.0, 8.0, 9.0)
QUANT_SNRS = (5.0, 7.0, 8.0)

FRAC_BITS = 4                           # input quantization step 1/16 LSB in the fine arm

# The committed evidence this analysis is attributed against
# (sim/results/2026-11-14-1564a0ec0cfb/per.json, --seed 1 --run-index 0,
# default caps; quoted in issue #137). Asserted before any variant delta.
COMMITTED_REFERENCE = (
    (5.0, {"packets": 229, "errors": 100, "cp_upper": 0.504}),
    (7.0, {"packets": 2462, "errors": 100, "cp_upper": 0.0492}),
    (9.0, {"packets": 20000, "errors": 11, "cp_upper": 9.84e-4}),
)

# One constant at a time, against the committed values
# (MIN_AMPLITUDE 4096, ACCEPT_NUM/ACCEPT_DEN_SHIFT 3/2, PREAMBLE_RUN 4).
VARIANTS = (
    ("baseline", {}),
    ("minamp_2048", {"MIN_AMPLITUDE": 2048}),
    ("minamp_1024", {"MIN_AMPLITUDE": 1024}),
    ("floor_only", {"ACCEPT_NUM": -1, "ACCEPT_DEN_SHIFT": 0}),   # ratio term cannot bind
    ("ratio_only", {"MIN_AMPLITUDE": 0}),                        # absolute floor cannot bind
    ("ratio_half", {"ACCEPT_NUM": 1, "ACCEPT_DEN_SHIFT": 1}),    # corr >= mag/2: >= 75 % weighted agreement
    ("prerun_2", {"PREAMBLE_RUN": 2}),
)

# Constants with a behavioural call-time path through _accept / channel_filter;
# probed, not just attribute-compared. PREAMBLE_RUN / MAX_PREAMBLE_SYMBOLS are
# read at call time too (oqpsk_rx.demodulate) and are covered by the attribute
# assertion.
GATE_KEYS = ("MIN_AMPLITUDE", "ACCEPT_NUM", "ACCEPT_DEN_SHIFT")

# Everything an arm may override. A misspelled constant name must be refused
# here, not silently setattr'd into a new module attribute while the model runs
# with its committed value.
OVERRIDABLE_KEYS = ("MIN_AMPLITUDE", "ACCEPT_NUM", "ACCEPT_DEN_SHIFT",
                    "PREAMBLE_RUN", "MAX_PREAMBLE_SYMBOLS", "FIR_OUT_BITS")


# ------------------------------------------------------------------ overrides

def _accept_from(min_amplitude, accept_num, accept_den_shift, corr, mag):
    """``oqpsk_rx._accept``'s predicate from explicit constants."""
    floor = min_amplitude * oqpsk_rx.NTAPS
    return bool(corr >= floor and (corr << accept_den_shift) >= accept_num * mag)


def _gate_probe_point(committed, variant):
    """A (corr, mag) point where the accept predicate must disagree between the
    committed gate constants and the variant's, or None when they are
    numerically the same gate."""
    f0 = committed["MIN_AMPLITUDE"] * oqpsk_rx.NTAPS
    f1 = variant["MIN_AMPLITUDE"] * oqpsk_rx.NTAPS
    mags = (1, 8, 4096, 1 << 12, 1 << 16, 1 << 20, f0 * 4, 1 << 24)
    for m in mags:
        cands = {f0 - 1, f0, f0 + 1, f1 - 1, f1, f1 + 1}
        for cfg in (committed, variant):
            t = (cfg["ACCEPT_NUM"] * m) >> cfg["ACCEPT_DEN_SHIFT"]
            cands.update({t - 1, t, t + 1})
        for c in sorted(cands):
            if c < 0:
                continue
            if (_accept_from(committed["MIN_AMPLITUDE"], committed["ACCEPT_NUM"],
                             committed["ACCEPT_DEN_SHIFT"], c, m)
                    != _accept_from(variant["MIN_AMPLITUDE"], variant["ACCEPT_NUM"],
                                    variant["ACCEPT_DEN_SHIFT"], c, m)):
                return c, m
    return None


class override_constants:
    """Override ``oqpsk_rx`` module globals for one experimental arm.

    On enter: capture the committed values, apply the overrides, then *prove*
    the override took effect --

    - every overridden name by attribute equality (catches a misspelled key:
      ``setattr`` would silently create a new attribute and the model would run
      with the committed value);
    - the amplitude/ratio gate through the real ``_accept`` at a point where
      the committed and override predicates disagree (catches a future refactor
      that stops reading the globals at call time: the model then fails loudly
      here instead of silently reporting "no difference");
    - ``FIR_OUT_BITS`` through the real ``channel_filter``.

    Restores exactly on exit and re-asserts the restore.
    """

    def __init__(self, overrides):
        self.overrides = dict(overrides)
        self.committed = {}

    def __enter__(self):
        mod = oqpsk_rx
        unknown = set(self.overrides) - set(OVERRIDABLE_KEYS)
        if unknown:
            raise AssertionError(f"not an overridable oqpsk_rx constant: {sorted(unknown)} "
                                 f"(known: {OVERRIDABLE_KEYS})")
        self.committed = {k: getattr(mod, k)
                          for k in set(self.overrides) | set(GATE_KEYS) | {"FIR_OUT_BITS"}}
        for k, v in self.overrides.items():
            setattr(mod, k, v)
        for k, v in self.overrides.items():
            if getattr(mod, k) != v:
                raise AssertionError(f"override of oqpsk_rx.{k} did not take")

        gate = {k: v for k, v in self.overrides.items() if k in GATE_KEYS}
        try:
            if any(self.committed[k] != v for k, v in gate.items()):
                variant = {k: getattr(mod, k) for k in GATE_KEYS}
                point = _gate_probe_point(self.committed, variant)
                if point is None:
                    raise AssertionError(f"gate override is numerically a no-op: {gate}")
                corr, mag = point
                got = bool(mod._accept(np.int64(corr), np.int64(mag)))
                want = _accept_from(mod.MIN_AMPLITUDE, mod.ACCEPT_NUM, mod.ACCEPT_DEN_SHIFT, corr, mag)
                if got != want:
                    raise AssertionError(f"oqpsk_rx._accept ignores the overridden constants: "
                                         f"at corr={corr} mag={mag} model said {got}, want {want}")
            if self.committed["FIR_OUT_BITS"] != mod.FIR_OUT_BITS:
                probe_in = 30000                     # single-sample conv output; >>FIR_SHIFT -> 1875
                shifted = (probe_in + (1 << (mod.FIR_SHIFT - 1))) >> mod.FIR_SHIFT
                expect = int(le1m_rx.saturate(np.int64(shifted), mod.FIR_OUT_BITS))
                got = int(mod.channel_filter(np.array([probe_in], dtype=np.int64))[0])
                if got != expect:
                    raise AssertionError(f"oqpsk_rx.channel_filter ignores FIR_OUT_BITS: "
                                         f"got {got}, want {expect}")
        except BaseException:
            self.__exit__(None, None, None)          # __enter__ raised: restore before propagating
            raise
        return self

    def __exit__(self, *exc):
        for k, v in self.committed.items():
            setattr(oqpsk_rx, k, v)
        for k, v in self.committed.items():
            if getattr(oqpsk_rx, k) != v:
                raise AssertionError(f"oqpsk_rx.{k} not restored")
        return False


# ------------------------------------------------------- quantization harness

def quantize_float(float_iq, gain, frac_bits):
    """The pre-gain float record on a 1/2**frac_bits LSB grid, integer-ready:
    scale by the recorded AGC gain and 2**frac_bits, round, keep int64. No
    clipping -- the caller owns the FIR_OUT_BITS headroom (asserted)."""
    scaled = np.rint(float_iq * (gain * (1 << frac_bits)))
    q = np.stack([scaled.real, scaled.imag], axis=1).astype(np.int64)
    peak = int(np.abs(q).max()) if len(q) else 0
    if peak >= (1 << 28):
        raise AssertionError(f"quantized input peak {peak} threatens the int64 downstream widths")
    return q


def demodulate_fine(out, frac_bits):
    """One packet through the integer receiver with the input quantization
    refined to 1/2**frac_bits LSB (the scaling choice, see module docstring).
    Same flags/gain records as the committed path."""
    gain = cm_a.gain_from_index(out.gain_index)
    with override_constants({"FIR_OUT_BITS": oqpsk_rx.FIR_OUT_BITS + frac_bits}):
        return oqpsk_rx.demodulate(quantize_float(out.float_iq, gain, frac_bits),
                                   out.flags, out.gain)


def quantize_float_frac0_matches_int8(out):
    """The harness's sanity anchor: at frac_bits=0 with int8 clipping, the
    quantization is bit-identical to the committed receive_chain output."""
    gain = cm_a.gain_from_index(out.gain_index)
    q = np.rint(out.float_iq * gain)
    iq = np.stack([np.clip(q.real, -128, 127), np.clip(q.imag, -128, 127)], axis=1).astype(np.int8)
    if not np.array_equal(iq, out.iq):
        raise AssertionError("frac_bits=0 quantization does not reproduce the committed int8 samples")


def assert_frac0_reproduces_committed():
    """Two packets at 5 dB through both paths; the frac_bits=0 arm must match
    the committed demodulation on every result field."""
    rng = np.random.Generator(np.random.PCG64(0))
    psdu = per_sweep.oqpsk_tx.with_fcs(
        bytes(rng.integers(0, 256, PSDU_OCTETS - 2, dtype=np.uint8).tolist()))
    params = cm_a_oqpsk.OqpskParams(snr_db=5.0)
    fields = ("synced", "psdu", "crc_ok", "length", "sync_index", "timing_steps")
    for _ in range(2):
        out_c = cm_a_oqpsk.generate_packet(psdu, params, rng, keep_float=True)
        quantize_float_frac0_matches_int8(out_c)
        a = oqpsk_rx.demodulate(out_c.iq, out_c.flags, out_c.gain)
        b = demodulate_fine(out_c, 0)
        if {k: a[k] for k in fields} != {k: b[k] for k in fields}:
            raise AssertionError("frac_bits=0 demodulate does not reproduce the committed path")


# ------------------------------------------------------------------- run loop

def run_point_variant(variant, overrides, snr_db, packet_cap, min_errors, base_seed, run_index):
    """One sweep point through the unmodified ``per_sweep.run_point`` with this
    arm's constants overridden around the call. Same seed derivation as the
    committed sweep, so the packet stream is shared across arms (common random
    numbers): packet k carries the same stimulus in every arm."""
    desc = dict(cm_a_oqpsk.OqpskParams(snr_db=snr_db).describe(), psdu_octets=PSDU_OCTETS)
    seed = ber_sweep.point_seed(ROW_ID, desc, SNR_POINT_INDEX[snr_db], run_index, base_seed)
    t0 = time.time()
    with override_constants(overrides):
        p = per_sweep.run_point(ROW_ID, SNR_POINT_INDEX[snr_db],
                                cm_a_oqpsk.OqpskParams(snr_db=snr_db), PSDU_OCTETS,
                                packet_cap, min_errors, base_seed, run_index=run_index)
    p["variant"] = variant
    p["overrides"] = dict(overrides)
    p["wall_s"] = round(time.time() - t0, 3)
    p.update(split_classes(p))
    p["residual"] = p["classes"]["residual"]
    return p


def run_point_fine(snr_db, frac_bits, packet_cap, min_errors, base_seed, run_index):
    """One sweep point with the input quantization refined, mirroring
    ``per_sweep.run_point``'s loop exactly: same seed, same draw order (PSDU
    body first, then the channel's per-packet draws; ``keep_float`` adds no
    draw), so its packets are the committed stream's packets."""
    params = cm_a_oqpsk.OqpskParams(snr_db=snr_db)
    desc = dict(params.describe(), psdu_octets=PSDU_OCTETS)
    seed = ber_sweep.point_seed(ROW_ID, desc, SNR_POINT_INDEX[snr_db], run_index, base_seed)
    rng = np.random.Generator(np.random.PCG64(seed))
    errors = packets = sync_misses = fcs_failures = clipped = samples = 0
    t0 = time.time()
    while errors < min_errors and packets < packet_cap:
        body = bytes(rng.integers(0, 256, PSDU_OCTETS - 2, dtype=np.uint8).tolist())
        psdu = per_sweep.oqpsk_tx.with_fcs(body)
        out = cm_a_oqpsk.generate_packet(psdu, params, rng, keep_float=True)
        quantize_float_frac0_matches_int8(out)      # per-packet anchor
        rx = demodulate_fine(out, frac_bits)
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
        "row_id": ROW_ID, "label": LABEL, "channel_model": "CM-A",
        "variant": f"quant_frac{frac_bits}",
        "overrides": {"FIR_OUT_BITS": oqpsk_rx.FIR_OUT_BITS + frac_bits},
        "point_index": SNR_POINT_INDEX[snr_db], "run_index": run_index, "seed": seed,
        "snr_db": snr_db, "impairments": desc,
        "packets": packets, "errors": errors, "per": r(errors / packets),
        "cp_lower": r(lower), "cp_upper": r(upper),
        "stopped_by": "packet_cap" if capped else "errors", "bound_only": capped,
        "sync_misses": sync_misses, "fcs_failures": fcs_failures,
        "residual": errors - sync_misses - fcs_failures,
        "clipped_samples": clipped, "samples": samples,
        "frac_bits": frac_bits, "wall_s": round(time.time() - t0, 3),
    }


# -------------------------------------------------------------------- summary

def split_classes(point):
    """Per-point error-class split. The residual is real: a packet that syncs,
    passes FCS and still returns a wrong PSDU counts in ``errors`` but in
    neither named class (issue #137, verified correction 2)."""
    residual = point["errors"] - point["sync_misses"] - point["fcs_failures"]
    if residual < 0:
        raise AssertionError(f"negative residual class at snr {point['snr_db']}: {point}")
    classes = {"sync_misses": point["sync_misses"],
               "fcs_failures": point["fcs_failures"],
               "residual": residual}
    return {"classes": classes, "dominant": max(classes, key=lambda k: classes[k])}


def crossing_snr(points, target_per=per_sweep.TARGET_PER):
    """Lowest SNR whose 95 % CP upper bound is below ``target_per`` within the
    points given, or (None, None). A capped point below target is still only a
    bound: the caller must say so."""
    best = None
    for p in points:
        if p["cp_upper"] < target_per and (best is None or p["snr_db"] < best["snr_db"]):
            best = p
    return (None, None) if best is None else (best["snr_db"], best)


def measured_slope_db_per_decade(baseline_points):
    """Local PER slope of the baseline between its measured (non-capped)
    points, in dB per decade of PER. Derived from measured points only."""
    meas = sorted((p for p in baseline_points if not p["bound_only"]), key=lambda p: p["snr_db"])
    out = []
    for lo, hi in zip(meas, meas[1:]):
        if lo["per"] > 0 and hi["per"] > 0 and hi["per"] < lo["per"]:
            out.append({"between_db": [lo["snr_db"], hi["snr_db"]],
                        "db_per_decade": round((hi["snr_db"] - lo["snr_db"])
                                               / np.log10(lo["per"] / hi["per"]), 3)})
    return out


def slope_for(slope, snr_db):
    """The measured slope entry whose bracket contains ``snr_db``, else the
    closest bracket, else None."""
    if not slope:
        return None
    for e in slope:
        if e["between_db"][0] <= snr_db <= e["between_db"][1]:
            return e
    return min(slope, key=lambda e: min(abs(snr_db - e["between_db"][0]),
                                        abs(snr_db - e["between_db"][1])))


def equivalent_db_delta(base_point, var_point, slope_entry):
    """dB the baseline curve would shift for its PER at this SNR to equal the
    variant's, using the measured local slope. Derived arithmetic on two
    measured PERs, not a crossing measurement; negative = variant better."""
    if slope_entry is None or base_point["per"] <= 0 or var_point["per"] <= 0:
        return None
    return round(slope_entry["db_per_decade"] * np.log10(var_point["per"] / base_point["per"]), 3)


def assert_committed_reference(baseline_points):
    """Full mode only: the unmodified-constant points at the committed caps
    must reproduce the committed evidence exactly (same machine and NumPy
    version). If this fails, every variant delta below is suspect."""
    by_snr = {p["snr_db"]: p for p in baseline_points}
    for snr, ref in COMMITTED_REFERENCE:
        p = by_snr[snr]
        if p["bound_only"] != (snr == 9.0) or p["packets"] != ref["packets"] or p["errors"] != ref["errors"]:
            raise AssertionError(
                f"baseline does not reproduce the committed evidence at {snr} dB: got "
                f"packets={p['packets']} errors={p['errors']} bound_only={p['bound_only']}, "
                f"want packets={ref['packets']} errors={ref['errors']} "
                f"bound_only={snr == 9.0} -- variant deltas are not attributable; "
                "check the NumPy version and that sim/model is unmodified")
        if abs(p["cp_upper"] - ref["cp_upper"]) > 5e-4:
            raise AssertionError(f"cp_upper at {snr} dB drifted vs the committed evidence")


# ----------------------------------------------------------------------- main

def build_report(args, sha, points, quant_points, slope):
    by_variant = {}
    for p in points:
        by_variant.setdefault(p["variant"], []).append(p)
    base_pts = by_variant.get("baseline", [])
    base_by_snr = {p["snr_db"]: p for p in base_pts}
    slope7 = slope_for(slope, 7.0)
    variants = {}
    for name, overrides in VARIANTS:
        pts = by_variant.get(name, [])
        snr, xpt = crossing_snr(pts)
        delta = None
        if name != "baseline" and 7.0 in base_by_snr:
            vp = next((p for p in pts if p["snr_db"] == 7.0), None)
            if vp is not None:
                delta = equivalent_db_delta(base_by_snr[7.0], vp, slope7)
        variants[name] = {
            "overrides": dict(overrides),
            "points": pts,
            "crossing": None if snr is None else {
                "snr_db": snr, "bound_only": xpt["bound_only"], "cp_upper": xpt["cp_upper"]},
            "equivalent_delta_db_at_7": delta,
        }
    qsnr, qx = crossing_snr(quant_points)
    bsnr, bx = crossing_snr(base_pts)
    return {
        "format": FORMAT,
        "label": LABEL,
        "channel_model": "CM-A",
        "analysis": "sim/analysis/oqpsk_sensitivity_budget.py",
        "issue": 137,
        "mode": "quick" if args.quick else "full",
        "sim_git_sha": sha,
        "prng": {"family": "PCG64", "numpy_version": np.__version__},
        "base_seed": args.seed,
        "run_index": args.run_index,
        "stop_rule": {"min_errors": args.min_errors,
                      "baseline_packet_cap": args.baseline_cap,
                      "bracket_packet_cap": args.bracket_cap,
                      "variant_packet_cap": args.variant_cap,
                      "quant_packet_cap": args.quant_cap,
                      "confidence": ber_sweep.CONFIDENCE,
                      "interval": "Clopper-Pearson, two-sided",
                      "capped_point": "upper bound, not a measurement"},
        "receiver": {"model": "sim/model/oqpsk_rx.py", "arithmetic": "integer",
                     "committed_constants": {"MIN_AMPLITUDE": oqpsk_rx.MIN_AMPLITUDE,
                                             "ACCEPT_NUM": oqpsk_rx.ACCEPT_NUM,
                                             "ACCEPT_DEN_SHIFT": oqpsk_rx.ACCEPT_DEN_SHIFT,
                                             "PREAMBLE_RUN": oqpsk_rx.PREAMBLE_RUN}},
        "baseline_reference": {"source": "sim/results/2026-11-14-1564a0ec0cfb/per.json "
                                         "(--seed 1 --run-index 0, quoted in issue #137)",
                               "asserted": not args.quick,
                               "reference": [[snr, ref] for snr, ref in COMMITTED_REFERENCE]},
        "points": points,
        "variants": variants,
        "quantization": {"points": quant_points, "frac_bits": FRAC_BITS,
                         "scaling_choice": "pre-gain float IQ scaled by the recorded AGC gain "
                                           "and 2**frac_bits; FIR_OUT_BITS raised to 9 + frac_bits; "
                                           "discriminator is a CORDIC angle, scale-invariant",
                         "crossing": None if qsnr is None else qsnr,
                         "crossing_bound_only": None if qx is None else qx["bound_only"],
                         "baseline_crossing": None if bsnr is None else bsnr,
                         "baseline_crossing_bound_only": None if bx is None else bx["bound_only"]},
        "baseline_slope": slope,
    }


def cap_for(role, snr_db, args):
    if role == "baseline" and snr_db in BRACKET_SNRS:
        return args.bracket_cap
    return {"baseline": args.baseline_cap, "variant": args.variant_cap,
            "quant": args.quant_cap}[role]


def _print_point(p):
    b = " BOUND" if p.get("bound_only") else ""
    print(f"  {p['variant']:<14} snr {p['snr_db']:>4} dB  packets {p['packets']:>6} "
          f"errors {p['errors']:>5} per {p['per']:.4g} cp_upper {p['cp_upper']:.4g} "
          f"sync {p['sync_misses']} fcs {p['fcs_failures']} resid {p['residual']}{b} "
          f"[{p['wall_s']} s]", flush=True)


def _save(path, report):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(report, f, indent=1)
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="few points, tiny caps (CI smoke)")
    ap.add_argument("--seed", type=int, default=1, help="base seed, as the committed sweep")
    ap.add_argument("--run-index", type=int, default=0)
    ap.add_argument("--min-errors", type=int, default=ber_sweep.MIN_ERRORS)
    ap.add_argument("--baseline-cap", type=int, default=20000)
    ap.add_argument("--bracket-cap", type=int, default=6000, help="packet cap at the 7.5/8/8.5 dB baseline points")
    ap.add_argument("--variant-cap", type=int, default=4000)
    ap.add_argument("--quant-cap", type=int, default=4000)
    ap.add_argument("--out", default=None, help="JSON report path "
                    "(default sim/results/oqpsk-sensitivity-budget-<date>.json)")
    args = ap.parse_args(argv)
    if args.quick:
        args.baseline_cap = args.bracket_cap = args.variant_cap = args.quant_cap = 40

    sha = ber_sweep.git_sha()
    out = args.out or os.path.join(
        SIM, "results", f"oqpsk-sensitivity-budget-{datetime.date.today().isoformat()}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    print(f"# oqpsk sensitivity budget, sha {sha}, out {out}", flush=True)

    assert_frac0_reproduces_committed()
    print("# anchor OK: frac_bits=0 reproduces the committed int8 path", flush=True)

    points, quant_points = [], []
    slope = []
    baseline_snrs = (5.0, 7.0) if args.quick else BASELINE_SNRS
    for snr in baseline_snrs:
        p = run_point_variant("baseline", {}, snr, cap_for("baseline", snr, args),
                              args.min_errors, args.seed, args.run_index)
        points.append(p)
        _print_point(p)
        _save(out, build_report(args, sha, points, quant_points, slope))
    if not args.quick:
        assert_committed_reference([p for p in points if p["variant"] == "baseline"])
        print("# baseline reproduces the committed evidence at 5/7/9 dB", flush=True)

    variant_snrs = (5.0, 7.0) if args.quick else VARIANT_SNRS
    arms = (VARIANTS[1],) if args.quick else VARIANTS[1:]
    for name, overrides in arms:
        for snr in variant_snrs:
            p = run_point_variant(name, overrides, snr, cap_for("variant", snr, args),
                                  args.min_errors, args.seed, args.run_index)
            points.append(p)
            _print_point(p)
            _save(out, build_report(args, sha, points, quant_points, slope))

    quant_snrs = (5.0,) if args.quick else QUANT_SNRS
    for snr in quant_snrs:
        p = run_point_fine(snr, FRAC_BITS, cap_for("quant", snr, args),
                           args.min_errors, args.seed, args.run_index)
        quant_points.append(p)
        _print_point(p)
        _save(out, build_report(args, sha, points, quant_points, slope))

    slope = measured_slope_db_per_decade([p for p in points if p["variant"] == "baseline"])
    _save(out, build_report(args, sha, points, quant_points, slope))
    print(f"# wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
