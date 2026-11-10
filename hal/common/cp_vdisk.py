# cp_vdisk.py - Cardputer port: COLDCARD's Virtual Disk, stored on the SD card.
#
# On a real Mk4/Mk5/Q, Settings > Hardware On/Off > Virtual Disk makes the
# COLDCARD show up on the computer as a 4MB USB drive, kept in half of its
# 8MB PSRAM chip. Drop a PSBT on it, the COLDCARD offers to sign, the signed
# files appear on the drive. COLDCARD's vdisk.py does all of that through one
# block-device object, ckcc.PSRAM(). This is that object.
#
# The Cardputer has no PSRAM, so the 4MB lives in a disk-image file on the
# microSD card:
#
#     Mk5 build:  <card>/MK5/.vdisk/vdisk.img        Q build:  <card>/.vdisk/vdisk.img
#
# The computer sees only what's inside that image (a small FAT disk of its
# own), never the rest of the card or the key folder. COLDCARD's own file
# lists can't see the .vdisk folder either (cp_sdsub.HIDDEN), and "Format SD
# Card" leaves it alone; "Format RAM Disk" re-formats just the image.
# Unlike the Mk5 (RAM), the contents stay when the power is off.
#
# The image is made (zero-filled, then formatted) the first time Virtual Disk
# is switched on with a card in. It stays open, through the shared card mount
# (cp_sdsub.share_acquire), while Virtual Disk is on.
#
# The USB side (mass-storage interface) is hal/device/cp_usbmsc.py; it calls
# host_ready / host_read / host_write here.
import os, utime

BLOCK = 512
BLOCKS = 8192                   # 4MB, same as the Mk4/Mk5
QUIET_MS = 750                  # host idle this long -> COLDCARD looks (Mk4: 750 ms)

README = '''
LukewarmCard ADV Virtual Disk (runs COLDCARD firmware; unofficial)

1) copy your PSBT file here.
2) select from Coldcard menu & approve transaction.
3) signed transaction file(s) will be saved here.

'''.replace('\n', '\r\n')


def _paths():
    import cp_sdsub, features
    sub = getattr(features, 'SD_SUBDIR', None)
    d = cp_sdsub.RAW + ('/' + sub if sub else '') + '/.vdisk'
    return d, d + '/vdisk.img'

def image_label():
    import features
    sub = getattr(features, 'SD_SUBDIR', None)
    return (sub + '/' if sub else '') + '.vdisk/vdisk.img'


