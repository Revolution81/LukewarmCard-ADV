#!/bin/bash
# Build a desktop (unix) MicroPython with the same C modules as the Cardputer
# firmware. Used to test the Coldcard Python code and measure RAM use.
set -e
MPY=${MPY:-$HOME/cardputer-cc-src/micropython}
PORT=$(cd "$(dirname "$0")/.." && pwd)
cd "$MPY/ports/unix"
make -j"$(nproc)" VARIANT=standard USER_C_MODULES="$PORT/cmodules" \
    NGU_NEEDS_CIFRA=1 BUILD=build-cc PROG=cc-mpy \
    MICROPY_PY_THREAD=0 MICROPY_SSL_MBEDTLS=0 MICROPY_PY_SSL=0 "$@" 2>&1 \
    | grep -E "error:|Error [0-9]|undefined reference" | sort -u | head -40
ls -la "$MPY/ports/unix/build-cc/cc-mpy" 2>/dev/null || ls -la cc-mpy
