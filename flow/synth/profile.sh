#!/usr/bin/env bash
# Bounded per-module Yosys cost profile (generic `synth`, no liberty mapping).
#
#   flow/synth/profile.sh [-t SECONDS] [-o OUTDIR] [-n] [-r ROUTE] [-L LIBERTY]
#                         [-d] [module ...]
#
# Runs `synth -top <m>` (no -flatten) on every module in rtl/baseband.f, one at a
# time (sequential on purpose: shared worker), each under a hard `timeout`.
# Writes OUTDIR/profile.json (default flow/synth/records/<date>/, suffixed
# `-noabc` under -n so the two variants do not overwrite each other). Never runs
# the flat flow. A row is status ok | timeout | error; cell/flop counts are
# generic post-`synth` counts and are not timing claims.
#
# `-n` appends `-noabc` to `synth -top <m>`, skipping the generic ABC pass; each
# row records which variant it was under `noabc`. The default (no -n, no -r)
# behaviour, `synth.tcl` and `make synth` are unchanged.
#
# `-r ROUTE` selects a mapping route (issue 201; -n is shorthand for
# `-r noabc`):
#   plain          synth -top <m>                        (default, unchanged)
#   noabc          synth -top <m> -noabc
#   noabc_map      synth -top <m> -noabc; dfflibmap -liberty L; abc -liberty L
#   noabc_mapfast  synth -top <m> -noabc; dfflibmap -liberty L; abc -fast -liberty L
#   noabc_abc9     read_liberty -lib L; synth -top <m> -abc9   (probed on the
#                  pinned 0.67: `abc9` standalone and `abc9 -liberty` do not
#                  exist for standard cells -- abc9 is LUT/FPGA-only, so this
#                  route is expected to record an error row naming that)
#   noabc_minmap   synth -top <m> -noabc; dfflibmap -liberty L;
#                  abc -liberty L -script +strash;,map  (ABC sees `strash; map`;
#                  commas in a +script become blanks, a literal `;` would
#                  split the -p string instead)
# The `noabc_*` routes need the pinned liberty: resolved like the Makefile
# (flow/versions.mk + CIEL_HOME/PDK_ROOT), or named with -L. Rows carry the
# route name; flop counting recognizes liberty flop cells (`<lib>__(e|s)?df*/
# dl*`, covering the enable (edf*) and scan (sdf*) families beside plain df*)
# for the mapped routes.
#
# `-d` runs the issue-201 stall diagnostics per named module instead of a synth
# variant, writing OUTDIR/diag.json and OUTDIR/diag/<m>/ logs:
#   case A  plain synth with COLUMNS=1000 TMPDIR=/tmp exported and stdbuf,
#           probing the yosys/ABC handshake deadlock of
#           2AMLogic/klayout-tools#5877;
#   case B  `synth -noabc` then an explicit `abc -nocleanup -showtmp`, keeping
#           the ABC temp dir (TMPDIR pointed at diag/<m>, so it lands inside
#           the record) so it is on record whether input.blif was written and
#           how big it is;
#   case C  only if case B produced input.blif: the plain default ABC script
#          (`strash; &get -n; &fraig -x; &put; scorr; dc2; dretime; strash;
#           &get -n; &dch -f; &nf; &put`, yosys 0.67 `help abc`, {D} empty)
#           run through yosys-abc standalone, one command group per
#           invocation (the &-space commands must not round-trip through BLIF
#           individually), each timed under the same per-run budget.
#
# Yosys runs with `-t` and `-d`, so the per-module log under OUTDIR/logs/ is
# usable for locating a stall:
#   -t  timestamps every log line, so a run killed by `timeout` still shows
#       which pass it was in (the only evidence available for a timeout).
#   -d  prints a ranked per-pass timing table -- but at exit only, so a killed
#       run has none; it serves the runs that finish.
# `-t` also prefixes the `stat` output, which is stripped before the cell/flop
# awk below (otherwise every count parses as null).
#
# `/usr/bin/time` wraps `timeout`, not the reverse: inside it, `timeout` kills
# `time` before it writes its summary, so a timed-out run records no peak RSS
# (the committed 2026-11-06 .time file is 0 bytes). `time` passes the child's
# exit status through, so the rc 124/137 timeout detection is unaffected.
# If /usr/bin/time is absent (batch images without GNU time), the wrapper is
# skipped and peak RSS records null instead of failing every row.
#
# Rows are `own` cost only for leaf modules. For a module with children
# (`has_children: true`) `synth -top` also synthesizes the children, so its cost
# includes theirs: do not add parent and child rows together.
set -u
cd "$(dirname "$0")/../.."
TMO=600
OUT=
NOABC=0
ROUTE=plain
LIB=
DIAG=0
while getopts "t:o:nr:L:d" o; do
  case $o in
    t) TMO=$OPTARG ;;
    o) OUT=$OPTARG ;;
    n) NOABC=1 ;;
    r) ROUTE=$OPTARG ;;
    L) LIB=$OPTARG ;;
    d) DIAG=1 ;;
    *) exit 2 ;;
  esac