class VDisk:
    def __init__(self):
        self.f = None               # open image file (holds the shared card mount)
        self.cb = None              # COLDCARD's "host finished writing" callback
        self.inserted = False       # host may see the medium
        self.t_host = utime.ticks_ms()
        self.dirty = False
        self.attention = False      # tell the host the medium changed
        self.task = None

    # ---- image file ----

    def _open(self):
        if self.f is not None:
            return
        import cp_sdsub
        cp_sdsub.share_acquire()            # OSError if no card
        try:
            f = open(_paths()[1], 'r+b')
            f.seek(0, 2)
            if f.tell() != BLOCKS * BLOCK:
                f.close()
                raise OSError(2)
            self.f = f
        except Exception:
            cp_sdsub.share_release()
            raise OSError(2)

    def close(self):
        if self.f is None:
            return
        import cp_sdsub
        try:
            self.f.close()
        except OSError:
            pass
        self.f = None
        cp_sdsub.share_release()

    def _create(self, show=None):
        # zero-filled first, so nothing left on the card from before (old
        # deleted files) can show up inside the image
        import cp_sdsub
        d, img = _paths()
        cp_sdsub.share_acquire()
        try:
            p = ''
            for part in d.split('/'):
                if part:
                    p += '/' + part
                    try:
                        os.mkdir(p)
                    except OSError:
                        pass
            chunk = bytes(4096)             # small: RAM is tight
            n = BLOCKS * BLOCK // len(chunk)
            with open(img, 'wb') as f:
                for i in range(n):
                    f.write(chunk)
                    if show:
                        show(i / n)
        finally:
            cp_sdsub.share_release()
        self._open()
        os.VfsFat.mkfs(self)
        self.write_ident()

    def prepare(self, show=None):
        # open the image, making it first if needed. -> True when usable
        try:
            self._open()
            return True
        except OSError:
            pass
        try:
            self._create(show)
            return True
        except Exception as exc:
            print('vdisk: %r' % exc)
            self.close()
            return False

    def write_ident(self):
        # README + ident/version.txt, like COLDCARD writes into its RAM disk
        if self.f is None:
            return
        try:
            import version
            os.mount(self, '/_vdid')
            try:
                try:
                    os.mkdir('/_vdid/ident')
                except OSError:
                    pass
                with open('/_vdid/README.txt', 'wt') as f:
                    f.write(README)
                date, ver, *_ = version.get_mpy_version()
                with open('/_vdid/ident/version.txt', 'wt') as f:
                    f.write('\r\n'.join([ver, date, '']))
            finally:
                os.umount('/_vdid')
            self.f.flush()
        except Exception as exc:
            print('vdisk ident: %r' % exc)

    # ---- block device (COLDCARD mounts this at /vdisk, /psram) ----

    def readblocks(self, n, buf, off=0):
        self._open()
        self.f.seek(n * BLOCK + off)
        self.f.readinto(buf)

    def writeblocks(self, n, buf, off=0):
        self._open()
        self.f.seek(n * BLOCK + (off or 0))
        self.f.write(buf)

    def ioctl(self, op, arg):
        if op == 4:                 # block count
            return BLOCKS
        if op == 5:                 # block size
            return BLOCK
        if op == 3 and self.f is not None:      # sync
            self.f.flush()
        return 0

    # ---- what COLDCARD's vdisk.py calls (ckcc.PSRAM() on the Mk4) ----

    def callback(self, cb):
        # set while Virtual Disk is on
        self.cb = cb
        if cb and self.task is None:
            import uasyncio
            self.task = uasyncio.create_task(self._poll())
        if not cb:
            self.close()

    def set_inserted(self, v):
        v = bool(v)
        if v and not self.inserted:
            self.attention = True
        self.inserted = v
        if self.f is not None:
            self.f.flush()

    def get_time(self):
        return self.t_host

    def wipe(self):
        # "Format RAM Disk": re-format the image (COLDCARD's make_psram_fs
        # then adds README etc)
        if not self.prepare(_progress):
            raise OSError(19)
        os.VfsFat.mkfs(self)
        self.f.flush()

    def copy_file(self, offset, name):
        # copy a file from the disk's root into the PSBT staging area
        from glob import PSRAM
        os.mount(self, '/_vdcp', readonly=True)
        try:
            pos = 0
            with open('/_vdcp/' + name, 'rb') as f:
                while True:
                    b = f.read(4096)
                    if not b:
                        break
                    PSRAM.write(offset + pos, b)
                    pos += len(b)
            return pos
        finally:
            os.umount('/_vdcp')

    # ---- the computer's side (cp_usbmsc.py) ----

    def host_ready(self):
        if not self.inserted:
            return False
        try:
            self._open()
            return True
        except OSError:
            return False

    def host_read(self, lba, buf):
        self.readblocks(lba, buf)

    def host_write(self, lba, buf):
        self.writeblocks(lba, buf)
        self.t_host = utime.ticks_ms()
        self.dirty = True

    def host_sync(self):
        if self.f is not None:
            self.f.flush()

    def take_attention(self):
        a = self.attention
        self.attention = False
        return a

    async def _poll(self):
        # tell COLDCARD when the computer has finished writing; make the
        # image if the card wasn't in when Virtual Disk was switched on
        import uasyncio
        tries = 0
        try:
            while self.cb:
                await uasyncio.sleep_ms(250)
                if self.f is None and self.inserted:
                    tries += 1
                    if tries % 8 == 0:          # every 2 s
                        if self.prepare(_progress):
                            self.attention = True
                    continue
                if self.dirty and utime.ticks_diff(utime.ticks_ms(), self.t_host) > QUIET_MS:
                    self.dirty = False
                    try:
                        self.f.flush()
                        self.cb(self)
                    except Exception as exc:
                        print('vdisk cb: %r' % exc)
        finally:
            self.task = None


def _progress(frac):
    try:
        from glob import dis
        if frac == 0:
            dis.fullscreen('Preparing Virtual Disk...')
        dis.progress_bar_show(frac)
    except Exception:
        pass


DISK = VDisk()

# EOF
