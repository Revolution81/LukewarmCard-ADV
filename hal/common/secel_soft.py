# secel_soft.py - Cardputer port: software stand-in for COLDCARD's two secure
# elements (SE1 = ATECC608, SE2 = DS28C36) and the bootrom logic around them.
#
# Based on Coinkite's simulator (unix/variant/sim_secel.py, sim_se2.py) but
# PERSISTENT and with secrets encrypted at rest:
#
#   * One PBKDF2-HMAC-SHA512 per PIN attempt derives a key K from (PIN, salt).
#     From K we get a check tag (is this the PIN?) and an encryption key.
#   * A random 32-byte master key (DMK) encrypts the seed and the "long secret".
#     DMK is stored wrapped (AES-256-CTR + tag) under the main PIN, and under
#     any Delta Mode trick PIN (which must log into the real seed).
#   * Trick PIN slots are stored encrypted under their own PIN. Only the
#     "N wrong PINs" policy slots are stored in the clear (no PIN to key them).
#
# LIMITATION, stated plainly: there is no secure element. Anyone who has the
# device can read the flash and brute-force the PIN offline; PBKDF2 only slows
# that down. Treat the PIN as protection against casual access only, and use
# a BIP-39 passphrase (never stored) for real protection of funds.
#
import ustruct, utime, ngu, version
from ubinascii import hexlify as b2a_hex
from uerrno import ENOENT, EPERM

ERANGE = const(34)

EPIN_RANGE_ERR       = const(-103)
EPIN_BAD_REQUEST     = const(-104)
EPIN_AUTH_FAIL       = const(-112)
EPIN_OLD_AUTH_FAIL   = const(-113)

KDF_ROUNDS = const(2048)
STORE_MAGIC = b'CPSE'
STORE_VERSION = const(1)

TC_HIDDEN_MASK = const(0xf800)

SECRET_LEN = const(72)
LS_LEN = const(416)


def _kdf(pin, salt):
    # pin: bytes. One PBKDF2 per attempt; everything else derived with HMAC.
    k = ngu.hash.pbkdf2_sha512(pin, salt + b'cardputer-pin', KDF_ROUNDS)
    return bytes(k[0:32])

def _sub(k, label):
    return bytes(ngu.hmac.hmac_sha256(k, label))

def _xor_ctr(key, nonce, data):
    # AES-256-CTR, 16-byte nonce
    return ngu.aes.CTR(key, nonce).cipher(bytes(data))

def _wrap(k, label, plaintext):
    # authenticated encryption-ish: CTR + HMAC tag (encrypt-then-mac)
    nonce = bytes(ngu.random.bytes(16))
    ek = _sub(k, label + b'-enc')
    ct = _xor_ctr(ek, nonce, plaintext)
    tag = _sub(_sub(k, label + b'-mac'), nonce + ct)[0:16]
    return nonce + tag + ct

def _unwrap(k, label, blob):
    nonce, tag, ct = blob[0:16], blob[16:32], blob[32:]
    if _sub(_sub(k, label + b'-mac'), nonce + ct)[0:16] != tag:
        return None
    return _xor_ctr(_sub(k, label + b'-enc'), nonce, ct)