done
shift $((OPTIND-1))

case "$ROUTE" in
  plain|noabc|noabc_map|noabc_mapfast|noabc_abc9|noabc_minmap) ;;
  *) echo "profile: unknown route '$ROUTE' (plain|noabc|noabc_map|noabc_mapfast|noabc_abc9|noabc_minmap)" >&2; exit 2 ;;
esac
if [ "$NOABC" -eq 1 ] && [ "$ROUTE" != plain ] && [ "$ROUTE" != noabc ]; then
  echo "profile: -n cannot be combined with -r $ROUTE" >&2; exit 2
fi
if [ "$NOABC" -eq 1 ]; then ROUTE=noabc; fi

# route -> yosys command after the file reads and `hierarchy -check -top <m>; `
# (<LIB> substituted at call time)
PRE_READ="read_verilog -sv <files>; hierarchy -check -top <m>; "
case "$ROUTE" in
  plain)        MAP_CMD='synth -top <m>' ;;
  noabc)        MAP_CMD='synth -top <m> -noabc' ;;
  noabc_map)    MAP_CMD='synth -top <m> -noabc; dfflibmap -liberty <LIB>; abc -liberty <LIB>' ;;
  noabc_mapfast) MAP_CMD='synth -top <m> -noabc; dfflibmap -liberty <LIB>; abc -fast -liberty <LIB>' ;;
  noabc_abc9)   MAP_CMD='synth -top <m> -abc9' ;;
  noabc_minmap) MAP_CMD='synth -top <m> -noabc; dfflibmap -liberty <LIB>; abc -liberty <LIB> -script +strash;,map' ;;
esac
if [ "$ROUTE" = noabc_abc9 ]; then
  PRE_READ="read_verilog -sv <files>; read_liberty -lib <LIB>; hierarchy -check -top <m>; "
fi

# Liberty: resolve like the Makefile (flow/versions.mk, CIEL_HOME/PDK_ROOT
# overridable) unless -L named it. Only the noabc_* mapping routes need it.
needs_lib=0
case "$ROUTE" in noabc_map|noabc_mapfast|noabc_abc9|noabc_minmap) needs_lib=1 ;; esac
if [ "$DIAG" -eq 0 ] && [ "$needs_lib" -eq 1 ]; then
  if [ -z "$LIB" ]; then
    mk=flow/versions.mk
    get() { sed -n "s/^$1[[:space:]]*:=[[:space:]]*//p" "$mk" | head -1; }
    CIEL_HOME=${CIEL_HOME:-$HOME/.ciel}
    fam=$(get PDK_FAMILY); rev=$(get PDK_REV); var=$(get PDK_VARIANT); cell=$(get STD_CELL_LIB); cor=$(get LIB_CORNER)
    PDK_ROOT=${PDK_ROOT:-$CIEL_HOME/ciel/$fam/versions/$rev}
    LIB=$PDK_ROOT/$var/libs.ref/$cell/lib/${cell}__${cor}.lib
  fi
  if [ ! -f "$LIB" ]; then
    echo "profile: liberty not found: $LIB (see 'make check-pdk' or pass -L)" >&2; exit 1
  fi
