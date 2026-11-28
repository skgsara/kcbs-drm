#!/usr/bin/env bash
# Replay one frozen view. Set KCBS_DREAM to the finite-input executable.
set -euo pipefail
if [[ $# -ne 3 ]]; then
    echo 'Usage: replay.sh sign|original|even|odd ORIGINAL_RECORDING NEW_OUTPUT_DIR' >&2
    exit 2
fi
arm=$1
original=$(realpath "$2")
output=$(realpath -m "$3")
study=$(cd "$(dirname "$0")" && pwd)
scripts=$(realpath "$study/../../../scripts")
py=${PYTHON:-python3}
: "${KCBS_DREAM:?Set KCBS_DREAM to the pinned Dream executable}"
export KCBS_DREAM
case "$arm" in
    sign|original)
        expected=936531e7c934a2fcee981f375a9075dfd7c0e144bf9957b7e431459c584e326c
        seconds=201.472 ;;
    even|odd)
        expected=0764eb4f22d318efdda8572efe78269796f6ae8bd6257b63738537c95617486f
        seconds=24 ;;
    *) echo "Unknown receiver view $arm" >&2; exit 2 ;;
esac
check_sha() {
    local hash
    hash=$(sha256sum -- "$2")
    [[ ${hash%% *} == "$1" ]] || { echo "SHA-256 differs for $2" >&2; return 1; }
}
check_sha 1e398433affbe71e3bdbc30171e9c770ddd3a622c0fe1577b3f3837c3fa07a26 "$KCBS_DREAM"
check_sha "$expected" "$original"
mkdir "$output"
input=$original
options=()
if [[ $arm == sign ]]; then
    input="$output/sign.wav"
    "$py" "$study/quantize.py" "$original" "$input"
elif [[ $arm == even || $arm == odd ]]; then
    input="$output/$arm.cs8"
    "$py" "$study/split_cs8.py" "$original" "$input" --start-sample 142272000 --sample-count 21888000 --parity "$arm" > "$output/splitter.json"
    options=(--sample-rate 456000 --offset-hz 0)
fi
sha256sum "$input" > "$output/arm-input.sha256"
"$py" "$scripts/demod_iq_window.py" "$input" "$output/rf" --seconds "$seconds" --reception-profile wiener --mlc-iterations 1 "${options[@]}" > "$output/demod.log"
if [[ ! -f "$output/rf/msc.bin" ]]; then
    "$py" - "$output/rf" <<'PY'
import json
from pathlib import Path
import sys
rf = Path(sys.argv[1])
manifest = json.loads((rf/'manifest.json').read_bytes())
if (manifest['status'],manifest['dump_bytes'],manifest['returncode']) != ('no_msc_output',0,0):
    raise SystemExit('Receiver failed before it produced an MSC file')
(rf/'no-native-output').touch()
(rf/'msc.bin').touch()
PY
fi
"$py" "$scripts/salvage_msc_packets.py" "$output/rf/msc.bin" --transport-only --save-packets --out "$output/stock" > "$output/salvage.log"
"$py" "$study/evaluate.py" seal "$output/rf/msc.bin" "$output/stock/packets.npz" > "$output/fields.json.gz"
sha256sum "$output/fields.json.gz"
