# test_keystore.py - key storage on internal flash or the SD card
# (hal/common/cp_keystore.py), on the desktop build's emulated flash + card.
#
#   CP_WORK=<empty dir> build/host-mk4/cc-mpy -X heapsize=4m tests/test_keystore.py
#
# Checks: new wallets go to the card; flash then holds only a pointer; reboot
# reads the card; card missing -> nothing written, reported; save waits for
# the card; move flash <-> card both ways leaves no copy behind; reinstall
# finds the key on the card; COLDCARD can't see the key folder; Format SD
# Card keeps it; brick/wipe leave no stale copy.
import os, sys

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

import cp_board, cp_keystore, features, cp_sdsub, pyb
from cp_keystore import KeyStore, PTR
from secel_soft import STORE_MAGIC

W = cp_board.WORK
SE_FILE = W + '/se.bin'
KD = cp_keystore.key_dir()

def rec(pin, seed='c2VlZA=='):
    import ujson
    return STORE_MAGIC + ujson.dumps(dict(salt='c2FsdHNhbHQ=', pin_tag=pin, sec=seed if pin else None)).encode()

BLANK = rec(None)
WALLET = rec('cGlu')
WALLET2 = rec('cGluMg==', 'b3RoZXI=')

def flash_raw():
    try:
        return open(SE_FILE, 'rb').read()
    except OSError:
        return None

def card_files():
    with cp_keystore._Card() as c:
        try:
            return sorted(os.listdir(c.path))
        except OSError:
            return []

def card_out(out=True):
    if out:
        open(W + '/card-out', 'w').close()
    else:
        try:
            os.remove(W + '/card-out')
        except OSError:
            pass

print('== key folder:', KD)
check('Mk5 build: folder inside MK5', KD == (features.SD_SUBDIR + '/.keystore'
      if features.SD_SUBDIR else '.keystore'))

print('== new wallet, card inserted')
ks = KeyStore(cp_board.se_store())
ks.load()
ks.save(BLANK)                          # first boot: blank record (salt)
check('blank record stays in internal flash', ks.loc == 'flash' and flash_raw() == BLANK)
ks.save(WALLET)                         # first PIN set
check('first PIN -> key moves to the card', ks.loc == 'sd')
check('internal flash now only a pointer', flash_raw()[0:4] == PTR and b'sec' not in flash_raw())
check('one copy on the card', card_files() == ['key0.bin'])
check('card copy reads back', cp_keystore.sd_load() == WALLET)

print('== more saves (PIN attempts, changes)')
ks.save(WALLET2)
check('saved to the card, older copy deleted', card_files() == ['key1.bin']
      and cp_keystore.sd_load() == WALLET2)
ks.save(WALLET)
check('alternates files, still one copy', card_files() == ['key0.bin'])

print('== power off / on')
ks = KeyStore(cp_board.se_store())
check('pointer -> reads the card', ks.loc == 'sd' and ks.load() == WALLET and not ks.missing)

print('== power on without the card')
card_out()
ks = KeyStore(cp_board.se_store())
check('nothing to read, reported missing', ks.load() is None and ks.missing)
from secel_soft import SoftSE
se = SoftSE(ks)
check('soft SE: blank while missing, writes nothing',
      se.pin_tag is None and flash_raw()[0:4] == PTR)
card_out(False)
se._load()
check('card back in: wallet loaded', not ks.missing and se.pin_tag is not None)

print('== save while the card is out: waits for it')
shown = []
def fake_show(msg, msg_mk4):
    shown.append(msg)
    if len(shown) == 2:
        card_out(False)                 # user puts the card back
cp_keystore._show = fake_show
card_out()
ks.save(WALLET2)
check('asked for the card, then saved', len(shown) == 2 and cp_keystore.sd_load() == WALLET2)

print('== move to internal flash')
ks.move_to_flash(WALLET2)
check('in flash', ks.loc == 'flash' and flash_raw() == WALLET2)
check('deleted from the card', card_files() == [])
ks = KeyStore(cp_board.se_store())
check('reboot: reads flash', ks.loc == 'flash' and ks.load() == WALLET2)
ks.save(WALLET)
check('existing wallet: further saves stay in flash', ks.loc == 'flash' and flash_raw() == WALLET)

print('== move to the card')
ks.move_to_sd(WALLET)
check('on the card, flash is a pointer only', ks.loc == 'sd'
      and flash_raw()[0:4] == PTR and cp_keystore.sd_load() == WALLET)

print('== reinstall: blank internal flash, same card')
os.remove(SE_FILE)
ks = KeyStore(cp_board.se_store())
d = ks.load()
check('finds the wallet on the card', d == WALLET and ks.loc == 'sd'
      and flash_raw()[0:4] == PTR)

print('== card lost: start blank')
ks.start_blank_on_flash()
check('pointer gone, blank device', ks.loc == 'flash' and flash_raw() is None)
check('card key untouched', cp_keystore.sd_load() == WALLET)

print('== COLDCARD\'s view of the card (SubdirVfs)')
sd = pyb.SDCard()
os.mount(sd, '/sd')
try:
    if features.SD_SUBDIR:
        # Mk5: COLDCARD sees MK5/ as its card; the key folder is invisible
        names = os.listdir('/sd')
        check('key folder not listed', '.keystore' not in names)
        try:
            open('/sd/.keystore/key0.bin', 'rb')
            hidden = False
        except OSError:
            hidden = True
        check('key folder can\'t be opened', hidden)
    # (Q uses the whole card: the folder is there, COLDCARD's file lists skip folders)
    with open('/sd/test.psbt', 'wb') as f:
        f.write(b'psbt')
finally:
    os.umount('/sd')
    sd.power(0)
if features.SD_SUBDIR:
    import glob
    class _Dis:
        def fullscreen(self, *a, **k): pass
    glob.dis = glob.dis or _Dis()
    cp_sdsub.wipe_subdir()
    check('Format SD Card: other files gone, key kept',
          cp_keystore.sd_load() == WALLET and card_files() == ['key0.bin'])

print('== wipe: no stale copy')
ks = KeyStore(cp_board.se_store())
ks.load()
check('blank device adopted the card again', ks.loc == 'sd')
ks.save(BLANK)                          # e.g. brick: blank record
with cp_keystore._Card() as c:
    blobs = b''.join(open(c.path + '/' + fn, 'rb').read() for fn in os.listdir(c.path))
check('only the blank record on the card (old seed gone)', b'c2VlZA==' not in blobs)

print('== owner chose internal flash')
cp_board.se_store().erase()
cp_keystore.sd_delete()
ks = KeyStore(cp_board.se_store())
ks.load()
import ujson
CHOSE = STORE_MAGIC + ujson.dumps(dict(salt='c2FsdHNhbHQ=', pin_tag='cGlu', sec='c2VlZA==',
                                       ksc='flash')).encode()
ks.save(BLANK)
ks.save(CHOSE)
check('first PIN with "flash" chosen: stays in flash, card in or not',
      ks.loc == 'flash' and flash_raw() == CHOSE and card_files() == [])

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
