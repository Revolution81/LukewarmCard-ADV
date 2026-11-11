#!/bin/bash
# Build the desktop-test firmware: unix MicroPython + same C modules + the
# assembled COLDCARD tree frozen in (like the device).
#   tools/build_host_fw.sh   -> build/host-mk4/cc-mpy   (Keypad edition, COLDCARD Mk4/Mk5 firmware)
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
CC=${CC_REPO:-$HOME/cardputer-cc-src/coldcard}
MPY=${MPY:-$HOME/cardputer-cc-src/micropython}
VARIANT=mk4
OUT=$PORT/build/host-$VARIANT
# LAYOUT=launcher: same settings as the M5Launcher device build (128K PSBT
# limit); the desktop storage itself is file-backed either way
LAYOUT=${LAYOUT:-own}
HTAG=$VARIANT; [ "$LAYOUT" = own ] || { HTAG=$VARIANT-$LAYOUT; OUT=$OUT-$LAYOUT; }
# BITS=32: 32-bit build (needs gcc-multilib), so objects and pointers are the
# same size as on the ESP32: memory measurements match the device's MicroPython
# heap. No FFI module in that build (not used by the firmware).
EXTRA=""
if [ "${BITS:-64}" = 32 ]; then
    HTAG=$HTAG-32; OUT=$OUT-32
    EXTRA="MICROPY_PY_FFI=0 CFLAGS_EXTRA=-m32 LDFLAGS_EXTRA=-m32"
fi
mkdir -p "$OUT"

python3 "$PORT/tools/patch_micropython.py" "$MPY"
python3 "$PORT/tools/assemble.py" "$CC" "$OUT/py" host --dev --variant "$VARIANT" --layout "$LAYOUT"

cat > "$OUT/manifest.py" <<EOF
include("\$(MPY_DIR)/extmod/asyncio")
# opt=0 keeps assert statements: COLDCARD relies on them for validation
freeze("$OUT/py", opt=0)
EOF

# MicroPython's unix build looks for C modules one folder down, so it needs
# cmodules/libngu -> libngu-src/ngu. Links are made here, not stored in git:
# a copied folder (e.g. from a zip, or on Windows) breaks libngu's relative paths.
if [ ! -L "$PORT/cmodules/libngu" ]; then
    rm -rf "$PORT/cmodules/libngu"
    ln -s libngu-src/ngu "$PORT/cmodules/libngu"
fi
# and libngu's own link to its SHA/AES library (cifra), same reason
[ -L "$PORT/cmodules/libngu-src/ngu/cifra" ] || { rm -rf "$PORT/cmodules/libngu-src/ngu/cifra"; ln -s ../libs/cifra/src "$PORT/cmodules/libngu-src/ngu/cifra"; }
[ -d "$PORT/cmodules/libngu-src/libs" ] || { echo "cmodules/libngu-src/libs missing: run tools/setup.sh first"; exit 1; }

cd "$MPY/ports/unix"
rm -f build-cchost-$HTAG${DEBUG:+-dbg}/cc-host     # never ship a binary from an earlier build
make -j"$(nproc)" VARIANT=standard USER_C_MODULES="$PORT/cmodules" \
    NGU_NEEDS_CIFRA=1 BUILD=build-cchost-$HTAG${DEBUG:+-dbg} PROG=cc-host ${DEBUG:+DEBUG=1 STRIP=true} \
    MICROPY_PY_THREAD=0 MICROPY_SSL_MBEDTLS=0 MICROPY_PY_SSL=0 $EXTRA \
    FROZEN_MANIFEST="$OUT/manifest.py" 2>&1 \
    | grep -E "error:|Error [0-9]|undefined reference|Traceback|SyntaxError" | sort -u | head -40
[ -x build-cchost-$HTAG${DEBUG:+-dbg}/cc-host ] || { echo "desktop build failed (errors above)"; exit 1; }
cp build-cchost-$HTAG${DEBUG:+-dbg}/cc-host "$OUT/cc-mpy${DEBUG:+-dbg}"
ls -la "$OUT/cc-mpy${DEBUG:+-dbg}"
