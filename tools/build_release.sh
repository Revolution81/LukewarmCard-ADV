#!/bin/bash
# build_release.sh - build LukewarmCard ADV images from a COLDCARD release, in one go.
#
#   tools/build_release.sh [coldcard-ref]
#
#   coldcard-ref:  latest-mk5 | latest-q | master | a tag | a commit   (see tools/setup.sh)
#                  default: the commit this port was last tested with
#
# What it does:
#   1. fetches COLDCARD at that version (tools/setup.sh)
#   2. builds the desktop test firmware and runs the test suites, so a COLDCARD
#      change that breaks the port is caught before you flash anything
#   3. builds the device images (M5Launcher + full-flash, Mk5 + Q)
#   4. puts them in dist/<coldcard version>/ with SHA256SUMS.txt
#
# Settings (environment):
#   VARIANTS="mk4"             which editions: mk4 = Keypad (released),
#                              "mk4 q1" adds the QWERTY edition (experimental)
#   LAYOUTS="launcher own"     launcher = for M5Launcher, own = full flash at 0x0
#   SKIP_TESTS=1               skip step 2 (not recommended for a new version)
#   SRC=~/cardputer-cc-src     where sources are kept
#   DIST=<port>/dist           where images go
#
# Needs ESP-IDF v5.5.x (found via $IDF_PATH or ~/esp-idf), or run it in the
# Docker image (BUILDING.md). Takes 10-30 minutes.
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
REF=${1:-${CC_REF:-}}
SRC=${SRC:-$HOME/cardputer-cc-src}
VARIANTS=${VARIANTS:-mk4}
LAYOUTS=${LAYOUTS:-launcher own}
DIST=${DIST:-$PORT/dist}
LOGS=$PORT/build/release-logs
mkdir -p "$LOGS"

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
die() {
    printf '\n\033[1;31mBUILD STOPPED: %s\033[0m\n' "$1"
    [ -n "$2" ] && { echo "Last lines of $2:"; tail -25 "$2"; }
    exit 1
}
patch_help() {
    if grep -q "assemble.py: patch for\|unexpected uhashlib\|could not read Q-only" "$1" 2>/dev/null; then
        echo
        echo "COLDCARD changed a piece of code this port adjusts. The line above names"
        echo "the file and the text that was expected. See BUILDING.md, section"
        echo "\"If the build stops with 'patch ... matched 0 times'\"."
    fi
}

# ---- 1. sources
say "1. COLDCARD sources (${REF:-tested commit})"
"$PORT/tools/setup.sh" "$SRC" "$REF" | tee "$LOGS/setup.log" | grep -v '^  export\|^Device\|^Desktop\|^Everything\|^$' || true
export CC_REPO=$SRC/coldcard MPY=$SRC/micropython
CC_COMMIT=$(git -C "$CC_REPO" log -1 --format=%h)

host_bin() { [ "$1" = q1 ] && echo "$PORT/build/host/cc-mpy" || echo "$PORT/build/host-$1/cc-mpy"; }

# ---- 2. desktop builds + tests
for V in $VARIANTS; do
    say "2. desktop test build + tests: $V"
    VARIANT=$V "$PORT/tools/build_host_fw.sh" > "$LOGS/host-$V.log" 2>&1 \
        || { patch_help "$LOGS/host-$V.log"; die "desktop build ($V) failed" "$LOGS/host-$V.log"; }
    grep -q "patch for\|Error" "$LOGS/host-$V.log" && { patch_help "$LOGS/host-$V.log"; die "desktop build ($V)" "$LOGS/host-$V.log"; }
    [ -x "$(host_bin $V)" ] || die "desktop build ($V) produced no program" "$LOGS/host-$V.log"
    if [ -n "$SKIP_TESTS" ]; then echo "   tests skipped (SKIP_TESTS)"; continue; fi
    M=$(host_bin $V)
    ( cd "$PORT" && VARIANT=$V tests/run_flows.sh 320k ) > "$LOGS/flows-$V.log" 2>&1 \
        || die "screen-flow tests ($V): COLDCARD behaves differently now" "$LOGS/flows-$V.log"
    echo "   flows: $(grep -c '^== ' "$LOGS/flows-$V.log") steps passed (log: build/release-logs/flows-$V.log)"
    ( cd "$PORT" && "$M" -X heapsize=4m tests/test_keymap.py ) > "$LOGS/keymap-$V.log" 2>&1 \
        || die "keyboard map test ($V)" "$LOGS/keymap-$V.log"
    echo "   keyboard map: ok"
    if command -v hwi >/dev/null && python3 -c "import embit" 2>/dev/null; then
        ( cd "$PORT" && VARIANT=$V tests/test_usb.sh ) > "$LOGS/usb-$V.log" 2>&1 \
            || die "USB / wallet software test ($V)" "$LOGS/usb-$V.log"
        echo "   USB with HWI (Sparrow's library): ok"
    else
        echo "   USB test skipped (pip install hwi embit to enable)"
    fi
