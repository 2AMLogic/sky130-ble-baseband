#!/bin/sh
# Regenerate every klt functional-verification report (issue #202): the
# passing runs, then the negative controls, from the committed requests.
# Positives must exit 0, negatives must exit 3 (status "fail"); anything else
# is an error. check_reports.py then validates the right-reason rule, so this
# script only pins the exit-code half.
#
# The klt pin below is scanned by verification/tool_pins.py and must equal the
# version .github/workflows/signoff.yml installs. cocotb / numpy come from
# requirements.txt, so the report's environment.cocotb_version always matches
# the pins the item-9 inventory records. Python 3.12 matches the flow CI.
set -eu

cd "$(dirname "$0")/../.."

KLT="klayout-tools==0.9.2"
COCOTB="$(sed -n 's/^cocotb==//p' requirements.txt)"
NUMPY="$(sed -n 's/^numpy==//p' requirements.txt)"
REQUESTS=manifests/requests/fv
REPORTS=manifests/reports/fv
mkdir -p "$REPORTS"

run_one() { # <request-file> <expected-exit>
    req=$1
    want=$2
    name=$(basename "$req" .json)
    set +e
    uvx --python 3.12 --from "$KLT" --with "cocotb==$COCOTB" --with "numpy==$NUMPY" \
        klt functional-verification "$req" -o "flow/build/fv/$name" --format json \
        > "$REPORTS/$name.json"
    rc=$?
    set -e
    if [ "$rc" -ne "$want" ]; then
        echo "ERROR: $name exited $rc (wanted $want); see flow/build/fv/$name/ and $REPORTS/$name.json" >&2
        exit 1
    fi
    echo "$name: exit $rc, report $REPORTS/$name.json"
}

for req in "$REQUESTS"/*.json; do
    case "$req" in
        *.negative.json) want=3 ;;
        *) want=0 ;;
    esac
    run_one "$req" "$want"
done

echo "all reports regenerated; validating:"
.venv/bin/python verification/fv/check_reports.py
