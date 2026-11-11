#!/bin/bash
# End-to-end test on the desktop build, from a blank device:
#   set PIN -> import test seed -> sign a PSBT from microSD -> verify signature
# Needs: tools/build_host_fw.sh done, python3 with embit (pip install embit).
# Usage: tests/run_flows.sh [heapsize]     e.g. 320k (default 1m)
#        (Keypad edition: tests/flows-mk4, plus duress-PIN and fingerprint checks)
set -e
PORT=$(cd "$(dirname "$0")/.." && pwd)
VARIANT=mk4      # Keypad edition (COLDCARD Mk4/Mk5 firmware)
M=$PORT/build/host-$VARIANT/cc-mpy; FLOWS=$PORT/tests/flows-$VARIANT
LAYOUT=${LAYOUT:-own}
[ "$LAYOUT" = own ] || M=$(dirname "$M")-$LAYOUT/cc-mpy
[ -n "$CC_MPY" ] && M=$CC_MPY     # e.g. the 32-bit build (tools/build_host_fw.sh BITS=32)
echo "variant: $VARIANT, layout: $LAYOUT ($M)"
HEAP=${1:-1m}
RUN=$(mktemp -d)
export CP_WORK=$RUN/cp-work
cd "$RUN"

step() {
    echo "== $1"
    CP_SCRIPT=$FLOWS/$1 timeout 300 "$M" -X heapsize=$HEAP -m host_main > "$1.log" 2>&1 || true
    if grep -q "\[FAIL\]\|Traceback\|Yikes" "$1.log"; then
        grep -A12 "\[FAIL\]\|Traceback\|Yikes" "$1.log" | head -30
        echo "FAILED: $1 (log: $RUN/$1.log)"; exit 1
    fi
    grep "\[ok\]\|\[mem\]" "$1.log" | sed 's/^/   /'
}

step 01_set_pin.txt
step 02_import_seed.txt

# Mk5 firmware only uses the MK5 folder of the card (features.SD_SUBDIR)
SDDIR="MK5/"
echo "not ours" > other.txt
"$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" put other.txt other-app.txt >/dev/null
python3 "$PORT/tools/make_test_psbt.py" test.psbt >/dev/null
"$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" put test.psbt ${SDDIR}test.psbt >/dev/null
step 03_sign_psbt.txt

echo "== SD card contents"
"$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls | sed 's/^/   \/ /'
[ -n "$SDDIR" ] && "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "$SDDIR" | sed "s|^|   /$SDDIR|"
"$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" get ${SDDIR}test-signed.psbt signed.psbt >/dev/null \
    || { echo "FAILED: signed PSBT not found in /${SDDIR}"; exit 1; }
"$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" get other-app.txt other.chk >/dev/null && cmp -s other.txt other.chk \
    || { echo "FAILED: file outside the firmware's folder changed"; exit 1; }
if [ -n "$SDDIR" ]; then
    if "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls | grep -q "test-signed"; then
        echo "FAILED: firmware wrote to the card root"; exit 1
    fi
    echo "   ok: signed PSBT saved in /$SDDIR, nothing written outside it"
fi
echo "== independent signature check (embit)"
python3 "$PORT/tools/check_signed_psbt.py" signed.psbt | sed 's/^/   /'