class SoftSE:
    def __init__(self, store):
        # store: object with .load() -> bytes|None and .save(bytes)
        self.store = store
        self.wallet = None          # trick wallet chosen at last login (SE2 behaviour)
        self.dmk = None             # master key, held in RAM only after good login
        self.genuine = True
        self._load()

    # ---- persistence ----

    def _blank_state(self):
        self.salt = bytes(ngu.random.bytes(32))
        self.pin_tag = None         # None => no PIN set (blank device)
        self.dmk_wrap = None
        self.secret_ct = None
        self.ls_ct = None
        self.num_fails = 0
        self.attempts_left = self._max_attempts()
        self.slots = {}             # slot_num -> dict(kind, tag, blob, dmk)
        self.highwater = bytes(8)
        self.ks_choice = None       # 'flash' = owner chose internal flash (cp_keystore)

    def _max_attempts(self):
        import features
        return features.MAX_PIN_ATTEMPTS

    def _load(self):
        raw = self.store.load()
        self._blank_state()
        if not raw and getattr(self.store, 'missing', False):
            # key card not inserted (cp_keystore): blank until it is; don't
            # write anything
            return
        if not raw or raw[0:4] != STORE_MAGIC:
            # first boot (or wiped): random salt, nothing else
            self._save()
            return
        import ujson
        from ubinascii import a2b_base64 as a2b
        d = ujson.loads(raw[4:])
        def b(v): return a2b(v) if v else None
        self.salt = b(d['salt'])
        self.pin_tag = b(d.get('pin_tag'))
        self.dmk_wrap = b(d.get('dmk'))
        self.secret_ct = b(d.get('sec'))
        self.ls_ct = b(d.get('ls'))
        self.num_fails = d.get('fails', 0)
        self.attempts_left = d.get('left', self._max_attempts())
        self.highwater = b(d.get('hw')) or bytes(8)
        self.ks_choice = d.get('ksc')
        for sn, s in d.get('slots', {}).items():
            self.slots[int(sn)] = dict(kind=s['k'], tag=b(s.get('t')),
                                       blob=b(s['b']), dmk=b(s.get('d')))

    def _save(self):
        self.store.save(self.record())

    def record(self):
        # the whole state as stored (secrets encrypted), see cp_keystore
        import ujson
        from ubinascii import b2a_base64
        def e(v): return b2a_base64(v).strip().decode() if v else None
        d = dict(v=STORE_VERSION, salt=e(self.salt), pin_tag=e(self.pin_tag),
                 dmk=e(self.dmk_wrap), sec=e(self.secret_ct), ls=e(self.ls_ct),
                 fails=self.num_fails, left=self.attempts_left, hw=e(self.highwater), ksc=self.ks_choice,
                 slots={str(sn): dict(k=s['kind'], t=e(s['tag']), b=e(s['blob']), d=e(s['dmk']))
                            for sn, s in self.slots.items()})
        return STORE_MAGIC + ujson.dumps(d).encode()

    # ---- key helpers ----

    def _pin_k(self, pin):
        return _kdf(pin, self.salt)

    def _tag(self, k):
        return _sub(k, b'tag')[0:16]

    def is_blank(self):
        return self.pin_tag is None

    def _main_pin_matches(self, k):
        if self.pin_tag is None:
            # blank device: only the empty PIN "matches"
            return False
        return self._tag(k) == self.pin_tag

    def _get_dmk(self, k):
        if not self.dmk_wrap:
            return None
        return _unwrap(k, b'dmk', self.dmk_wrap)

    def _read_secret(self):
        if not self.secret_ct or not self.dmk:
            return bytes(SECRET_LEN)
        return _unwrap(self.dmk, b'secret', self.secret_ct) or bytes(SECRET_LEN)

    def _read_ls(self):
        if not self.ls_ct or not self.dmk:
            return bytes(LS_LEN)
        return _unwrap(self.dmk, b'ls', self.ls_ct) or bytes(LS_LEN)

    def _write_secret(self, secret):
        assert self.dmk
        self.secret_ct = _wrap(self.dmk, b'secret', secret)

    def _write_ls(self, ls):
        assert self.dmk
        self.ls_ct = _wrap(self.dmk, b'ls', ls)

    # ---- destructive actions ----

    def wipe_seed(self):
        # erase seed + long secret; PIN and trick PINs remain
        self.secret_ct = None
        self.ls_ct = None
        self.wallet = None
        self._save()

    def factory_reset(self):
        # emulated "brick": everything gone, back to blank device. Reflashable.
        self._blank_state()
        self.dmk = None
        self.wallet = None
        self._save()

    def has_seed(self):
        return self.secret_ct is not None

    def brick(self):
        # COLDCARD's fast_brick(). A real COLDCARD destroys its secure elements.
        # Here: erase PIN, seed, trick PINs and settings, then stop. After a
        # power cycle the Cardputer is a blank device. If brick is disabled in
        # features.py, only the seed is wiped.
        import features
        if features.ALLOW_BRICK_OPTIONS:
            self.factory_reset()
            import cp_board
            cp_board.wipe_settings()
            _stop("Bricked.", "Everything erased. Power off/on to start again as a blank device.")
        else:
            self.wipe_seed()
            _stop("Seed Wiped.", "(Brick is disabled in this build.)")

    def show_wiped_and_stop(self):
        _stop("Seed Wiped.", None)

    # ---- failed attempts policy ----

    def _note_failure(self):
        import features
        self.num_fails += 1
        policy = features.ON_MAX_PIN_ATTEMPTS
        if policy == 'none':
            self.attempts_left = max(1, self.attempts_left - 1)
            self._save()
        else:
            self.attempts_left -= 1
            self._save()
            if self.attempts_left <= 0:
                print("SoftSE: PIN attempt limit reached: %s" % policy)
                if policy == 'brick':
                    self.brick()        # does not return on device
                else:
                    self.wipe_seed()
                    self.num_fails = 0
                    self.attempts_left = self._max_attempts()
                    self._save()
        # then any "N wrong PINs" trick (bootrom: se2_handle_bad_pin)
        self._handle_bad_pin()

    def _handle_bad_pin(self):
        from trick_pins import TC_WIPE, TC_BRICK, TC_REBOOT
        for sn, s in self.slots.items():
            if s['kind'] != 'w':
                continue
            slot = s['blob']
            flags, arg = ustruct.unpack_from('<HH', slot, 4)
            if self.num_fails < arg:
                continue
            if flags & TC_WIPE:
                if flags & TC_BRICK:
                    # "Last Chance": first time wipe and stop; if no seed
                    # remains, fall through to brick
                    if self.has_seed():
                        self.wipe_seed()
                        self.show_wiped_and_stop()
                else:
                    self.wipe_seed()
                    if flags == TC_WIPE:
                        self.show_wiped_and_stop()
            if flags & TC_BRICK:
                self.brick()
            if flags & TC_REBOOT:
                _reboot_now(None)
            # TC_FAKE_OUT ("Silent Wipe"): nothing more, it's a wrong PIN anyway
            return

    # ---- trick PINs (SE2) ----

    def _find_trick(self, k):
        # returns (slot_num, slot_bytes, dmk_wrap) if k matches a trick PIN
        tag = self._tag(k)
        for sn, s in self.slots.items():
            if s['kind'] == 'p' and s['tag'] == tag:
                slot = _unwrap(k, b'slot', s['blob'])
                if slot:
                    return (sn, slot, s['dmk'])
        return None

    def try_trick_login(self, pin, k):
        # mirrors bootrom se2_test_trick_pin(safety_mode=False)
        from trick_pins import TC_WIPE, TC_BRICK, TC_REBOOT, TC_FAKE_OUT
        from trick_pins import TC_WORD_WALLET, TC_XPRV_WALLET, TC_DELTA_MODE
        import uctypes
        from trick_pins import TRICK_SLOT_LAYOUT

        found = self._find_trick(k)
        if not found:
            self.wallet = None
            return None

        sn, slot, dmk_wrap = found
        b = bytearray(slot)
        xs = uctypes.struct(uctypes.addressof(b), TRICK_SLOT_LAYOUT)
        tc_flags, tc_arg = xs.tc_flags, xs.tc_arg

        if tc_flags & TC_WIPE:
            self.wipe_seed()
            if tc_flags == TC_WIPE:
                self.show_wiped_and_stop()

        if tc_flags & TC_BRICK:
            self.brick()

        if tc_flags & TC_REBOOT:
            _reboot_now(None)

        if tc_flags & TC_FAKE_OUT:
            return None

        self.wallet = None
        if tc_flags & TC_WORD_WALLET:
            if bytes(xs.xdata[16:32]) == bytes(16):
                self.wallet = bytes([0x80]) + bytes(xs.xdata[0:16]) + bytes(72-17)
            else:
                self.wallet = bytes([0x82]) + bytes(xs.xdata[0:32]) + bytes(72-33)

        if tc_flags & TC_XPRV_WALLET:
            self.wallet = bytes([0x01]) + bytes(xs.xdata[0:64]) + bytes(72-65)

        if tc_flags & TC_DELTA_MODE:
            # unlock the real seed with this trick PIN
            self.dmk = _unwrap(k, b'dmk', dmk_wrap) if dmk_wrap else None
            self.wallet = 'delta'
            tc_arg = 0

        if not self.wallet:
            self.wallet = bytes(72)

        tc_flags &= ~TC_HIDDEN_MASK
        return (tc_flags, tc_arg)

    def se2_callgate(self, buf_io, arg2):
        # ckcc.gate(22, ...) -- trick PIN slot management, see sim_se2.py
        from trick_pins import TRICK_SLOT_LAYOUT, NUM_TRICKS, TC_DELTA_MODE
        from pincodes import PIN_ATTEMPT_SIZE
        import uctypes

        orig = bytearray(buf_io[PIN_ATTEMPT_SIZE:])
        slot = uctypes.struct(uctypes.addressof(orig), TRICK_SLOT_LAYOUT)
        pc = bytes(slot.pin[0:slot.pin_len])

        if arg2 == 0:           # clear all
            self.slots.clear()
            self._save()
            return 0

        if arg2 == 1:           # get by pin
            blank = (1 << NUM_TRICKS) - 1
            for sn in self.slots:
                blank &= ~(1 << sn)
            if pc[:2] == b'!p':
                for sn, s in self.slots.items():
                    if s['kind'] == 'w' and s['blob'][8+64:8+64+len(pc)] == pc:
                        buf_io[PIN_ATTEMPT_SIZE:] = s['blob']
                        return 0
            else:
                k = self._pin_k(pc)
                tag = self._tag(k)
                for sn, s in self.slots.items():
                    if s['kind'] == 'p' and s['tag'] == tag:
                        got = _unwrap(k, b'slot', s['blob'])
                        if got:
                            buf_io[PIN_ATTEMPT_SIZE:] = got
                            return 0
            slot.blank_slots = blank
            slot.slot_num = -1
            buf_io[PIN_ATTEMPT_SIZE:] = orig
            return ENOENT

        if arg2 == 2:           # update / delete slot(s)
            if slot.blank_slots:
                for sn in range(NUM_TRICKS):
                    if (1 << sn) & slot.blank_slots:
                        self.slots.pop(sn, None)
            else:
                sn = slot.slot_num
                if pc[:2] == b'!p':
                    self.slots[sn] = dict(kind='w', tag=None, blob=bytes(orig), dmk=None)
                else:
                    k = self._pin_k(pc)
                    dmk = None
                    if (slot.tc_flags & TC_DELTA_MODE) and self.dmk:
                        dmk = _wrap(k, b'dmk', self.dmk)
                    self.slots[sn] = dict(kind='p', tag=self._tag(k),
                                          blob=_wrap(k, b'slot', bytes(orig)), dmk=dmk)
            self._save()
            return 0

        return ENOENT

    # ---- SE1 / bootrom PIN API (ckcc.gate 18) ----

    def pin_stuff(self, submethod, buf_io):
        from pincodes import (PIN_ATTEMPT_SIZE, PIN_ATTEMPT_FMT_V1, PA_ZERO_SECRET,
                            PIN_ATTEMPT_SIZE_V1, PA_SUCCESSFUL, PA_IS_BLANK,
                            CHANGE_WALLET_PIN, CHANGE_SECRET, CHANGE_DURESS_SECRET,
                            CHANGE_BRICKME_PIN, CHANGE_SECONDARY_WALLET_PIN,
                            CHANGE_LS_OFFSET, AE_LONG_SECRET_LEN)

        if len(buf_io) < PIN_ATTEMPT_SIZE_V1:
            return ERANGE

        rv = 0
        (magic, is_secondary, pin, pin_len, delay_achieved, delay_required,
            _nf, _al, state_flags, private_state, hmac, change_flags,
            old_pin, old_pin_len, new_pin, new_pin_len,
            secret) = ustruct.unpack_from(PIN_ATTEMPT_FMT_V1, buf_io)

        pin = bytes(pin[0:pin_len])
        old_pin = bytes(old_pin[0:old_pin_len])
        new_pin = bytes(new_pin[0:new_pin_len])

        if submethod == 0:
            # setup: report blank state
            state_flags = (PA_SUCCESSFUL | PA_IS_BLANK) if self.is_blank() else 0

        elif submethod == 1:
            delay_achieved += 1

        elif submethod == 2:
            # login
            k = self._pin_k(pin)
            got = self.try_trick_login(pin, k)
            if got is not None:
                delay_required, delay_achieved = got
                state_flags = PA_SUCCESSFUL
                if isinstance(self.wallet, bytes) and self.wallet == bytes(72):
                    state_flags |= PA_ZERO_SECRET
            elif self.is_blank() or self._main_pin_matches(k):
                if not self.is_blank():
                    self.dmk = self._get_dmk(k)
                state_flags = PA_SUCCESSFUL
                delay_required, delay_achieved = 0, 0
                self.num_fails = 0
                self.attempts_left = self._max_attempts()
                self._save()
                if self._read_secret() == bytes(SECRET_LEN):
                    state_flags |= PA_ZERO_SECRET
            else:
                self._note_failure()
                rv = EPIN_AUTH_FAIL

        elif submethod == 3:
            # change PIN and/or secret
            cf = change_flags
            if cf == 0:
                return EPIN_RANGE_ERR
            if cf & (CHANGE_BRICKME_PIN | CHANGE_DURESS_SECRET | CHANGE_SECONDARY_WALLET_PIN):
                return EPIN_BAD_REQUEST

            # must prove knowledge of current PIN (or device is blank)
            if not self.is_blank():
                ko = self._pin_k(old_pin if (cf & CHANGE_WALLET_PIN) else pin)
                if not self._main_pin_matches(ko):
                    return EPIN_OLD_AUTH_FAIL
                if not self.dmk:
                    self.dmk = self._get_dmk(ko)

            if not self.dmk:
                self.dmk = bytes(ngu.random.bytes(32))

            if cf & CHANGE_WALLET_PIN:
                kn = self._pin_k(new_pin)
                self.pin_tag = self._tag(kn)
                self.dmk_wrap = _wrap(kn, b'dmk', self.dmk)

            if cf & CHANGE_SECRET:
                if (cf & CHANGE_LS_OFFSET):
                    # long-secret block write (32 bytes at a time)
                    blk = (cf >> 8) & 0xf
                    if blk > 13:
                        return EPIN_RANGE_ERR
                    ls = bytearray(self._read_ls())
                    ls[blk*32:blk*32+32] = secret[0:32]
                    self._write_ls(bytes(ls))
                else:
                    self._write_secret(bytes(secret))
                    # update the zero-secret flag to be correct, as the Mk4
                    # bootloader does (stm32/mk4-bootloader/pins.c). Without
                    # this, code that runs right after a new secret is stored
                    # (backup restore -> trick PIN restore) sees "no secret".
                    if bytes(secret)[0:SECRET_LEN] == bytes(SECRET_LEN):
                        state_flags |= PA_ZERO_SECRET
                    else:
                        state_flags &= ~PA_ZERO_SECRET
            self._save()

        elif submethod == 4:
            # fetch secret
            delta = isinstance(self.wallet, str)        # 'delta'
            if self.wallet and not delta:
                secret = self.wallet
            elif delta and self.dmk:
                secret = self._read_secret()
            else:
                k = self._pin_k(pin)
                if not self._main_pin_matches(k):
                    return EPIN_AUTH_FAIL
                self.dmk = self._get_dmk(k)
                secret = self._read_secret()

        elif submethod == 5:
            self.genuine = True

        elif submethod == 6:
            # long secret block read/write (mk3 style API)
            cf = change_flags
            blk = (cf >> 8) & 0xf
            if blk > 13:
                return EPIN_RANGE_ERR
            if cf & CHANGE_SECRET:
                ls = bytearray(self._read_ls())
                ls[blk*32:blk*32+32] = secret[0:32]
                self._write_ls(bytes(ls))
                self._save()
            else:
                secret = self._read_ls()[blk*32:blk*32+32] + bytes(40)

        elif submethod == 7:
            # firmware upgrade via bootrom: not applicable, use esptool
            return ENOENT

        elif submethod == 8:
            # mk4 long-secret fetch
            if len(buf_io) != PIN_ATTEMPT_SIZE + AE_LONG_SECRET_LEN:
                return ERANGE
            buf_io[-AE_LONG_SECRET_LEN:] = self._read_ls()

        else:
            return ENOENT

        ustruct.pack_into(PIN_ATTEMPT_FMT_V1, buf_io, 0, magic, is_secondary,
                pin, pin_len, delay_achieved, delay_required,
                self.num_fails, self.attempts_left, state_flags, private_state,
                bytes(32), change_flags, old_pin, old_pin_len, new_pin, new_pin_len,
                bytes(secret))
        return rv

    # ---- misc ----

    def pin_prefix_words(self, prefix):
        # anti-phishing words: stable per device, need the device salt
        return bytes(ngu.hmac.hmac_sha256(self.salt, b'prefix:' + bytes(prefix)))[0:4]


def _stop(title, line2):
    # show a message and stop until power is cycled (COLDCARD: LOCKUP_FOREVER)
    import cp_board
    try:
        from glob import dis
        dis.fullscreen(title, line2=line2)
    except Exception:
        print(title, line2 or '')
    cp_board.halt()

def _reboot_now(msg):
    import cp_board
    if msg:
        try:
            from glob import dis
            dis.fullscreen(msg)
            utime.sleep_ms(1500)
        except Exception:
            pass
    cp_board.reset()

# EOF
