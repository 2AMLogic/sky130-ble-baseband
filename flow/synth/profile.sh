#!/usr/bin/env bash
# Bounded per-module Yosys cost profile (generic `synth`, no liberty mapping).
#
#   flow/synth/profile.sh [-t SECONDS] [-o OUTDIR] [module ...]
#
# Runs `synth -top <m>` (no -flatten) on every module in rtl/baseband.f, one at a
# time (sequential on purpose: shared worker), each under a hard `timeout`.
# Writes OUTDIR/profile.json (default flow/synth/records/<date>/). Never runs the
# flat flow. A row is status ok | timeout | error; cell/flop counts are generic
# post-`synth` counts and are not timing claims.
#
# Rows are `own` cost only for leaf modules. For a module with children
# (`has_children: true`) `synth -top` also synthesizes the children, so its cost
# includes theirs: do not add parent and child rows together.
set -u
cd "$(dirname "$0")/../.."
TMO=600
OUT=
while getopts "t:o:" o; do
  case $o in t) TMO=$OPTARG ;; o) OUT=$OPTARG ;; *) exit 2 ;; esac
done
shift $((OPTIND-1))
[ -n "$OUT" ] || OUT=flow/synth/records/$(date -u +%Y-%m-%d)
mkdir -p "$OUT/logs"
LIST=rtl/baseband.f
TIMEV=/usr/bin/time

files=$(grep -v '^[[:space:]]*\(#\|$\)' "$LIST")
# module name = file basename (verified by `hierarchy` in each run)
if [ $# -gt 0 ]; then mods="$*"; else mods=$(for f in $files; do basename "$f" .v; done); fi

rows=()
for m in $mods; do
  log="$OUT/logs/$m.log"; tl="$OUT/logs/$m.time"
  cmd="$(for f in $files; do printf 'read_verilog -sv %s; ' "$f"; done)hierarchy -check -top $m; synth -top $m; tee -o $OUT/logs/$m.stat stat"
  start=$(date +%s.%N)
  timeout -k 5 "$TMO" "$TIMEV" -v -o "$tl" yosys -q -l "$log" -p "$cmd" >/dev/null 2>&1
  rc=$?
  wall=$(awk -v a="$start" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
  rss=$(awk -F: '/Maximum resident set size/{gsub(/ /,"",$2); print $2}' "$tl" 2>/dev/null)
  rss=${rss:-null}
  if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then status=timeout
  elif [ $rc -eq 0 ]; then status=ok; else status=error; fi
  cells=null; flops=null
  if [ $status = ok ] && [ -f "$OUT/logs/$m.stat" ]; then
    st="$OUT/logs/$m.stat"
    # last `Number of cells` / design-hierarchy total if present, else top block
    # totals: the "design hierarchy" section if the module has children, else the
    # module's own block (both include every instantiated child once per instance)
    read -r cells flops < <(awk '
      /=== design hierarchy ===/ {c=""; f=0; inh=1}
      /^ +[0-9]+ +cells$/ {c=$1}
      $1 ~ /^[0-9]+$/ && $2 ~ /^\$_.*(DFF|DLATCH)/ {f+=$1}
      END {print (c==""?"null":c), f+0}' "$st")
  fi
  [ "$status" = error ] && echo "profile: $m: error (see $log)" >&2
  rows+=("    {\"module\": \"$m\", \"status\": \"$status\", \"wall_s\": $wall, \"peak_rss_kb\": $rss, \"cells\": $cells, \"flops\": $flops, \"timeout_s\": $TMO}")
done
{
  echo "{"
  echo "  \"tool\": \"$(yosys -V)\","
  echo "  \"command\": \"synth -top <module> (generic, no -flatten, no liberty)\","
  echo "  \"timeout_s\": $TMO,"
  echo "  \"note\": \"cells/flops are totals over the module and everything it instantiates; parent rows include their children\","
  echo "  \"rows\": ["
  n=${#rows[@]}; i=0
  for r in "${rows[@]}"; do i=$((i+1)); [ $i -lt $n ] && echo "$r," || echo "$r"; done
  echo "  ]"
  echo "}"
} > "$OUT/profile.json"
echo "wrote $OUT/profile.json"
