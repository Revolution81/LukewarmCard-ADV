#!/bin/bash
# Run "log in + sign a PSBT from SD" under shrinking heap limits to find the
# minimum heap the firmware needs. Uses checkpoint dir cp-work.wallet.
# Usage: heap_sweep.sh <run-dir> <psbt> <heap sizes...>
RUN=$1; PSBT=$2; shift 2
PORT=$(cd "$(dirname "$0")/.." && pwd)
M=$PORT/build/host/cc-mpy
cd "$RUN"
for hs in "$@"; do
    rm -rf cp-work && cp -r cp-work.wallet cp-work
    $M "$PORT/tools/sdtool.py" cp-work/sdcard.img put "$PSBT" test.psbt >/dev/null 2>&1
    out=$(CP_SCRIPT=$RUN/signchk.txt timeout 300 $M -X heapsize=$hs -m host_main 2>&1)
    if echo "$out" | grep -q "\[ok\] PSBT Signed"; then
        r="PASS  $(echo "$out" | grep '\[mem\]' | tail -1)"
    else
        r="FAIL  $(echo "$out" | grep -iE "MemoryError|Error|FAIL" | head -1)"
    fi
    echo "heap $hs: $r"
done
