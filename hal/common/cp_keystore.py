# cp_keystore.py - Cardputer port: where the soft secure element keeps its
# record (encrypted seed, PIN check values, trick PINs, wrong-PIN counter).
#
# Two places, chosen in Advanced/Tools > Key Storage:
#
#   flash   the ESP32's internal flash (as before)
#   sd      a hidden folder on the microSD card:  <card>/MK5/.keystore/ on the
#           Mk5 firmware, <card>/.keystore/ on the Q. Internal flash then only
#           holds a pointer saying "it's on the card": nothing secret.
#
# The record is the same encrypted blob either way (see secel_soft.py), so
# the PIN protects it exactly as before. What changes: without the card, the
# Cardputer holds no secrets at all.
#
# The card is needed at power-on (to read the record) and whenever the record
# changes (PIN changes, wrong-PIN counter, new seed). SoftSE keeps the record
# in RAM after reading it, so once logged in the card can be taken out, e.g.
# to fetch a PSBT from the PC, and signing works without it.
#
# On the card the record is written to two files in turn (key0.bin, key1.bin)
# with a sequence number and SHA-256, like the two flash slots: a power cut
# mid-write leaves the previous copy. After a good write the older copy is
# deleted, so no stale copy of an old record (e.g. a wiped seed) stays behind.
#
# New wallets: with features.KEY_STORE_DEFAULT = 'sd', the first time a PIN is
# saved on a blank device the record goes to the card if one is inserted.
# A blank device that finds a key folder on the card uses it (e.g. after
# reinstalling the firmware).
import os, utime

PTR = b'CPKP'                   # internal-flash record that points to the card
MAGIC = b'CPS1'                 # slot header, same as the flash slots
_SLOTS = ('key0.bin', 'key1.bin')


def key_dir():
    import features
    sub = getattr(features, 'SD_SUBDIR', None)
    return (sub + '/.keystore') if sub else '.keystore'

def key_dir_label():
    return key_dir() + '/'

def _chose_flash(raw):
    # the owner picked internal flash for this record (Key Storage > 1)
    try:
        import ujson
        return raw[0:4] != PTR and ujson.loads(raw[4:]).get('ksc') == 'flash'
    except Exception:
        return False

def _is_blank(raw):
    # blank = no record, a pointer, or a record without a main PIN
    if not raw or raw[0:4] == PTR:
        return True
    try:
        import ujson
        return ujson.loads(raw[4:]).get('pin_tag') is None
    except Exception:
        return False


# ---- card access ----

class _Card:
    # use the card through the one shared mount (cp_sdsub), yield the key folder
    def __enter__(self):
        import cp_sdsub
        cp_sdsub.share_acquire()            # raises OSError if no card
        self.path = cp_sdsub.RAW + '/' + key_dir()
        return self

    def __exit__(self, *a):
        import cp_sdsub
        cp_sdsub.share_release()

    def makedirs(self):
        p = ''
        for part in self.path.split('/'):
            if not part:
                continue
            p += '/' + part
            try:
                os.mkdir(p)
            except OSError:
                pass


def _read_file(fn):
    import ngu
    try:
        with open(fn, 'rb') as f:
            blob = f.read()
    except OSError:
        return None, -1
    if len(blob) < 44 or blob[0:4] != MAGIC:
        return None, -1
    seq = int.from_bytes(blob[4:8], 'little')
    ln = int.from_bytes(blob[8:12], 'little')
    if len(blob) != 12 + ln + 32:
        return None, -1
    if bytes(ngu.hash.sha256s(blob[:12 + ln])) != blob[12 + ln:]:
        return None, -1
    return blob[12:12 + ln], seq

def _best(path):
    best, bseq, which = None, -1, -1
    for i, fn in enumerate(_SLOTS):
        d, s = _read_file(path + '/' + fn)
        if d is not None and s > bseq:
            best, bseq, which = d, s, i
    return best, bseq, which

def sd_load():
    # -> record bytes, or None (no card, no key folder, or damaged)
    try:
        with _Card() as c:
            return _best(c.path)[0]
    except OSError:
        return None

def sd_present():
    try:
        with _Card():
            return True
    except OSError:
        return False

