# cp_sdsub.py - Cardputer port: give the firmware one folder of the microSD
# card as "its" SD card (features.SD_SUBDIR, e.g. 'MK5' for the Mk5 build).
#
# COLDCARD mounts pyb.SDCard() at /sd. In folder mode, pyb.SDCard() returns a
# SubdirVfs: an object with a mount() method, which MicroPython treats as a
# filesystem. It mounts the real FAT card at a private mount point and serves
# <card>/<SD_SUBDIR> as the root of /sd. So everything COLDCARD saves (backups,
# signed PSBTs, exports) lands in that folder, file pickers only list that
# folder, and nothing outside it is touched. The folder is created on first use.
#
# "Format SD Card" in folder mode empties the folder only (see wipe_subdir).
#
# The Q build (whole card) goes through the same object with subdir '', so on
# both builds there is only ever ONE mount of the real card (at RAW), shared
# by COLDCARD's /sd, the key store (cp_keystore.py) and the virtual disk
# image (cp_vdisk.py), with a use count: the card is unmounted and powered
# off when the last user lets go. (Two FAT drivers on one card would corrupt
# it.)
#
import os

RAW = '/_cpsd'          # private mount point of the whole card
# folders COLDCARD can't see or touch: the key store and the virtual disk image
HIDDEN = ('.keystore', '.vdisk')

# ---- the one shared mount of the real card ----

_users = 0
_bd = None

def share_acquire():
    # mount the card at RAW (first user), count users; raises OSError if no card
    global _users, _bd
    if _users == 0:
        import pyb
        bd = pyb._SDBlock()
        try:
            os.mount(bd, RAW)
        except Exception:
            bd.power(0)
            raise OSError(19)           # ENODEV: no card / unreadable
        _bd = bd
    _users += 1

def share_release():
    global _users, _bd
    if _users <= 0:
        return
    _users -= 1
    if _users == 0:
        try:
            os.umount(RAW)
        except OSError:
            pass
        if _bd is not None:
            _bd.power(0)
        _bd = None

def share_users():
    return _users

def _hidden(rel):
    top = rel.split('/', 1)[0]
    return top in HIDDEN


def _isdir(path):
    try:
        return (os.stat(path)[0] & 0x4000) != 0
    except OSError:
        return False


class SubdirVfs:
    def __init__(self, blockdev, subdir):
        self.bd = blockdev
        self.sub = subdir.strip('/')
        self.root = (RAW + '/' + self.sub) if self.sub else RAW
        self.cwd = '/'
        self.mounted = False

    # ---- block-device passthrough (COLDCARD calls these on pyb.SDCard()) ----
    def power(self, st=0):
        # COLDCARD powers the slot off after each use; leave it on while
        # someone else (virtual disk, key store) is using the card
        if st or _users:
            return False
        return self.bd.power(0)

    # raw block access: only the Q's "Format SD Card" uses it, and never
    # while anything has the card mounted
    def _free(self):
        if _users:
            raise OSError(16)           # EBUSY
    def readblocks(self, *a):
        return self.bd.readblocks(*a)
    def writeblocks(self, *a):
        self._free()
        return self.bd.writeblocks(*a)
    def ioctl(self, op, arg):
        return self.bd.ioctl(op, arg)

    def present(self):
        return self.bd.present()

    def info(self):
        return self.bd.info()

    # ---- VFS protocol ----
    def _p(self, path):
        if not path.startswith('/'):
            path = self.cwd.rstrip('/') + '/' + path
        rel = path.strip('/')
        if rel and _hidden(rel):
            raise OSError(2)            # ENOENT: COLDCARD can't see or touch it
        return self.root + ('/' + rel if rel else '')

    def mount(self, readonly, mkfs):
        # mkfs: Mk5 formatting is wipe_subdir(); the Q formats the whole card,
        # allowed only when nothing else has it mounted
        if mkfs:
            if self.sub:
                raise OSError(1)        # EPERM: never reformat the shared card
            self._free()
            os.VfsFat.mkfs(self.bd)
        share_acquire()
        self.mounted = True
        if self.sub and not _isdir(self.root):
            if readonly:
                return
            os.mkdir(self.root)

    def umount(self):
        if self.mounted:
            self.mounted = False
            share_release()

    def open(self, path, mode):
        return open(self._p(path), mode)

    def ilistdir(self, path):
        top = self._p(path) == self.root
        for ent in os.ilistdir(self._p(path)):
            if top and ent[0] in HIDDEN:
                continue
            yield ent

    def stat(self, path):
        return os.stat(self._p(path))

    def statvfs(self, path):
        return os.statvfs(RAW)

    def mkdir(self, path):
        return os.mkdir(self._p(path))

    def rmdir(self, path):
        return os.rmdir(self._p(path))

    def remove(self, path):
        return os.remove(self._p(path))

    def rename(self, old, new):
        return os.rename(self._p(old), self._p(new))

    def chdir(self, path):
        if not _isdir(self._p(path)):
            raise OSError(2)
        self.cwd = '/' + path.strip('/') if path.startswith('/') else \
            (self.cwd.rstrip('/') + '/' + path.strip('/'))

    def getcwd(self):
        return self.cwd


def _rm_tree(path):
    for ent in list(os.ilistdir(path)):
        name = ent[0]
        full = path + '/' + name
        if ent[1] & 0x4000:
            _rm_tree(full)
            os.rmdir(full)
        else:
            os.remove(full)


def wipe_subdir():
    # "Format SD Card" in folder mode: delete everything inside the folder,
    # leave the rest of the card (Launcher, other apps' files) alone
    import pyb, features
    from glob import dis
    sd = pyb.SDCard()
    dis.fullscreen('Erasing %s/...' % features.SD_SUBDIR)
    try:
        sd.power(1)
        os.mount(sd, '/sd')
        try:
            # everything in the folder except the key folder: wiping the
            # key is COLDCARD's job (Destroy Seed, brick), not formatting's
            top = RAW + '/' + features.SD_SUBDIR
            for ent in list(os.ilistdir(top)):
                if ent[0] in HIDDEN:
                    continue
                full = top + '/' + ent[0]
                if ent[1] & 0x4000:
                    _rm_tree(full)
                    os.rmdir(full)
                else:
                    os.remove(full)
        finally:
            os.umount('/sd')
    finally:
        sd.power(0)

# EOF
