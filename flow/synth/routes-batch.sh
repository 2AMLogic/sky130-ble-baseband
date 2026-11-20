#!/usr/bin/env bash
# Issue 201 trial matrix as ONE repo-script batch shard (operator ruling of
# 2026-10-29 via #72's Curator/Champion notes: no synthesis-trial load on a
# worker). Everything runs sequentially here, one yosys at a time, each run
# under ROUTES_TMO (default 300 s) inside profile.sh.
#
# The heavy batch image carries no PDK (2am infra/aws/repo-script-batch.md),
# so the pinned liberty is shipped inside the source tarball at
# flow/build/synth-batch-lib/ and named by SYNTH_LIB (default below); its
# sha256 is recorded in run-meta.txt for provenance. The image's yosys is its
# own pin (not flow/versions.mk's) -- also recorded, so rows stay comparable
# with the 2026-11-14* records only through that caveat.
#
# Outputs (declared output dir, collected by the submitter):
#   $ROUTES_OUT/run-meta.txt   provenance (yosys/abc versions, liberty sha,
#                              RS_* source identity, date, host)
#   $ROUTES_OUT/diag.json      issue-201 step-1 diagnostics (profile.sh -d)
#   $ROUTES_OUT/diag/<m>/      diagnostic logs (and the kept ABC temp dir)
#   $ROUTES_OUT/routes/<r>/    per-route profile.json + logs (profile.sh -r)
#   $ROUTES_OUT/profile.json   merged rows of all four step-2 routes
set -u
cd "$(dirname "$0")/../.."
# repo-script shard arguments reach this script as argv; accept KEY=VALUE
# assignments (ROUTES_OUT=..., ROUTES_TMO=..., ROUTES_MODULES=..., SYNTH_LIB=...)
for a in "$@"; do
  case "$a" in
    [A-Z_]*=*) export "$a" ;;
    *) echo "routes-batch: ignoring argument '$a' (expected KEY=VALUE)" >&2 ;;
  esac
done
OUT="${ROUTES_OUT:?ROUTES_OUT must name the record directory}"
TMO="${ROUTES_TMO:-300}"
LIB="${SYNTH_LIB:-flow/build/synth-batch-lib/sky130_fd_sc_hd__tt_025C_1v80.lib}"
LEAVES="${ROUTES_MODULES:-oqpsk_rx_corr le1m_rx_sync}"
mkdir -p "$OUT"
{
  echo "date_utc: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "host: $(uname -a)"
  echo "yosys: $(yosys -V)"
  echo "yosys-abc: $(yosys-abc -q version 2>&1 | head -1 || echo unknown)"
  echo "stdbuf: $(command -v stdbuf || echo MISSING)"
  echo "/usr/bin/time: $( [ -x /usr/bin/time ] && echo present || echo MISSING )"
  echo "liberty: $LIB"
  sha256sum "$LIB" 2>/dev/null || echo "liberty: NOT FOUND"
  echo "rs_commit: ${RS_COMMIT:-}"
  echo "rs_source_commit: ${RS_SOURCE_COMMIT:-}"
  echo "rs_src_sha256: ${RS_SRC_SHA256:-}"
} > "$OUT/run-meta.txt"
[ -f "$LIB" ] || { echo "routes-batch: liberty missing: $LIB" >&2; exit 1; }

echo "== step 1: stall diagnostics (profile.sh -d), ${TMO}s cap per run"
./flow/synth/profile.sh -d -t "$TMO" -o "$OUT" $LEAVES || exit 1

echo "== step 2: trial routes (profile.sh -r), ${TMO}s cap per run"
for r in noabc_map noabc_mapfast noabc_abc9 noabc_minmap; do
  ./flow/synth/profile.sh -r "$r" -L "$LIB" -t "$TMO" -o "$OUT/routes/$r" $LEAVES || exit 1
done

# merge the per-route rows into one profile.json (rows carry their route)
rows=$(jq -s 'map(.rows) | add' "$OUT"/routes/*/profile.json) \
  || { echo "routes-batch: jq merge failed" >&2; exit 1; }
{
  echo "{"
  echo "  \"tool\": \"$(yosys -V)\","
  echo "  \"timeout_s\": $TMO,"
  echo "  \"liberty\": \"$LIB\","
  echo "  \"note\": \"issue 201 step-2 trial routes, sequential inside one repo-script shard; cells/flops are mapped liberty counts for the noabc_map* routes; cell counts are not timing claims\","
  echo "  \"rows\": $rows"
  echo "}"
} > "$OUT/profile.json"
echo "wrote $OUT/profile.json"
