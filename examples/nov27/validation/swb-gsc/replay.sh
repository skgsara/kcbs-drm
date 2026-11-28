#!/bin/sh
# Run from the public checkout at 5886518975dfb7ad2c23c5d4c416aaee9b5a374f.
# Arguments are the original IQ FLAC, the standalone Dream executable and a fresh output directory.
set -eu
test "$#" -eq 3
input=$(realpath "$1")
KCBS_DREAM=$(realpath "$2")
export KCBS_DREAM PYTHONDONTWRITEBYTECODE=1
python_exec=${PYTHON:-python3}
mkdir "$3"
output=$(realpath "$3")
"$python_exec" -B scripts/demod_iq_window.py "$input" "$output/receiver" \
    --seconds 180 --reception-profile wiener --mlc-iterations 1 > "$output/receiver.log"
"$python_exec" -B scripts/salvage_msc_packets.py "$output/receiver/msc.bin" \
    --transport-only --out "$output/transport" > "$output/transport.log"
"$python_exec" -B examples/nov27/validation/swb-gsc/direct.py \
    "$output/transport/data_units.npz" > "$output/field-score.json"
