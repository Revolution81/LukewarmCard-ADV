#!/bin/bash
# Fetch the sources: COLDCARD firmware at a chosen version, MicroPython v1.29.0.
#
#   tools/setup.sh [workdir] [coldcard-ref]
#
#   workdir        default ~/cardputer-cc-src
#   coldcard-ref   what to build (default: the COLDCARD release this port was last tested with)
#                    latest-mk5   newest Mk4/Mk5 release tag (e.g. 2026-09-30T2026-v5.6.3)
#                    latest-q     newest Q release tag       (e.g. 2026-09-30T2025-v1.5.3Q)
#                    master       Coinkite's newest code, released or not
#                    any tag, branch or commit id from github.com/Coldcard/firmware
#   (CC_REF in the environment works too)
#
# Running it again with another ref switches the existing checkout.
#
# Then install ESP-IDF v5.5.4 yourself (https://docs.espressif.com, "Get Started"):
#   git clone -b v5.5.4 --recursive https://github.com/espressif/esp-idf.git
#   cd esp-idf && ./install.sh esp32s3 && . ./export.sh
# (or use the Docker image: see BUILDING.md)
#
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
W=${1:-$HOME/cardputer-cc-src}
REF=${2:-${CC_REF:-}}
mkdir -p "$W"

TESTED_COMMIT=2026-09-30T2026-v5.6.3   # COLDCARD 5.6.3 release (Q code 1.5.3Q), commit 3e32e32a
MPY_TAG=v1.29.0
CC_URL=https://github.com/Coldcard/firmware.git

if [ ! -d "$W/coldcard/.git" ]; then
    git clone -q "$CC_URL" "$W/coldcard"
fi
cd "$W/coldcard"
git fetch -q --tags origin

# newest release tag for a product line. Coinkite tags look like
# 2026-09-30T2026-v5.6.3 (Mk4/Mk5), ...-v1.5.3Q (Q), ...X (Edge, not used)
latest_tag() {
    git tag -l '20*' | grep -E -- "$1" | sort | tail -1
}
case "$REF" in
    ''|tested)   REF=$TESTED_COMMIT ;;
    latest-mk5|latest-mk4) REF=$(latest_tag '-v[0-9]+\.[0-9]+\.[0-9]+$') ;;
    latest-q)    REF=$(latest_tag '-v[0-9]+\.[0-9]+\.[0-9]+Q$') ;;
    master)      REF=origin/master ;;
esac
[ -n "$REF" ] || { echo "setup.sh: no matching COLDCARD release tag found"; exit 1; }
git -c advice.detachedHead=false checkout -q --force "$REF"
SUB="git -c advice.detachedHead=false submodule update -q --init --depth 1"
$SUB external/ckcc-protocol external/libngu external/mpy-qr
(cd external/libngu && $SUB libs/secp256k1 libs/cifra libs/bech32)
CC_DESC="$REF ($(git log -1 --format='%h, %cd' --date=short))"

if [ ! -d "$W/micropython" ]; then
    git clone -q --depth 1 -b $MPY_TAG https://github.com/micropython/micropython.git "$W/micropython"
fi
# the parts of MicroPython's libraries the desktop and ESP32 builds use
(cd "$W/micropython" && git -c advice.detachedHead=false submodule update -q --init --depth 1 \
    lib/berkeley-db-1.xx lib/mbedtls lib/micropython-lib)
python3 "$PORT/tools/patch_micropython.py" "$W/micropython"
make -s -C "$W/micropython/mpy-cross" -j"$(nproc)" >/dev/null

# the patched libngu copy in cmodules/ uses the original's crypto libraries
ln -sfn "$W/coldcard/external/libngu/libs" "$PORT/cmodules/libngu-src/libs"

# libngu's C code is copied into this port (cmodules/libngu-src, with small
# changes). Say so if Coinkite changed theirs since: the build still works,
# but their change isn't in it.
LIBNGU_TESTED=$(cat "$PORT/cmodules/libngu-src/UPSTREAM_COMMIT" 2>/dev/null || true)
LIBNGU_NOW=$(git -C "$W/coldcard" rev-parse HEAD:external/libngu)
if [ -n "$LIBNGU_TESTED" ] && [ "$LIBNGU_TESTED" != "$LIBNGU_NOW" ]; then
    echo "NOTE: COLDCARD now uses libngu $LIBNGU_NOW (port has $LIBNGU_TESTED)."
fi

cat <<EOF

Setup done: COLDCARD $CC_DESC
  export CC_REPO=$W/coldcard
  export MPY=$W/micropython

Device firmware (needs ESP-IDF exported):   tools/build_device.sh
Desktop test build (Linux):                  tools/build_host_fw.sh
Everything at once:                          tools/build_release.sh
EOF