def sd_save(data):
    # write the record to the card; raises OSError if it can't be done
    import ngu
    with _Card() as c:
        c.makedirs()
        _, seq, which = _best(c.path)
        seq += 1
        n = 1 - which if which >= 0 else 0
        hdr = MAGIC + seq.to_bytes(4, 'little') + len(data).to_bytes(4, 'little')
        blob = hdr + data + bytes(ngu.hash.sha256s(hdr + data))
        fn = c.path + '/' + _SLOTS[n]
        with open(fn, 'wb') as f:
            f.write(blob)
        d, s = _read_file(fn)               # read back before trusting it
        if d != data or s != seq:
            raise OSError(5)
        try:
            os.remove(c.path + '/' + _SLOTS[1 - n])
        except OSError:
            pass

def sd_delete():
    try:
        with _Card() as c:
            for fn in _SLOTS:
                try:
                    os.remove(c.path + '/' + fn)
                except OSError:
                    pass
            try:
                os.rmdir(c.path)
            except OSError:
                pass
    except OSError:
        pass


def _show(msg, msg_mk4):
    import ckcc
    ckcc._show(msg, msg_mk4)


class KeyStore:
    # the .load()/.save() object SoftSE uses; wraps the internal flash store

    def __init__(self, inner):
        self.inner = inner
        self.missing = False        # 'sd' chosen but the card isn't readable
        raw = inner.load()
        self.loc = 'sd' if (raw and raw[0:4] == PTR) else 'flash'
        self._flash_blank = _is_blank(raw)

    def load(self):
        if self.loc == 'flash':
            raw = self.inner.load()
            self._flash_blank = _is_blank(raw)
            if self._flash_blank:
                # blank device: is there a wallet on the card? (reinstall)
                d = sd_load()
                if d and not _is_blank(d):
                    self._point_to_sd()
                    return d
            return raw
        d = sd_load()
        self.missing = d is None
        return d

    def save(self, data):
        if self.loc == 'flash':
            import features
            if self._flash_blank and not _is_blank(data) and not _chose_flash(data) \
                    and getattr(features, 'KEY_STORE_DEFAULT', 'flash') == 'sd':
                # first PIN on a blank device: new wallets live on the card
                try:
                    sd_save(data)
                    self._point_to_sd()
                    return
                except OSError:
                    pass                    # no card: internal flash
            self.inner.save(data)
            self._flash_blank = _is_blank(data)
            return
        # on the card: wait for it if it's out (PIN changes etc.)
        while True:
            try:
                sd_save(data)
                self.missing = False
                return
            except OSError:
                self.missing = True
                _show("Insert the SD card\nwith your key\n(%s)\nto save the change." % key_dir_label(),
                      "Insert SD card\nwith your key\nto save change.")
                utime.sleep_ms(800)

    def _point_to_sd(self):
        self.inner.erase()
        self.inner.save(PTR + b'{"loc":"sd"}')
        self.loc = 'sd'
        self.missing = False
        self._flash_blank = True

    # ---- Key Storage menu ----

    def move_to_sd(self, data):
        sd_save(data)                       # raises if no card
        if sd_load() != data:
            raise OSError(5)
        self._point_to_sd()

    def move_to_flash(self, data):
        self.inner.erase()
        self.inner.save(data)
        if self.inner.load() != data:
            raise OSError(5)
        self.loc = 'flash'
        self.missing = False
        self._flash_blank = _is_blank(data)
        sd_delete()

    def start_blank_on_flash(self):
        # card lost: forget the pointer, start as a blank device (card untouched)
        self.inner.erase()
        self.loc = 'flash'
        self.missing = False
        self._flash_blank = True


def _se():
    import ckcc
    return ckcc._se()

def location():
    return _se().store.loc


async def boot_check():
    # Before COLDCARD asks for the PIN: if the key lives on the card, make
    # sure the card is there. (A new wallet goes to the card if one is in,
    # else to internal flash, without asking: see KeyStore.save.)
    from ux import ux_show_story, ux_confirm
    se = _se()
    ks = se.store
    while ks.loc == 'sd' and ks.missing:
        ch = await ux_show_story(
            "Your key (encrypted seed and PINs) is stored on the SD card, in "
            "%s, but it wasn't found.\n\nInsert that card and press OK.\n\n"
            "Lost it? Press X to start as a blank device. You'd then restore "
            "your wallet from your backup or seed words." % key_dir_label(),
            title='Key Card')
        if ch == 'x':
            if await ux_confirm("Start as a blank device, with the key in internal flash? "
                                "Nothing on any SD card is deleted. If the key card is in "
                                "at a later power-on, before you set a new PIN, it's used again."):
                ks.start_blank_on_flash()
                se._load()
            continue
        se._load()


# EOF
