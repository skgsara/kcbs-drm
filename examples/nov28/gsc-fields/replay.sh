#!/bin/sh
# Run inside the public project checkout at commit 59c3aec4ea5e38a0adb92ee04e1cdd9b59b2a8f8.
# The arguments are the IQ FLAC, standalone finite-input Dream binary, and a fresh output directory.
set -eu
test "$#" -eq 3
input=$(realpath "$1")
KCBS_DREAM=$(realpath "$2")
export KCBS_DREAM PYTHONDONTWRITEBYTECODE=1
python_exec=${PYTHON:-python3}
mkdir "$3"
output=$(realpath "$3")
"$python_exec" -B scripts/demod_iq_window.py "$input" "$output/receiver" --seconds 180 --reception-profile wiener --mlc-iterations 1 > "$output/receiver.log"
"$python_exec" -B scripts/salvage_msc_packets.py "$output/receiver/msc.bin" --transport-only --out "$output/transport" > "$output/transport.log"
"$python_exec" -B examples/nov28/gsc-fields/check.py "$output/transport/data_units.npz" --out "$output/field-result.json"
"$python_exec" -B scripts/project_evs_group.py "$output/transport/data_units.npz" --counter 43909460 > "$output/primary-projection.json"
"$python_exec" -B scripts/project_evs_group.py "$output/transport/data_units.npz" --counter 43909460 --field-checks > "$output/primary-field-checks.json"
