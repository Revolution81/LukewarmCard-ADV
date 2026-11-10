#!/bin/bash
# tests/stress.sh - pre-release stress tests on the desktop build:
#
#  1. leak test: sign the same transaction 25 times in a row (dropped on the
#     Virtual Disk each time); free memory after each signing must not keep
#     falling
#  2. monkey test: random keypresses through the menus (tests/monkey.py),
#     looking for crashes, tracebacks, memory errors, hangs
#
# Usage: VARIANT=mk4 tests/stress.sh [heap] [cc-mpy]     (leak test is Keypad edition only)
#        VARIANT=q1  tests/stress.sh [heap] [cc-mpy]
# Best with the 32-bit build (BITS=32 tools/build_host_fw.sh): object sizes
# match the ESP32, so the memory numbers mean the same thing.
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
VARIANT=${VARIANT:-mk4}
HEAP=${1:-320k}
if [ "$VARIANT" = q1 ]; then DEF=$PORT/build/host/cc-mpy; FLOWS=$PORT/tests/flows
else DEF=$PORT/build/host-$VARIANT/cc-mpy; FLOWS=$PORT/tests/flows-$VARIANT; fi
M=${2:-$DEF}
RUN=$(mktemp -d)
cd "$RUN"
echo "variant $VARIANT, heap $HEAP, $M, work $RUN"
python3 "$PORT/tools/make_test_psbt.py" test.psbt > /dev/null

if [ "$VARIANT" = mk4 ]; then
    echo "== 1. leak test: 25 signings in a row"
    export CP_WORK=$RUN/leak
    mkdir -p "$CP_WORK"
    for f in 01_set_pin.txt 02_import_seed.txt; do
        CP_SCRIPT=$FLOWS/$f timeout 300 "$M" -X heapsize=$HEAP -m host_main > $f.log 2>&1 || true
    done
    # Virtual Disk on (Enable & Auto), then 25 x: drop PSBT, approve, close
    { sed -n '1,/^pick Enable & Auto$/p' "$FLOWS/23_vdisk.txt"
      printf 'wait 8000\nkey x\nwait 500\nkey x\nwait 500\nkey x\nwait 800\nmem start\n'
      for i in $(seq 1 25); do
          # sign, then the "computer" deletes the files again, so the disk
          # doesn't fill up (COLDCARD keeps a list of what's on it); also
          # forget COLDCARD's UTXO-amount history (by design grows to 128
          # entries, ~5K), so only real leaks show
          printf 'vdput test.psbt t%d.psbt\nwait 4000\nexpect OK TO SEND?\nkey y\nwait 4500\nexpect PSBT Signed\nkey x\nwait 1500\nvdrm t%d.psbt t%d-signed.psbt t%d-final.txn\nwait 2500\novcclear\nprobe\nmem sign%d\n' $i $i $i $i $i
      done
      # the cached secret must still be wiped after a minute unused
      printf 'wait 75000\npy import stash; print("[cache] " + ("cleared" if stash.SensitiveValues._cache_secret is None else "STILL SET"))\nquit\n'; } > leak.txt
    CP_SCRIPT=$RUN/leak.txt timeout 1000 "$M" -X heapsize=$HEAP -m host_main > leak.log 2>&1 || true
    if grep -q "Yikes\|Traceback\|MemoryError\|\[FAIL\]" leak.log; then
        grep -B2 -A8 "Yikes\|Traceback\|MemoryError\|\[FAIL\]" leak.log | head -30
        echo "FAILED: leak test (log: $RUN/leak.log)"; exit 1
    fi
    python3 - leak.log <<'EOF'
import re, sys
v = [int(x) for x in re.findall(r'\[mem\] sign\d+ free=(\d+)', open(sys.argv[1]).read())]
start = int(re.search(r'\[mem\] start free=(\d+)', open(sys.argv[1]).read()).group(1))
assert len(v) == 25, 'only %d signings completed' % len(v)
print('   signings completed: %d' % len(v))
print('   free after login: %d bytes; after signings: first %d, last %d, lowest %d' % (start, v[0], v[-1], min(v)))
drift = v[4] - v[-1]          # after warm-up (caches fill during the first few)
print('   drift from signing 5 to 25: %+d bytes' % -drift)
if drift > 1024:
    sys.exit('FAILED: free memory keeps falling (leak?)')
print('   ok: no leak')
if '[cache] cleared' not in open(sys.argv[1]).read():
    sys.exit('FAILED: cached secret not wiped after a minute unused')
print('   ok: cached secret wiped after a minute unused')
EOF
fi

echo "== 2. monkey test: random keys through the menus"
python3 "$PORT/tests/monkey.py" "$VARIANT" ${MONKEY_RUNS:-6} ${MONKEY_KEYS:-500} "$HEAP" "$M"
echo "ALL STRESS TESTS PASSED ($VARIANT)"
