#!/bin/bash
# Build the Cardputer ADV firmware image.
#
# Needs: ESP-IDF v5.5.x installed and exported (". $IDF_PATH/export.sh"),
#        MicroPython v1.29.0 checkout ($MPY), COLDCARD firmware checkout ($CC_REPO).
#
#   tools/build_device.sh          # release build (mainnet default, no REPL)
#   tools/build_device.sh --dev    # developer build (testnet default)
#   LAYOUT=launcher tools/build_device.sh   # image for M5Launcher
#
# Builds the Keypad edition (COLDCARD Mk4/Mk5 firmware).
# Output: build/device-mk4/firmware.bin  (build/device-mk4-launcher/ for M5Launcher)
# Flash at 0x0 with esptool.
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
CC=${CC_REPO:-$HOME/cardputer-cc-src/coldcard}
MPY=${MPY:-$HOME/cardputer-cc-src/micropython}
VARIANT=mk4
OUT=$PORT/build/device-$VARIANT
LAYOUT=${LAYOUT:-own}
case "$LAYOUT" in own) ;; launcher) OUT=$OUT-launcher ;; *) echo "LAYOUT must be own or launcher"; exit 1 ;; esac
export CP_LAYOUT=$LAYOUT
BTAG=$VARIANT; [ "$LAYOUT" = own ] || BTAG=$VARIANT-$LAYOUT
BOARD=M5STACK_CARDPUTER_ADV
mkdir -p "$OUT"

command -v idf.py >/dev/null || { echo "ESP-IDF not found: run . \$IDF_PATH/export.sh"; exit 1; }

# libngu links (see tools/build_host_fw.sh); the desktop build needs
# cmodules/libngu -> libngu-src/ngu. Links are made here, not stored in git:
# a copied folder (e.g. from a zip, or on Windows) breaks libngu's relative paths.
if [ ! -L "$PORT/cmodules/libngu" ]; then
    rm -rf "$PORT/cmodules/libngu"
    ln -s libngu-src/ngu "$PORT/cmodules/libngu"
fi
# and libngu's own link to its SHA/AES library (cifra), same reason
[ -L "$PORT/cmodules/libngu-src/ngu/cifra" ] || { rm -rf "$PORT/cmodules/libngu-src/ngu/cifra"; ln -s ../libs/cifra/src "$PORT/cmodules/libngu-src/ngu/cifra"; }
python3 "$PORT/tools/patch_micropython.py" "$MPY"
python3 "$PORT/tools/assemble.py" "$CC" "$OUT/py" device $1 --variant "$VARIANT" --layout "$LAYOUT"

# board definition lives in this repo; link it into the MicroPython tree
ln -sfn "$PORT/boards/$BOARD" "$MPY/ports/esp32/boards/$BOARD"

# No network stack on this board, so drop MicroPython's espressif/mdns
# dependency (also avoids needing the ESP component registry). Idempotent.
python3 - "$MPY/ports/esp32/main/idf_component.yml" <<'EOF'
import sys
p = sys.argv[1]
lines = open(p).read().split('\n')
out = [l for l in lines if 'espressif/mdns' not in l]
if out != lines:
    open(p, 'w').write('\n'.join(out))
    print('build_device: removed espressif/mdns from', p)
EOF

export CP_PY_DIR="$OUT/py"
make -C "$MPY/mpy-cross" -j"$(nproc)"
cd "$MPY/ports/esp32"
make BOARD=$BOARD BUILD=build-$BOARD-$BTAG USER_C_MODULES="$PORT/cmodules/micropython.cmake" -j"$(nproc)"

python3 "$PORT/tools/check_frozen_names.py" "build-$BOARD-$BTAG/frozen_content.c"
cp "build-$BOARD-$BTAG/firmware.bin" "$OUT/firmware.bin"
ls -la "$OUT/firmware.bin"
echo
echo "Flash with:  esptool.py --chip esp32s3 --port <PORT> write_flash -z 0 $OUT/firmware.bin"
