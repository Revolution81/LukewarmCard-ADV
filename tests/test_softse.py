# Unit tests for the emulated secure element (hal/common/secel_soft.py).
# Run with the desktop-test build:  build/host/cc-mpy tests/test_softse.py
import os, sys, ustruct

WORK = os.getcwd() + '/softse-test'
try:
    os.mkdir(WORK)
except OSError:
    pass

import glob
class _Settings:
    # minimal stand-in for COLDCARD's settings object (no trick PINs defined)
    def get(self, key, default=None):
        return default
    def set(self, *a): pass
    def save(self): pass
glob.settings = _Settings()

import cp_board
from secel_soft import SoftSE, SECRET_LEN
import pincodes
from pincodes import (PIN_ATTEMPT_FMT_V1, PIN_ATTEMPT_SIZE, PA_IS_BLANK, PA_SUCCESSFUL,
                      PA_ZERO_SECRET, CHANGE_WALLET_PIN, CHANGE_SECRET, PA_MAGIC_V2)
import features

FAILS = []
def check(cond, msg):
    print(('PASS ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)

def attempt(pin=b'', change=0, old=b'', new=b'', secret=bytes(72)):
    buf = bytearray(PIN_ATTEMPT_SIZE)
    ustruct.pack_into(PIN_ATTEMPT_FMT_V1, buf, 0, PA_MAGIC_V2, 0, pin, len(pin),
                      0, 0, 0, 0, 0, 0, bytes(32), change, old, len(old), new, len(new), secret)
    return buf

def state(buf):
    f = ustruct.unpack_from(PIN_ATTEMPT_FMT_V1, buf)
    return dict(num_fails=f[6], attempts_left=f[7], flags=f[8], secret=bytes(f[16]))

def fresh(name):
    fn = WORK + '/' + name
    try:
        os.remove(fn)
    except OSError:
        pass
    return SoftSE(cp_board.FileStore(fn))

SEED = bytes([0x80]) + bytes(range(1, 17)) + bytes(72 - 17)   # "12-word" secret
PIN = b'12-34'

# --- setup + login ---
se = fresh('a.bin')
b = attempt(); se.pin_stuff(0, b)
check(state(b)['flags'] & PA_IS_BLANK, 'new device reports blank')

b = attempt(PIN, change=CHANGE_WALLET_PIN | CHANGE_SECRET, new=PIN, secret=SEED)
check(se.pin_stuff(3, b) == 0, 'set PIN + secret')

se = SoftSE(cp_board.FileStore(WORK + '/a.bin'))          # "reboot"
b = attempt(); se.pin_stuff(0, b)
check(not (state(b)['flags'] & PA_IS_BLANK), 'not blank after reboot')

b = attempt(PIN); rv = se.pin_stuff(2, b)
check(rv == 0 and state(b)['flags'] & PA_SUCCESSFUL, 'login with right PIN')
b = attempt(PIN); se.pin_stuff(4, b)
check(state(b)['secret'] == SEED, 'secret survives reboot, decrypts')

raw = open(WORK + '/a.bin', 'rb').read()
check(SEED[1:17] not in raw, 'seed bytes not stored in the clear')
check(PIN not in raw, 'PIN not stored in the clear')

b = attempt(b'99-99'); rv = se.pin_stuff(2, b)
check(rv != 0, 'wrong PIN rejected')
b = attempt(b'99-99'); rv = se.pin_stuff(4, b)
check(rv != 0, 'wrong PIN cannot fetch secret')

# --- failed attempts: 'wipe' policy ---
features.ON_MAX_PIN_ATTEMPTS = 'wipe'
se = fresh('w.bin')
se.pin_stuff(3, attempt(PIN, change=CHANGE_WALLET_PIN | CHANGE_SECRET, new=PIN, secret=SEED))
for i in range(features.MAX_PIN_ATTEMPTS - 1):
    se.pin_stuff(2, attempt(b'00-00'))
check(se.secret_ct is not None, 'seed kept after %d failures' % (features.MAX_PIN_ATTEMPTS - 1))
se.pin_stuff(2, attempt(b'00-00'))
check(se.secret_ct is None, "seed wiped at failure #%d ('wipe')" % features.MAX_PIN_ATTEMPTS)
b = attempt(PIN); rv = se.pin_stuff(2, b)
check(rv == 0 and state(b)['flags'] & PA_ZERO_SECRET, 'right PIN still works, wallet empty (not bricked)')

# --- failed attempts: 'none' policy ---
features.ON_MAX_PIN_ATTEMPTS = 'none'
se = fresh('n.bin')
se.pin_stuff(3, attempt(PIN, change=CHANGE_WALLET_PIN | CHANGE_SECRET, new=PIN, secret=SEED))
for i in range(30):
    se.pin_stuff(2, attempt(b'00-00'))
b = attempt(PIN); se.pin_stuff(2, b); se.pin_stuff(4, b)
check(state(b)['secret'] == SEED, "'none': 30 failures, seed untouched")
features.ON_MAX_PIN_ATTEMPTS = 'wipe'

# --- tampering with the stored blob is detected ---
se = fresh('t.bin')
se.pin_stuff(3, attempt(PIN, change=CHANGE_WALLET_PIN | CHANGE_SECRET, new=PIN, secret=SEED))
import ujson
from ubinascii import a2b_base64, b2a_base64
raw = open(WORK + '/t.bin', 'rb').read()
d = ujson.loads(raw[4:])
s = bytearray(a2b_base64(d['sec'])); s[-1] ^= 1
d['sec'] = b2a_base64(bytes(s)).strip().decode()
open(WORK + '/t.bin', 'wb').write(b'CPSE' + ujson.dumps(d).encode())
se = SoftSE(cp_board.FileStore(WORK + '/t.bin'))
b = attempt(PIN); se.pin_stuff(2, b); se.pin_stuff(4, b)
check(state(b)['secret'] != SEED, 'modified ciphertext is rejected (no garbage seed)')

# --- brick paths: must erase data, then the device works again as blank ---
from trick_pins import TC_WIPE, TC_BRICK

def stops(fn):
    # emulated brick/wipe screens halt (desktop build: SystemExit)
    try:
        fn()
    except SystemExit:
        return True
    return False

def setup(name):
    se = fresh(name)
    se.pin_stuff(3, attempt(PIN, change=CHANGE_WALLET_PIN | CHANGE_SECRET, new=PIN, secret=SEED))
    return se

def reboot(name):
    return SoftSE(cp_board.FileStore(WORK + '/' + name))

def is_blank(se):
    b = attempt(); se.pin_stuff(0, b)
    return bool(state(b)['flags'] & PA_IS_BLANK) and se.secret_ct is None and not se.slots

def make_slot(sn, flags, arg, pin):
    s = bytearray(128)
    ustruct.pack_into('<iHH', s, 0, sn, flags, arg)
    s[72:72+len(pin)] = pin
    ustruct.pack_into('<i', s, 88, len(pin))
    return s

def add_slot(se, slot):
    buf = bytearray(PIN_ATTEMPT_SIZE) + slot
    se.dmk = se._get_dmk(se._pin_k(PIN))
    se.se2_callgate(buf, 2)

# 13 wrong PINs, policy 'brick'
features.ON_MAX_PIN_ATTEMPTS = 'brick'
se = setup('b.bin')
for i in range(features.MAX_PIN_ATTEMPTS - 1):
    se.pin_stuff(2, attempt(b'00-00'))
check(se.secret_ct is not None, "'brick': seed kept after 12 failures")
check(stops(lambda: se.pin_stuff(2, attempt(b'00-00'))), "'brick': failure #13 stops the device")
se = reboot('b.bin')
check(is_blank(se), "'brick': after power cycle device is blank and usable")
check(se.pin_stuff(3, attempt(b'', change=CHANGE_WALLET_PIN, new=b'55-55')) == 0, "'brick': can set a new PIN afterwards")
features.ON_MAX_PIN_ATTEMPTS = 'wipe'

# "Last Chance" wrong-PIN rule: wipe on 2nd failure, brick on the next
se = setup('lc.bin')
add_slot(se, make_slot(0, TC_WIPE | TC_BRICK, 2, b'!p'))
se = reboot('lc.bin')
se.pin_stuff(2, attempt(b'00-00'))
check(se.secret_ct is not None, 'Last Chance: 1st wrong PIN does nothing')
check(stops(lambda: se.pin_stuff(2, attempt(b'00-00'))), 'Last Chance: 2nd wrong PIN stops')
se = reboot('lc.bin')
check(se.secret_ct is None and se.pin_tag is not None, 'Last Chance: seed wiped, PIN kept')
check(stops(lambda: se.pin_stuff(2, attempt(b'00-00'))), 'Last Chance: next wrong PIN bricks')
se = reboot('lc.bin')
check(is_blank(se), 'Last Chance: then blank device')

# "Brick Self" trick PIN
se = setup('bs.bin')
add_slot(se, make_slot(1, TC_BRICK, 0, b'77-77'))
se = reboot('bs.bin')
b = attempt(PIN); se.pin_stuff(2, b)
check(state(b)['flags'] & PA_SUCCESSFUL, 'Brick Self: real PIN unaffected')
se = reboot('bs.bin')
check(stops(lambda: se.pin_stuff(2, attempt(b'77-77'))), 'Brick Self: trick PIN stops device')
se = reboot('bs.bin')
check(is_blank(se), 'Brick Self: blank after power cycle')

# with brick disabled, a brick trick only wipes the seed
features.ALLOW_BRICK_OPTIONS = False
se = setup('bd.bin')
add_slot(se, make_slot(1, TC_BRICK, 0, b'77-77'))
se = reboot('bd.bin')
stops(lambda: se.pin_stuff(2, attempt(b'77-77')))
se = reboot('bd.bin')
check(se.secret_ct is None and se.pin_tag is not None, 'brick disabled: acts as wipe seed')
features.ALLOW_BRICK_OPTIONS = True

print('\n%d failure(s)' % len(FAILS))
sys.exit(1 if FAILS else 0)
