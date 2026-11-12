#!/usr/bin/env bash
# Run the baseband_top synthesis on the Spot batch fleet (`repo-script` job
# kind, 2am#6381), not on a dispatch worker. Submit with
# infra/aws/repo-script-submit.py from the 2am repo, e.g.
#   repo-script-submit.py --source-dir <this repo> --commit <sha> \
#     --script flow/synth/run-batch.sh --issue 72 --capacity on-demand \
#     --timeout 7200 --output flow/synth/baseband_top_netlist.v \
#     --output flow/synth/liberty_record.txt --output flow/build/synth/cell_count.rpt \
#     --output flow/build/synth/batch_env.txt
# Runs from the source root on the instance. Records the instance's tool
# versions first (batch_env.txt), so a version mismatch against
# flow/versions.mk is visible in the collected outputs even if synthesis fails.
set -uo pipefail
mkdir -p flow/build/synth
ENVREC=flow/build/synth/batch_env.txt
{
  echo "start: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "yosys: $(yosys -V 2>&1)"
  echo "nproc: $(nproc)"; grep -E 'MemTotal' /proc/meminfo
  grep -E '^(YOSYS_VERSION|PDK_REV|LIB_CORNER)' flow/versions.mk
} > "$ENVREC"

# Make is driven with the PDK where the Makefile expects it; if the image has
# the pinned PDK elsewhere, point PDK_ROOT at it via env, else try ciel.
if ! make check-pdk >> "$ENVREC" 2>&1; then
  echo "pinned PDK not at the Makefile default; trying ciel" >> "$ENVREC"
  python3 -m pip install --quiet ciel >> "$ENVREC" 2>&1 \
    && ciel enable --pdk-family sky130 "$(sed -n 's/^PDK_REV *:= *//p' flow/versions.mk)" >> "$ENVREC" 2>&1
fi
make check-tools check-pdk >> "$ENVREC" 2>&1 || { echo "tool/PDK check failed" >> "$ENVREC"; cat "$ENVREC"; exit 1; }

/usr/bin/time -v make synth > flow/build/synth/make.out 2> flow/build/synth/time.txt
RC=$?
{ echo "make synth rc: $RC"; grep -E 'Elapsed|Maximum resident' flow/build/synth/time.txt; echo "end: $(date -u +%Y-%m-%dT%H:%M:%SZ)"; } >> "$ENVREC"
exit "$RC"
