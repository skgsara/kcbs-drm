#!/usr/bin/env bash
# Build the KCBS-instrumented console receiver on Ubuntu, including WSL.
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --no-install ) ]]; then
  echo "Usage: bash build/build.sh [--no-install]" >&2
  exit 2
fi
if [[ $# -eq 0 ]]; then
  apt=(apt-get)
  if (( EUID != 0 )); then apt=(sudo apt-get); fi
  "${apt[@]}" update
  "${apt[@]}" install -y git python3 build-essential qt5-qmake qtbase5-dev \
    libfftw3-dev libsndfile1-dev libpcap-dev libspeexdsp-dev libfdk-aac-dev libasound2-dev \
    zlib1g-dev pkg-config
fi
dream_revision=895658c567d2fd47d6006065e75abf0c3157783f
if [ ! -d dream-src ]; then
  stage=$(mktemp -d "$PWD/.dream-src.XXXXXXXX")
  trap 'rm -rf -- "$stage"' EXIT
  git init -q "$stage"
  git -C "$stage" remote add origin https://github.com/mmjee/dream-patched.git
  git -C "$stage" fetch --depth 1 origin "$dream_revision"
  git -C "$stage" checkout -q --detach FETCH_HEAD
  mv -T "$stage" dream-src
fi
if [[ $(git -C dream-src rev-parse --verify HEAD 2>/dev/null) != "$dream_revision" || ! -f dream-src/dream.pro ]]; then
  echo "Expected the mmjee/dream-patched checkout at $dream_revision in $PWD/dream-src." >&2
  echo "Move your existing dream-src directory aside to build the pinned revision." >&2
  exit 1
fi
python3 apply_kcbs_patch.py dream-src
python3 id_patch.py dream-src
python3 mux_patch.py dream-src
patch_file="$PWD/dream-offline-input.patch"
if ! git -C dream-src apply --reverse --check "$patch_file" 2>/dev/null; then
  git -C dream-src apply "$patch_file"
fi
cd dream-src
qmake dream.pro 'CONFIG+=console sound sndfile' 'LIBS+=-lspeexdsp' -after 'OBJECTS_DIR=obj-kcbs-console'
make -j"${JOBS:-4}"
test -x dream
echo "Built $PWD/dream"