done
if [ -z "$SKIP_TESTS" ]; then
    M=$(host_bin $(set -- $VARIANTS; echo $1))
    ( cd "$PORT" && "$M" -X heapsize=24m tests/test_launcher_layout.py ) > "$LOGS/layout.log" 2>&1 \
        || die "M5Launcher storage layout test" "$LOGS/layout.log"
    echo "   M5Launcher storage layout: ok"
fi

# ---- 3. device images (ESP-IDF set up only now: its Python environment
# needn't have the test tools)
if ! command -v idf.py >/dev/null; then
    for f in "${IDF_PATH:-}/export.sh" "$HOME/esp-idf/export.sh" /opt/esp/idf/export.sh; do
        [ -f "$f" ] && { export IDF_PYTHON_CHECK_CONSTRAINTS=no; . "$f" >/dev/null 2>&1 && break; }
    done
fi
command -v idf.py >/dev/null || die "ESP-IDF not found. Install v5.5.4 (BUILDING.md) or use the Docker image."

say "3. device images"
OUTS=()
for V in $VARIANTS; do
    for L in $LAYOUTS; do
        echo "   building $V / $L ..."
        VARIANT=$V LAYOUT=$L "$PORT/tools/build_device.sh" > "$LOGS/device-$V-$L.log" 2>&1 \
            || { patch_help "$LOGS/device-$V-$L.log"; die "device build $V/$L failed" "$LOGS/device-$V-$L.log"; }
        D=$PORT/build/device; [ "$V" = q1 ] || D=$D-$V; [ "$L" = own ] || D=$D-$L
        OUTS+=("$V:$L:$D")
    done
done

# ---- 4. dist
VER_OF() { python3 -c "import sys; sys.path.insert(0, '$1/py'); import cp_buildinfo; print(cp_buildinfo.VERSION.replace('-cp', ''))"; }
TAG=$(for o in "${OUTS[@]}"; do IFS=: read V L D <<< "$o"; VER_OF "$D"; done | sort -u | paste -sd_ -)
OUT=$DIST/$TAG-$CC_COMMIT
rm -rf "$OUT"          # only this build's files
mkdir -p "$OUT"
say "4. images in ${OUT#$PORT/}"
: > "$OUT/SHA256SUMS.txt"
for o in "${OUTS[@]}"; do
    IFS=: read V L D <<< "$o"
    VER=$(VER_OF "$D")
    ED=keypad; [ "$V" = q1 ] && ED=qwerty      # Keypad edition (Mk5 firmware), QWERTY edition (Q)
    NAME=lukewarmcard-adv-$ED-$VER-$L.bin
    [ "$L" = own ] && NAME=lukewarmcard-adv-$ED-$VER-full-flash.bin
    cp "$D/firmware.bin" "$OUT/$NAME"
    (cd "$OUT" && sha256sum "$NAME" >> SHA256SUMS.txt)
done
for f in "$PORT"/licenses/*.txt; do cp "$f" "$OUT/"; done
cp "$PORT/NOTICE.md" "$PORT/LICENSE" "$OUT/"
cat > "$OUT/BUILDINFO.txt" <<EOF
LukewarmCard ADV - unofficial port of COLDCARD firmware to the M5Stack
Cardputer ADV. Not affiliated with or endorsed by Coinkite. See NOTICE.md.

  *-keypad-*   Keypad edition: runs COLDCARD Mk4/Mk5 firmware
  *-qwerty-*   QWERTY edition (if built): runs COLDCARD Q firmware, experimental

COLDCARD source:  $(grep '^Setup done' "$LOGS/setup.log" | sed 's/Setup done: COLDCARD //')
MicroPython:      v1.29.0
ESP-IDF:          $(idf.py --version 2>/dev/null | head -1)
Built:            $(date -u '+%Y-%m-%d %H:%M UTC')
Tests:            $([ -n "$SKIP_TESTS" ] && echo skipped || echo passed)

*-launcher.bin    install with M5Launcher (SD card > the .bin)
*-full-flash.bin  write at offset 0x0 with esptool or a web flasher (erases Launcher)
EOF
(cd "$OUT" && ls -l *.bin && cat SHA256SUMS.txt)
echo
echo "Done. Before installing over an existing wallet: Advanced/Tools > Backup."