fi
LIBPFX=
if [ -n "$LIB" ]; then LIBPFX=$(basename "$LIB"); LIBPFX=${LIBPFX%%__*}; fi

case "$ROUTE" in plain) SUFFIX="" ;; noabc) SUFFIX=-noabc ;; *) SUFFIX="-$ROUTE" ;; esac
if [ "$DIAG" -eq 1 ]; then SUFFIX=${SUFFIX}-diag; fi
[ -n "$OUT" ] || OUT=flow/synth/records/$(date -u +%Y-%m-%d)$SUFFIX
mkdir -p "$OUT/logs"
LIST=rtl/baseband.f
TIMEV=/usr/bin/time
[ -x "$TIMEV" ] || TIMEV=

files=$(grep -v '^[[:space:]]*\(#\|$\)' "$LIST")
# module name = file basename (verified by `hierarchy` in each run)
if [ $# -gt 0 ]; then mods="$*"; else mods=$(for f in $files; do basename "$f" .v; done); fi

read_cmd() { # <module> -> full yosys -p string for the selected route
  local m=$1 pre=$PRE_READ map=$MAP_CMD
  local reads=""
  for f in $files; do reads="$reads read_verilog -sv $f; "; done
  pre=${pre/read_verilog -sv <files>; /$reads}
  pre=${pre//<m>/$m}; pre=${pre//<LIB>/$LIB}; map=${map//<m>/$m}; map=${map//<LIB>/$LIB}
  printf '%s %s' "${pre%"${pre##*[! ]}"}" "$map"
}

run_yosys() { # log tl rc-holding var name -> runs one bounded yosys invocation
  local log=$1 tl=$2
  if [ -n "$TIMEV" ]; then
    "$TIMEV" -v -o "$tl" timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
  else
    timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
  fi
}

parse_stat() { # stat file -> "cells flops" (generic $_DFF or liberty flops)
  local st=$1
  sed 's/^\[[0-9][0-9]*\.[0-9][0-9]*\] //' "$st" | awk -v pfx="$LIBPFX" '
    /=== design hierarchy ===/ {c=""; f=0; inh=1}
    /^ +[0-9]+ +cells$/ {c=$1}
    $1 ~ /^[0-9]+$/ && $2 ~ /^\$_.*(DFF|DLATCH)/ {f+=$1}
    pfx != "" && $1 ~ /^[0-9]+$/ && $2 ~ "^" pfx "__(e|s)?(df|dl)" {f+=$1}
    END {print (c==""?"null":c), f+0}'
}

if [ "$DIAG" -eq 1 ]; then
  # ---------------------------------------------------------------- diagnostics
  diag_rows=()
  for m in $mods; do
    d="$OUT/diag/$m"; mkdir -p "$d"
    reads=""
    for f in $files; do reads="$reads read_verilog -sv $f; "; done
    # case A: plain synth, handshake-probe env (klayout-tools#5877); runs
    # from the repo root (RTL paths are relative), TMPDIR=/tmp per the probe
    log="$d/caseA.log"; tl="$d/caseA.time"
    CMDBUF="${reads}hierarchy -check -top $m; synth -top $m"
    start=$(date +%s.%N)
    if [ -n "$TIMEV" ]; then
      COLUMNS=1000 TMPDIR=/tmp stdbuf -oL -eL "$TIMEV" -v -o "$tl" timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
    else
      COLUMNS=1000 TMPDIR=/tmp stdbuf -oL -eL timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
    fi
    rc=$?
    wall=$(awk -v a="$start" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
    rss=$(awk -F: '/Maximum resident set size/{gsub(/ /,"",$2); print $2}' "$tl" 2>/dev/null); rss=${rss:-null}
    if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then status=timeout
    elif [ $rc -eq 0 ]; then status=ok; else status=error; fi
    diag_rows+=("    {\"module\": \"$m\", \"case\": \"A-env\", \"status\": \"$status\", \"wall_s\": $wall, \"peak_rss_kb\": $rss, \"env\": \"COLUMNS=1000 TMPDIR=/tmp stdbuf\"}")

    # case B: noabc synth, then an explicit abc keeping its temp dir; TMPDIR
    # points at diag/<m> so _tmp_yosys-abc-* lands inside the record
    log="$d/caseB.log"; tl="$d/caseB.time"
    CMDBUF="${reads}hierarchy -check -top $m; synth -top $m -noabc; abc -nocleanup -showtmp"
    start=$(date +%s.%N)
    if [ -n "$TIMEV" ]; then
      TMPDIR="$d" stdbuf -oL -eL "$TIMEV" -v -o "$tl" timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
    else
      TMPDIR="$d" stdbuf -oL -eL timeout -k 5 "$TMO" yosys -q -t -d -l "$log" -p "$CMDBUF" >/dev/null 2>&1
    fi
    rc=$?
    wall=$(awk -v a="$start" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
    rss=$(awk -F: '/Maximum resident set size/{gsub(/ /,"",$2); print $2}' "$tl" 2>/dev/null); rss=${rss:-null}
    if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then status=timeout
    elif [ $rc -eq 0 ]; then status=ok; else status=error; fi
    tmpdir=$(sed -n 's/.*to `\(.*\)\/input\.blif.*/\1/p' "$log" | tail -1)
    # the abc pass writes <tmpdir>/input.blif relative to yosys' cwd (the repo
    # root), not TMPDIR; TMPDIR only hosts the liberty/genlib staging dir
    blif="$tmpdir/input.blif"
    blif_exists=false; blif_bytes=null; blif_sha=null
    if [ -n "$tmpdir" ] && [ -f "$blif" ]; then
      blif_exists=true; blif_bytes=$(stat -c%s "$blif"); blif_sha=$(sha256sum "$blif" | cut -c1-16)
    fi
    diag_rows+=("    {\"module\": \"$m\", \"case\": \"B-keeptmp\", \"status\": \"$status\", \"wall_s\": $wall, \"peak_rss_kb\": $rss, \"abc_tmpdir\": \"${tmpdir:-null}\", \"input_blif_exists\": $blif_exists, \"input_blif_bytes\": $blif_bytes, \"input_blif_sha256_16\": \"$blif_sha\"}")

    # case C: standalone yosys-abc on the kept input.blif, one script command
    # per invocation, each timed, whole case under the same budget
    crow="    {\"module\": \"$m\", \"case\": \"C-abc-standalone\", \"status\": \"skipped\", \"wall_s\": null, \"commands\": []}"
    if [ "$blif_exists" = true ]; then
      # The plain default script, split so that each invocation round-trips
      # through BLIF safely: the &-space commands must run as one group
      # (write_blif serializes the regular network, not the &-network).
      abc_cmds=("strash" "&get -n; &fraig -x; &put" "scorr" "dc2" "dretime" "strash" "&get -n; &dch -f; &nf; &put")
      cstart=$(date +%s.%N); budget=$TMO; cstatus=ok; crows=(); cur="$blif"
      : > "$d/caseC.log"
      i=0
      for c in "${abc_cmds[@]}"; do
        i=$((i+1)); nxt="$d/caseC-step$i.blif"
        s0=$(date +%s.%N)
        stdbuf -oL -eL timeout -k 5 "$budget" yosys-abc -c "read_blif $cur; $c; write_blif $nxt" >>"$d/caseC.log" 2>&1
        crc=$?
        cw=$(awk -v a="$s0" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
        budget=$(awk -v b="$budget" -v w="$cw" 'BEGIN{printf "%d", b-w}')
        if [ $crc -eq 124 ] || [ $crc -eq 137 ]; then cs=timeout; elif [ $crc -eq 0 ]; then cs=ok; else cs=error; fi
        crows+=("        {\"cmd\": \"$c\", \"wall_s\": $cw, \"status\": \"$cs\"}")
        cur=$nxt
        if [ "$cs" != ok ]; then cstatus=$cs; break; fi
        if [ "$budget" -le 0 ]; then cstatus=timeout; crows+=("        {\"cmd\": \"(budget exhausted)\", \"wall_s\": null, \"status\": \"timeout\"}"); break; fi
      done
      cwall=$(awk -v a="$cstart" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
      cjson=$(printf '%s,\n' "${crows[@]}" | sed '$ s/,$//' | tr -d '\n')
      crow="    {\"module\": \"$m\", \"case\": \"C-abc-standalone\", \"status\": \"$cstatus\", \"wall_s\": $cwall, \"commands\": [$cjson]}"
      rm -f "$d"/caseC-step*.blif
    fi
    diag_rows+=("$crow")
    # remove the kept ABC temp dir from the repo root now that size and sha
    # are recorded (case B's -nocleanup evidence has served its purpose);
    # guarded to the abc pass's own naming so a misparsed log cannot rm else
    case "${tmpdir##*/}" in _tmp_yosys-abc-*) [ -d "$tmpdir" ] && rm -rf -- "$tmpdir" ;; esac
  done
  {
    echo "{"
    echo "  \"tool\": \"$(yosys -V)\","
    echo "  \"timeout_s\": $TMO,"
    echo "  \"note\": \"issue-201 stall diagnostics: A handshake env probe (COLUMNS/TMPDIR, stdbuf), B explicit abc -nocleanup -showtmp after synth -noabc (input.blif evidence), C yosys-abc standalone, plain default script per command\"",
    echo "  \"cases\": ["
    n=${#diag_rows[@]}; i=0
    for r in "${diag_rows[@]}"; do i=$((i+1)); [ $i -lt $n ] && echo "$r," || echo "$r"; done
    echo "  ]"
    echo "}"
  } > "$OUT/diag.json"
  echo "wrote $OUT/diag.json"
  exit 0
fi

# ---------------------------------------------------------------- route runs
rows=()
for m in $mods; do
  log="$OUT/logs/$m.log"; tl="$OUT/logs/$m.time"
  CMDBUF="$(read_cmd "$m"); tee -o $OUT/logs/$m.stat stat"
  start=$(date +%s.%N)
  run_yosys "$log" "$tl"
  rc=$?
  wall=$(awk -v a="$start" -v b="$(date +%s.%N)" 'BEGIN{printf "%.1f", b-a}')
  rss=$(awk -F: '/Maximum resident set size/{gsub(/ /,"",$2); print $2}' "$tl" 2>/dev/null)
  rss=${rss:-null}
  if [ $rc -eq 124 ] || [ $rc -eq 137 ]; then status=timeout
  elif [ $rc -eq 0 ]; then status=ok; else status=error; fi
  cells=null; flops=null
  if [ $status = ok ] && [ -f "$OUT/logs/$m.stat" ]; then
    read -r cells flops < <(parse_stat "$OUT/logs/$m.stat")
  fi
  [ "$status" = error ] && echo "profile: $m: error (see $log)" >&2
  rows+=("    {\"module\": \"$m\", \"status\": \"$status\", \"wall_s\": $wall, \"peak_rss_kb\": $rss, \"cells\": $cells, \"flops\": $flops, \"noabc\": $([ "$ROUTE" = noabc ] && echo true || echo false), \"route\": \"$ROUTE\", \"timeout_s\": $TMO}")
done
{
  echo "{"
  echo "  \"tool\": \"$(yosys -V)\","
  echo "  \"command\": \"$(case $ROUTE in
    plain) echo 'synth -top <module> (generic, no -flatten, no liberty)' ;;
    noabc) echo 'synth -top <module> -noabc (generic, no -flatten, no liberty)' ;;
    *) echo "$MAP_CMD" | sed 's/<m>/<module>/g; s/<LIB>/<liberty>/g' ;;
  esac)\","
  echo "  \"timeout_s\": $TMO,"
  echo "  \"noabc\": $([ "$ROUTE" = noabc ] && echo true || echo false),"
  echo "  \"route\": \"$ROUTE\","
  echo "  \"liberty\": \"${LIB:-null}\","
  echo "  \"note\": \"cells/flops are totals over the module and everything it instantiates; parent rows include their children\","
  echo "  \"rows\": ["
  n=${#rows[@]}; i=0
  for r in "${rows[@]}"; do i=$((i+1)); [ $i -lt $n ] && echo "$r," || echo "$r"; done
  echo "  ]"
  echo "}"
} > "$OUT/profile.json"
echo "wrote $OUT/profile.json"
