#!/bin/bash
# tests/test_usb.sh - the COLDCARD USB link (what Sparrow, Electrum etc use).
#
#  1. hal/device/cp_usb.py, the Cardputer's USB code, against a fake USB
#     controller (tests/test_usb_device.py): descriptors, packets, waiting.
#  2. The desktop firmware driven by the real wallet tools, over the socket
#     where they look for a COLDCARD simulator: HWI (which Sparrow uses) and
#     Coinkite's ckcc. Fresh device -> set PIN -> import test seed -> turn USB
#     on in the menus -> HWI finds it, reads keys, signs a PSBT (approved on
#     screen by the test script), shows an address. Everything checked
#     against embit.
#
# Needs: tools/build_host_fw.sh done; pip: hwi ckcc-protocol embit
#        (HWI 3.x: pip install --ignore-requires-python hwi==3.2.0 on Python 3.13)
# Usage: tests/test_usb.sh [heapsize]            Q firmware
#        VARIANT=mk4 tests/test_usb.sh [heapsize] Mk5 firmware
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
VARIANT=${VARIANT:-q1}
HEAP=${1:-320k}
if [ "$VARIANT" = q1 ]; then
    M=$PORT/build/host/cc-mpy; FLOWS=$PORT/tests/flows
else
    M=$PORT/build/host-$VARIANT/cc-mpy; FLOWS=$PORT/tests/flows-$VARIANT
fi
CC=${CC_REPO:-$HOME/cardputer-cc-src/coldcard}
MPY=${MPY:-$HOME/cardputer-cc-src/micropython}
SOCK=/tmp/ckcc-simulator.sock      # fixed: HWI and ckcc look here
HWI="hwi -t coldcard -d $SOCK --chain test"
RUN=$(mktemp -d)
echo "variant: $VARIANT, heap $HEAP, work: $RUN"
cd "$RUN"

fail() { echo "FAILED: $*"; exit 1; }

echo "== 1. device USB module vs fake USB controller"
( cd "$PORT" && CC_USB_PY=$CC/shared/usb.py \
    "$M" -X heapsize=4m tests/test_usb_device.py ) > device.log 2>&1 || true
grep -c "^  ok" device.log | sed 's/^/   checks passed: /'
grep "FAIL\|Traceback" device.log && fail "device USB module (log: $RUN/device.log)"
grep -q "^0 failure(s)" device.log || fail "device USB module (log: $RUN/device.log)"

echo "== 1b. Virtual Disk USB drive (mass storage) vs fake USB controller"
( cd "$PORT" && CC_USB_PY=$CC/shared/usb.py \
    "$M" -X heapsize=16m tests/test_usb_msc.py ) > msc.log 2>&1 || true
grep -c "^  ok" msc.log | sed 's/^/   checks passed: /'
grep "FAIL\|Traceback" msc.log && fail "USB drive (log: $RUN/msc.log)"
grep -q "^0 failure(s)" msc.log || fail "USB drive (log: $RUN/msc.log)"

echo "== 2. firmware + HWI / ckcc"
export CP_WORK=$RUN/cp-work
mkdir -p "$CP_WORK"
step() {
    CP_SCRIPT=$FLOWS/$1 timeout 300 "$M" -X heapsize=$HEAP -m host_main > "$1.log" 2>&1 || true
    grep -q "\[FAIL\]\|Traceback\|Yikes" "$1.log" && { grep -A12 "\[FAIL\]\|Traceback" "$1.log" | head -20; fail "$1"; }
    echo "   $1 ok"
}
step 01_set_pin.txt
step 02_import_seed.txt

# the device side: logs in, turns USB on, approves, looks at the address
rm -f "$SOCK"
CP_USB_SOCK=$SOCK CP_SCRIPT=$FLOWS/30_usb.txt timeout 300 "$M" -X heapsize=$HEAP -m host_main \
    > fw.log 2>&1 &
FW=$!
for i in $(seq 120); do grep -q "\[usb\] on" fw.log && break; sleep 0.5; done
grep "\[usb\] on" fw.log | sed 's/^/   /' || { tail -20 fw.log; fail "USB never came on"; }
sleep 1.5       # back at the main menu

python3 -I - > want.json <<'EOF'
import json
from embit import bip39, bip32, script
from embit.networks import NETWORKS
root = bip32.HDKey.from_seed(bip39.mnemonic_to_seed("abandon " * 11 + "about"))
T = NETWORKS['test']
print(json.dumps({
    'fp': root.my_fingerprint.hex(),
    'x84': root.derive("m/84h/1h/0h").to_public().to_base58(version=T['xpub']),
    'x49': root.derive("m/49h/1h/0h").to_public().to_base58(version=T['xpub']),
    'addr': script.p2wpkh(root.derive("m/84h/1h/0h/0/0").key).address(T),
}))
EOF
want() { python3 -c "import json; print(json.load(open('want.json'))['$1'])"; }

hwi --emulators enumerate > enum.json
python3 - <<'EOF' || fail "HWI enumerate"
import json
d = [x for x in json.load(open('enum.json')) if x['type'] == 'coldcard']
want = json.load(open('want.json'))
print('   HWI enumerate:', d)
assert d and d[0]['fingerprint'] == want['fp'], 'fingerprint'
EOF
echo "   ok: HWI finds a COLDCARD, fingerprint $(want fp)"

for P in 84 49; do
    GOT=$($HWI getxpub "m/${P}h/1h/0h" | python3 -c "import json,sys; print(json.load(sys.stdin)['xpub'])")
    [ "$GOT" = "$(want x$P)" ] || fail "xpub m/${P}h/1h/0h: $GOT"
    echo "   ok: xpub m/${P}h/1h/0h matches embit"
done

echo "   ckcc (Coinkite's tool):"
ckcc -x version 2>&1 | head -3 | sed 's/^/     /'
ckcc -x xfp 2>&1 | tail -1 | sed 's/^/     xfp: /'

python3 "$PORT/tools/make_test_psbt.py" test.psbt > /dev/null
$HWI signtx "$(base64 -w0 test.psbt)" 2>/dev/null | grep '^{' > sign.json
python3 -c "
import json, base64; d = json.load(open('sign.json'))
assert 'psbt' in d, d
open('signed.psbt', 'wb').write(base64.b64decode(d['psbt']))" || fail "HWI signtx: $(cat sign.json)"
python3 "$PORT/tools/check_signed_psbt.py" signed.psbt | sed 's/^/   /'
python3 "$PORT/tools/check_signed_psbt.py" signed.psbt | grep -q VALID || fail "signature"
echo "   ok: HWI signtx -> approved on screen -> signature VALID (embit)"

ADDR=$($HWI displayaddress --path "m/84h/1h/0h/0/0" --addr-type wit \
       | python3 -c "import json,sys; print(json.load(sys.stdin)['address'])")
[ "$ADDR" = "$(want addr)" ] || fail "displayaddress: $ADDR"
echo "   ok: HWI displayaddress $ADDR matches embit"

wait $FW || true
grep -q "\[FAIL\]\|Traceback\|Yikes" fw.log && { grep -A12 "\[FAIL\]\|Traceback" fw.log | head -20; fail "device side (log: $RUN/fw.log)"; }
grep "\[ok\]\|\[mem\]" fw.log | sed 's/^/   device: /'
grep -A4 "\[screen\]" fw.log | head -0
echo "ALL PASSED ($VARIANT). Screenshots: $CP_WORK/shots/usb_*.png"