if [ "$VARIANT" = mk4 ]; then
    fp_of() { grep -A12 "Fingerprint:" "$1" | grep -oE "[0-9A-F]{8}" | head -1; }
    step 12_main_identity.txt
    echo "   main wallet fingerprint: $(fp_of 12_main_identity.txt.log)"
    [ "$(fp_of 12_main_identity.txt.log)" = 73C5DA0A ] || { echo "FAILED: main fingerprint"; exit 1; }
    step 10_add_duress_pin.txt
    step 11_duress_login.txt
    echo "   duress wallet fingerprint: $(fp_of 11_duress_login.txt.log)"
    WANT=$(python3 -I "$PORT/tools/bip85_fp.py" 2001)
    echo "   embit, BIP-85 index 2001:  $WANT"
    [ "$(fp_of 11_duress_login.txt.log)" = "$WANT" ] || { echo "FAILED: duress fingerprint"; exit 1; }

    # The key went to the SD card when the PIN was set (Key Storage default):
    # internal flash holds only a pointer
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "${SDDIR}.keystore" | grep -q "^key[01].bin" \
        || { echo "FAILED: key not on the SD card"; exit 1; }
    grep -q "CPSE" "$CP_WORK/se.bin" && { echo "FAILED: key record still in internal flash"; exit 1; }
    echo "   ok: key on the SD card (/${SDDIR}.keystore), internal flash holds a pointer only"

    # Power on without the card: asks for it; after login it can come out
    touch "$CP_WORK/card-out"
    step 17_key_card_missing.txt
    rm -f "$CP_WORK/card-out"

    # Key Storage menu: to internal flash, log in, back to the card
    step 16_key_to_flash.txt
    grep -q "CPSE" "$CP_WORK/se.bin" || { echo "FAILED: key not in internal flash"; exit 1; }
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "${SDDIR}.keystore" 2>/dev/null | grep -q "key" \
        && { echo "FAILED: key left on the SD card"; exit 1; }
    echo "   ok: Key Storage > internal flash: key moved, nothing left on the card"
    step 12_main_identity.txt
    [ "$(fp_of 12_main_identity.txt.log)" = 73C5DA0A ] || { echo "FAILED: login from internal flash"; exit 1; }
    echo "   ok: chose internal flash: logs in from it, not asked to move"
    step 16_key_to_sd.txt
    grep -q "CPSE" "$CP_WORK/se.bin" && { echo "FAILED: key still in internal flash"; exit 1; }
    echo "   ok: Key Storage > SD card: key moved back"
    # brand-new device without a card: key goes to internal flash, no questions
    NEW=$RUN/cp-work-nocard
    mkdir -p "$NEW"
    ( export CP_WORK=$NEW; touch "$NEW/card-out"; step 01_set_pin.txt; rm -f "$NEW/card-out"
      grep -q "CPSE" "$CP_WORK/se.bin" || { echo "FAILED: no card, key not in internal flash"; exit 1; } ) || exit 1
    echo "   ok: new device without a card: key in internal flash"
    # then Key Storage > SD card moves it
    ( export CP_WORK=$NEW; step 02_import_seed.txt; step 16_key_to_sd.txt
      grep -q "CPSE" "$CP_WORK/se.bin" && { echo "FAILED: key still in internal flash"; exit 1; }
      "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "${SDDIR}.keystore" | grep -q "^key[01].bin" \
          || { echo "FAILED: key not on the card"; exit 1; } ) || exit 1
    echo "   ok: Key Storage > SD card: moved, internal flash a pointer only"

    # Backup to SD:/MK5, then "reinstall": a new device whose only data is
    # the SD card. With the key on the card, the wallet is simply there.
    step 20_backup.txt
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "$SDDIR" | grep -q "^backup.7z" \
        || { echo "FAILED: backup.7z not in /$SDDIR"; exit 1; }
    if "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls | grep -q "\.7z"; then
        echo "FAILED: backup written to the card root"; exit 1
    fi
    echo "   ok: backup.7z saved in /$SDDIR"
    echo "== reinstall: new device, same SD card"
    OLD_WORK=$CP_WORK
    export CP_WORK=$RUN/cp-work-reinstalled
    mkdir -p "$CP_WORK"
    cp "$OLD_WORK/sdcard.img" "$OLD_WORK/backup-words.txt" "$CP_WORK/"
    step 12_main_identity.txt
    [ "$(fp_of 12_main_identity.txt.log)" = 73C5DA0A ] || { echo "FAILED: wallet from key card after reinstall"; exit 1; }
    echo "   ok: reinstalled device found the key on the card (no restore needed)"

    # And without the key folder (key was in internal flash): restore from
    # the backup; both PINs must work again.
    echo "== reinstall: new device, SD card without a key"
    export CP_WORK=$RUN/cp-work-restored
    mkdir -p "$CP_WORK"
    cp "$OLD_WORK/sdcard.img" "$OLD_WORK/backup-words.txt" "$CP_WORK/"
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" rm "${SDDIR}.keystore" >/dev/null
    step 01_set_pin.txt
    step 21_restore.txt
    step 12_main_identity.txt
    echo "   main wallet fingerprint after restore: $(fp_of 12_main_identity.txt.log)"
    [ "$(fp_of 12_main_identity.txt.log)" = 73C5DA0A ] || { echo "FAILED: main fingerprint after restore"; exit 1; }
    step 11_duress_login.txt
    echo "   duress wallet fingerprint after restore: $(fp_of 11_duress_login.txt.log)"
    [ "$(fp_of 11_duress_login.txt.log)" = "$WANT" ] || { echo "FAILED: duress PIN after restore"; exit 1; }
    step 22_format_sd.txt
    LEFT=$("$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "$SDDIR" | grep -v "^\.keystore/\|^\.vdisk/" | wc -l)
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "${SDDIR}.keystore" | grep -q "^key[01].bin" \
        || { echo "FAILED: Format SD Card deleted the key"; exit 1; }
    [ "$LEFT" = 0 ] || { echo "FAILED: /$SDDIR not empty after Format SD Card ($LEFT files)"; exit 1; }
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" get other-app.txt other.chk >/dev/null && cmp -s other.txt other.chk \
        || { echo "FAILED: Format SD Card touched files outside /$SDDIR"; exit 1; }
    echo "   ok: Format SD Card emptied /$SDDIR only (key kept); other-app.txt untouched"
fi

# Advanced/Tools > Entropy Sources; Upgrade Firmware > From MicroSD explains
step 14_entropy_upgrade.txt
# Perform Selftest: Cardputer parts (USB light = RGB LED, mic, gyro, SD)
step 15_selftest.txt
# regressions found by the monkey test (tests/stress.sh)
step 24_passphrase.txt      # letter-entry screen; passphrase fingerprint vs embit

if [ "$VARIANT" = mk4 ]; then
    # Virtual Disk (4MB image on the SD card): drop a PSBT on it, sign, read back
    step 23_vdisk.txt
    python3 "$PORT/tools/check_signed_psbt.py" vd-signed.psbt | grep -q VALID \
        || { echo "FAILED: signed PSBT from the Virtual Disk"; exit 1; }
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "${SDDIR}.vdisk" | grep -q "^vdisk.img" \
        || { echo "FAILED: disk image not on the card"; exit 1; }
    "$M" "$PORT/tools/sdtool.py" "$CP_WORK/sdcard.img" ls "$SDDIR" | grep -q "test-final.txn" \
        && { echo "FAILED: Virtual Disk files leaked into the SD folder"; exit 1; }
    echo "   ok: Virtual Disk: PSBT dropped on the drive, signed (VALID), result on the drive;"
    echo "       image at /${SDDIR}.vdisk/vdisk.img, nothing else on the card touched"
fi

# Test Login Now = restart (callgate.show_logout(2)), then log in again
echo "== 13_test_login.txt"
CP_SCRIPT=$FLOWS/13_test_login.txt timeout 300 "$M" -X heapsize=$HEAP -m host_main > 13_test_login.txt.log 2>&1 || true
grep -q "reset requested" 13_test_login.txt.log || { tail -15 13_test_login.txt.log; echo "FAILED: Test Login Now did not restart"; exit 1; }
grep -q "Logged out" 13_test_login.txt.log && { echo "FAILED: Test Login Now showed Logged out"; exit 1; }
echo "   ok: Test Login Now restarts"
step 12_main_identity.txt
echo "   ok: logged in again after the restart"

echo "== secure element unit tests"
"$M" -X heapsize=4m "$PORT/tests/test_softse.py" | tail -1 | sed 's/^/   /'
echo "== Virtual Disk image tests (SD card)"
mkdir -p "$RUN/vd-work"
( cd "$PORT" && CP_WORK=$RUN/vd-work "$M" -X heapsize=4m tests/test_vdisk.py ) > vdisk.log 2>&1 || true
grep -c "^  ok" vdisk.log | sed 's/^/   checks passed: /'
grep -q "^0 failure(s)" vdisk.log || { grep "FAIL\|Traceback" -A5 vdisk.log; echo "FAILED: Virtual Disk tests (log: $RUN/vdisk.log)"; exit 1; }
echo "== key storage tests (internal flash / SD card)"
mkdir -p "$RUN/ks-work"
( cd "$PORT" && CP_WORK=$RUN/ks-work "$M" -X heapsize=4m tests/test_keystore.py ) > keystore.log 2>&1 || true
grep -c "^  ok" keystore.log | sed 's/^/   checks passed: /'
grep -q "^0 failure(s)" keystore.log || { grep "FAIL\|Traceback" -A5 keystore.log; echo "FAILED: key storage tests (log: $RUN/keystore.log)"; exit 1; }
echo "== entropy source tests (microphone, motion sensor, chip RNG)"
( cd "$PORT" && "$M" -X heapsize=4m tests/test_entropy.py ) > entropy.log 2>&1 || true
grep -c "^  ok" entropy.log | sed 's/^/   checks passed: /'
grep -q "^0 failure(s)" entropy.log || { grep "FAIL\|Traceback" -A5 entropy.log; echo "FAILED: entropy tests (log: $RUN/entropy.log)"; exit 1; }

python3 "$PORT/tools/host_shots.py" "$CP_WORK/shots" 3 >/dev/null 2>&1 || echo "(screenshots left as .rgb565: pip install pillow to convert)"
echo
echo "ALL PASSED. Screenshots: $CP_WORK/shots/*.png"
