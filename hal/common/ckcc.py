# ckcc.py - Cardputer port: replacement for COLDCARD's C module "ckcc"
# (stm32/COLDCARD_MK4/modckcc.c) and the bootrom "callgate" behind it.
#
# Adapted from Coinkite's simulator (unix/variant/ckcc.py). Hardware specifics
# come from cp_board (device or desktop-test build).
#
import ustruct, utime
import cp_board
from uerrno import ENOENT, EPERM

ERANGE = const(34)

_SE = None

def _se():
    global _SE
    if _SE is None:
        from secel_soft import SoftSE
        from cp_keystore import KeyStore
        _SE = SoftSE(KeyStore(cp_board.se_store()))
    return _SE

# ---- randomness ----

def rng():
    # 30-bit random number
    b = bytearray(4)
    cp_board.rng_bytes(b)
    return ustruct.unpack('I', b)[0] >> 2

def rng_bytes(buf):
    cp_board.rng_bytes(buf)

# ---- the "callgate" into the (emulated) bootrom ----

_BL_VERSION = b'cardputer-1.0 time=0 git=cardputer'

def gate(method, buf_io, arg2):
    import version

    if method == 0:
        # bootrom version string
        buf_io[0:len(_BL_VERSION)] = _BL_VERSION
        return len(_BL_VERSION)

    if method == 1:
        # bootrom checksum: hash of our firmware build id
        import ngu, cp_buildinfo
        h = ngu.hash.sha256s(cp_buildinfo.BUILD_ID.encode() + ustruct.pack('<I', arg2))
        buf_io[0:32] = h
        return 0

    if method == 4:
        # "genuine" green/red light: no light on Cardputer, just track it
        se = _se()
        if arg2 == 1:
            se.genuine = False
        elif arg2 == 3:
            se.genuine = True
        return 1 if se.genuine else 0

    if method == 5:
        # are we a brick? never.
        return 0

    if method == 6:
        # has 608 (SE1)? emulated: yes
        return 0

    if method == 16:
        # PIN prefix -> anti-phishing words
        if len(buf_io) < 8:
            return ERANGE
        utime.sleep_ms(200)
        buf_io[0:4] = _se().pin_prefix_words(buf_io[0:arg2])
        return 0

    if method == 18:
        return _se().pin_stuff(arg2, buf_io)

    if method == 19:
        if arg2 == 0:
            # bag number (shown in some screens)
            v = b'CARDPUTER'
            buf_io[0:32] = v + bytes(32 - len(v))
        elif arg2 == 1:
            return 0
        elif arg2 == 2:
            # RDP level: 2 = production, not factory mode
            buf_io[0] = 2
        return 0

    if method == 20:
        # SE1 config: return the simulator's sample, so get_608_rev() works
        assert len(buf_io) == 128
        buf_io[:] = (b'\x01#\xbf\x0b\x00\x00`\x04CP,\xbf\xeeap\x00\xe1\x00a\x00\x00\x00\x8f-'
            b'\x8f\x80\x8fC\xaf\x80\x00C\x00C\x8fG\xc3C\xc3C\xc7G\x00G\x00\x00\x8fM\x8fC\x00'
            b'\x00\x00\x00\x1f\xff\x00\x1a\x00\x1a\xff\xff\xff\xff\x00\x00\x00\x00\x00\x00'
            b'\x00\x00\xf0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xea'
            b'\xff\x02\x15\x00\x00\x00\x00<\x00\\\x00\xbc\x01\xfc\x01\xbc\x01\x9c\x01\x9c'
            b'\x01\xfc\x01\xdc\x03\xdc\x03\xdc\x07\x9c\x01<\x00\xfc\x01\xdc\x01<\x00')
        return 0

    if method == 21:
        # firmware "high water" mark (anti-downgrade)
        se = _se()
        if arg2 == 0:
            buf_io[0:8] = se.highwater
        elif arg2 == 2:
            se.highwater = bytes(buf_io[0:8])
            se._save()
        return 0

    if method == 22:
        return _se().se2_callgate(buf_io, arg2)

    if method == 25:
        # mcu_key_usage: avail/consumed/total
        ustruct.pack_into('3I', buf_io, 0, 255, 1, 256)
        return 0

    if method == 26:
        # random bytes "from the secure elements" (SE1: 32, SE2: 8): chip
        # TRNG mixed with microphone / motion-sensor noise, see cp_entropy.py
        n = 32 if arg2 == 1 else 8 if arg2 == 2 else 0
        if not n:
            return ERANGE
        import cp_entropy
        tmp = cp_entropy.share(arg2, n)
        buf_io[0] = n
        buf_io[1:1+n] = tmp
        return 0

    if method == 27:
        v = b'SoftSE1\nSoftSE2\0'
        buf_io[0:len(v)] = v
        return 0

    return ENOENT

