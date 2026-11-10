# test_vdisk.py - Virtual Disk on the SD card (hal/common/cp_vdisk.py) and the
# shared card mount (hal/common/cp_sdsub.py), on the desktop build's emulated
# card. Run with an empty work dir:
#   CP_WORK=<dir> build/host-mk4/cc-mpy -X heapsize=4m tests/test_vdisk.py
import os, sys, utime

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

import cp_board, cp_sdsub, cp_vdisk, features, pyb, glob
from cp_vdisk import VDisk, BLOCKS, BLOCK

class _Dis:
    def fullscreen(self, *a, **k): pass
    def progress_bar_show(self, *a): pass
glob.dis = _Dis()

W = cp_board.WORK
d = VDisk()

def card_out(out=True):
    if out:
        open(W + '/card-out', 'w').close()
    else:
        try:
            os.remove(W + '/card-out')
        except OSError:
            pass

print('== no card: not usable, nothing mounted')
card_out()
check('prepare() -> False', d.prepare() is False and cp_sdsub.share_users() == 0)
card_out(False)

print('== first use: image made on the card')
shown = []
check('prepare() -> True', d.prepare(lambda f: shown.append(f)) is True)
check('progress shown while zero-filling', len(shown) > 10)
label = cp_vdisk.image_label()
check('image at %s' % label, label == (features.SD_SUBDIR + '/' if features.SD_SUBDIR else '') + '.vdisk/vdisk.img')
img = cp_vdisk._paths()[1]
check('4MB image', os.stat(img)[6] == BLOCKS * BLOCK)
check('card stays mounted while the disk is open (1 user)', cp_sdsub.share_users() == 1)

print('== inside the image: a FAT disk of its own')
os.mount(d, '/vd')
names = os.listdir('/vd')
check('README.txt + ident/ like the Mk4 RAM disk', 'README.txt' in names and 'ident' in names)
check('version.txt', len(open('/vd/ident/version.txt').read()) > 5)
check('statvfs ~4MB', os.statvfs('/vd')[0] * os.statvfs('/vd')[2] > 3_500_000)
with open('/vd/test.psbt', 'wb') as f:
    f.write(b'psbt\xff' + bytes(200))
os.umount('/vd')

print('== COLDCARD using the card at the same time (one shared mount)')
sd = pyb.SDCard()
os.mount(sd, '/sd')
check('COLDCARD mount shares it (2 users)', cp_sdsub.share_users() == 2)
check('.vdisk folder hidden from COLDCARD', '.vdisk' not in os.listdir('/sd'))
try:
    open('/sd/.vdisk/vdisk.img', 'rb')
    hidden = False
except OSError:
    hidden = True
check('image can\'t be opened through COLDCARD\'s view', hidden)
with open('/sd/other.txt', 'w') as f:
    f.write('hello')
os.umount('/sd')
sd.power(0)                     # COLDCARD powers the slot off after use
check('after COLDCARD lets go: still mounted for the disk', cp_sdsub.share_users() == 1)
buf = bytearray(BLOCK)
d.readblocks(0, buf)
check('disk still readable after COLDCARD\'s power-off', buf[510:512] == b'\x55\xaa')

print('== the computer writes (cp_usbmsc -> host_write)')
called = []
d.callback(lambda v: called.append(utime.ticks_ms()))
d.set_inserted(True)
check('medium-changed notice armed', d.take_attention() is True and d.take_attention() is False)
blk = bytearray(BLOCK)
d.host_read(100, blk)
d.host_write(100, blk)
check('host write marks dirty', d.dirty)
import uasyncio
async def wait_for_cb():
    for _ in range(40):
        if called:
            return
        await uasyncio.sleep_ms(100)
uasyncio.run(wait_for_cb())
check('COLDCARD told after the host goes quiet (750 ms)', len(called) == 1 and not d.dirty)

print('== copy_file into the PSBT staging area')
import psram
glob.PSRAM = psram.PSRAMWrapper()
n = d.copy_file(0, 'test.psbt')
check('copied %d bytes' % n, n == 205 and glob.PSRAM.read_at(0, 5) == b'psbt\xff')

print('== Format RAM Disk')
d.wipe()
os.mount(d, '/vd')
check('empty after wipe', os.listdir('/vd') == [])
os.umount('/vd')
d.write_ident()
os.mount(d, '/vd')
check('README back (make_psram_fs)', 'README.txt' in os.listdir('/vd'))
os.umount('/vd')

print('== Format SD Card leaves the image alone')
if features.SD_SUBDIR:
    cp_sdsub.wipe_subdir()
    check('image still there', os.stat(img)[6] == BLOCKS * BLOCK)
else:
    sd = pyb.SDCard()
    try:
        sd.writeblocks(0, bytes(BLOCK))
        refused = False
    except OSError:
        refused = True
    check('Q: whole-card format refused while the disk is open', refused)

print('== Virtual Disk off')
d.callback(None)
check('card released (0 users)', cp_sdsub.share_users() == 0 and d.f is None)

print('== contents kept: open again later')
d2 = VDisk()
check('existing image reused, not re-made', d2.prepare(lambda f: shown.append('again')) is True
      and 'again' not in shown)
d2.close()

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