def oneway(method, arg2):
    # bootrom calls that never return
    import features
    se = _se()

    if method == 2:
        # enter DFU = ESP32 ROM download mode, for flashing new firmware
        _show("Firmware update mode.\n\nUse esptool to flash.",
              "Firmware update\nmode. Use esptool\nto flash.")
        cp_board.bootloader()

    elif method == 3:
        # callgate.show_logout(style), as the Mk4 bootloader handles it:
        #   0  show "Logged out" and stop
        #   1  stop, leaving the current screen visible (errors, HSM)
        #   2  restart: Test Login Now, Lock Down Seed, CCC setup
        #   3  Q: power down (no power control here: as 0)
        # The restart is a full chip reset, so RAM is wiped either way.
        if arg2 == 2:
            cp_board.reset()
        if arg2 != 1:
            _show("Logged out.\n\nTurn the power switch off,\nor press the reset button.",
                  "Logged out.\n\nPower off to\nrestart.")
        cp_board.halt()

    elif method == 23:
        # fast wipe of seed, then reboot (0xBeef) or show screen and stop (0xdead)
        se.wipe_seed()
        if arg2 == 0xBeef:
            cp_board.reset()
        _show("Seed Wiped.")
        cp_board.halt()

    elif method == 24:
        # fast brick: see SoftSE.brick() (erases everything, never harms hardware)
        se.brick()

    print("oneway(%d, %d)" % (method, arg2))
    cp_board.halt()

def _show(msg, msg_mk4=None):
    # Final screen before halting, drawn like the bootloader would.
    # Q display code positions text in character rows; the Mk4/Mk5 OLED code
    # positions it in pixels (128x64, FontSmall is 14px tall, ~18 chars
    # wide), so the Mk5 gets its own shorter wording, centred vertically.
    try:
        from glob import dis
        if hasattr(dis, 'next_buf'):
            # Q: character rows
            dis.clear()
            y = 2
            for ln in msg.split('\n'):
                dis.text(None, y, ln)
                y += 1
        else:
            # Mk4/Mk5: pixel rows
            from zevvpeep import FontSmall
            lines = (msg_mk4 or msg).split('\n')
            h = FontSmall.height
            dis.clear()
            y = max(0, (64 - len(lines) * h) // 2)
            for ln in lines:
                dis.text(None, y, ln, font=FontSmall)
                y += h
        dis.show()
    except Exception as exc:
        print(msg, exc)

# ---- misc ----

def is_simulator():
    return False

def is_debug_build():
    return cp_board.IS_DEV

def get_sim_root_dirs():
    raise RuntimeError('not a simulator')

def presume_green():
    pass

def breakpoint():
    pass

def watchpoint():
    pass

_repl = False
def repl_enabled(en=None):
    global _repl
    if en is not None:
        _repl = bool(en)
    return _repl

def usb_active():
    return False

def get_cpu_id():
    # COLDCARD checks for STM32L4S5; we report the same so shared code is happy
    return 0x470

def PSRAM():
    # Mk4/Q: the Virtual Disk's block device (half the PSRAM chip there).
    # Here: a 4MB disk image on the SD card, see cp_vdisk.py
    import cp_vdisk
    return cp_vdisk.DISK

# EOF
