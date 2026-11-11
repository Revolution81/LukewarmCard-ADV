#!/usr/bin/env python3
#
# assemble.py - build the Python tree for the Cardputer firmware.
#
#   1. copy COLDCARD's shared/*.py (unmodified source of truth)
#   2. apply the small, exact-match PATCHES below; if upstream code changed so a
#      patch no longer matches exactly once, stop with an error (never guess)
#   3. append APPENDS (method overrides) to a few modules
#   4. drop simulator/debug-only modules
#   5. overlay hal/common, hal/<variant>, then hal/<target> (replacements + new files)
#   6. write cp_buildinfo.py and a frozen-module manifest
#
# Usage: assemble.py <coldcard-repo> <out-dir> <target: device|host> [--dev]
#                    [--layout own|launcher]
#
# Layouts (device only): own = the port's partition table (ccse, ccscratch,
# vfs); launcher = everything in one 'vfs' partition, for M5Launcher.
#
# Builds the COLDCARD Mk4/Mk5 code path (numeric keypad + 128x64 OLED UI),
# the Keypad edition. The Q-only modules listed in COLDCARD's manifest_q1.py
# are left out, exactly as Coinkite's Mk4/Mk5 build does.
#
import os, sys, shutil, subprocess, datetime, glob

PORT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EXCLUDE = {
    'h.py',                 # debug helpers; would enable REPL
    'dev_helper.py',
    'usb_test_commands.py',
    'gpu_binary.py',        # firmware image for the Q's graphics chip
    'sim_display.py',
    'manifest.py', 'manifest_mk4.py', 'manifest_q1.py',
}

# (file, old, new): old must occur exactly once
PATCHES = [
    # Self-test, microSD: the Cardputer's slot has no card-detect switch, so
    # skip the remove/insert phases and the "remove card" wait at the end;
    # the real write/read/delete check still runs.
    ('selftest.py', '        # test presence switch\n        for ph in range(7):\n',
                    '        # test presence switch (Cardputer: no switch, phases skipped)\n        for ph in range(0):\n'),
    ('selftest.py', '        # force removal, so cards don\'t get stuck in finished units\n        await wait_til_state(slot_num, False)\n',
                    '        # (Cardputer: no card-detect switch, so no "remove card" wait)\n'),
    # memory: every use of the cached secret started another 10 s expiry
    # timer chain (each lives until the cache sits unused for a minute), so
    # signing many transactions back to back piled up timers. Keep one.
    ('stash.py', '        SensitiveValues._cache_used = utime.ticks_ms()\n\n        call_later_ms(CACHE_CHECK_RATE, self.cache_check)\n',
                 '        SensitiveValues._cache_used = utime.ticks_ms()\n\n        SensitiveValues._cp_arm()\n'),
    ('stash.py', '        SensitiveValues._cache_secret = bytearray(main_secret)\n        call_later_ms(CACHE_CHECK_RATE, cls.cache_check)\n',
                 '        SensitiveValues._cache_secret = bytearray(main_secret)\n        cls._cp_arm()\n'),
    ('stash.py', '            # called after already cleared\n            return\n',
                 '            # called after already cleared\n            cls._cp_timer = False\n            return\n'),
    ('stash.py', '            cls.clear_cache()\n        else:\n',
                 '            cls.clear_cache()\n            cls._cp_timer = False\n        else:\n'),
    # memory: libngu's word lookup copied the rest of the 2048-word list on
    # every call (8K at once); walk it in place instead. Same result.
    ('bip39.py', '    for i, w in enumerate(wordlist_en[start_index:], start=start_index):\n',
                 '    for i in range(start_index, len(wordlist_en)):\n        w = wordlist_en[i]\n'),
    # View TRNG Words: say where this device's random bytes come from
    ('seed.py', '256-bit device seed (STM32 TRNG + SE1 + SE2) ',
                '256-bit device seed (ESP32 TRNG + microphone + gyro) '),
    # ---- trick PINs: hide options disabled in features.py
    ('trick_pins.py', 'from menu import MenuSystem, MenuItem\n',
     'from menu import MenuSystem as _CC_MenuSystem, MenuItem\n'
     'class MenuSystem(_CC_MenuSystem):\n'
     '    # Cardputer: drop trick-PIN choices disabled in features.py\n'
     '    def __init__(self, items, *a, **kw):\n'
     '        import features\n'
     '        items = [i for i in items if features.trick_menu_allowed(getattr(i, "flags", 0) or 0)]\n'
     '        super().__init__(items, *a, **kw)\n'),
    ('trick_pins.py', "the Coldcard will always brick after 13 failed PIN attempts.''')",
                      "''' + __import__('features').max_attempts_text())"),

    # ---- login warning: say what this port really does at the limit
    ('login.py', "You have %d attempts left before this Coldcard BRICKS \\\nITSELF FOREVER.",
                 "You have %d attempts left before %s"),
    ('login.py', "''' % (attempts_left, value, OK, X), title=\"WARNING\")",
                 "''' % (attempts_left, __import__('features').limit_action_text(), value, OK, X), title=\"WARNING\")"),

    # ---- Nuke Device: describe what the emulated brick really does
    ('actions.py', '" all related settings, and makes ewaste from this device."',
                   '" all related settings, PIN and trick PINs. The Cardputer comes back blank after a power cycle."'),
    ('actions.py', '"Brick device?\\n\\nBy design, there is no way to reset or recover"\n'
                   '                            " the secure element, and its contents become forever inaccessible."',
                   '"Brick device?\\n\\nEverything stored on this Cardputer will be erased."\n'
                   '                            " Only your seed words can restore the wallet."'),

    # ---- Danger Zone > Nuke Device: hidden unless brick is allowed
    ('flow.py', 'MenuItem("Nuke Device", f=nuke_device),',
                'MenuItem("Nuke Device", f=nuke_device, predicate=__import__("features").ALLOW_BRICK_OPTIONS),'),

    # ---- Advanced/Tools > Entropy Sources (Cardputer screen, see actions.py append)
    ('flow.py', '                            f=drv_entro_start),\n    MenuItem("View Identity", f=view_ident),\n',
                '                            f=drv_entro_start),\n    MenuItem("View Identity", f=view_ident),\n'
                '    MenuItem("Entropy Sources", f=cp_entropy_sources),\n'
                '    MenuItem("Key Storage", f=cp_key_storage),\n'),
    # key on the SD card: make sure the card is in before COLDCARD asks for the PIN
    ('main.py', '            await pa.enforce_brick()\n',
                '            import cp_keystore\n            await cp_keystore.boot_check()\n'
                '            await pa.enforce_brick()\n'),
]

# Mk4/Mk5 variant only. COLDCARD's display.py opens the OLED's STM32 SPI bus;
# here the LCD bus is owned by cp_board (see hal/mk4/ssd1306.py).
MK4_PATCHES = [
    ('display.py', '        spi = machine.SPI(1)\n',
                   '        spi = None      # Cardputer: LCD bus is set up by cp_board\n'),
    # SD card is the MK5 folder only (features.SD_SUBDIR, hal/common/cp_sdsub.py)
    ('actions.py', 'Erases and reformats MicroSD card. This is not a secure erase but more of a quick format.',
                   'Erases everything in the MK5 folder on the MicroSD card, except your key if it is stored there (Key Storage). Other files on the card are not touched.'),
]

# Mk4/Mk5 variant only: appended to modules after patching
MK4_APPENDS = {
    'files.py': '''
# Cardputer port: "Format SD Card" empties the firmware's folder on the card
# (features.SD_SUBDIR) instead of reformatting the whole shared card.
_cp_orig_wipe_microsd_card = wipe_microsd_card
def wipe_microsd_card():
    import features
    if getattr(features, 'SD_SUBDIR', None):
        import cp_sdsub
        return cp_sdsub.wipe_subdir()
    return _cp_orig_wipe_microsd_card()
''',
}

APPENDS = {
    'usb.py': '''
# ---- Cardputer: COLDCARD's USB link runs as on a real COLDCARD (HID only,
# see hal/device/cp_usb.py). Keyboard emulation (typing passwords into the
# computer as a USB keyboard) is not ported.
def enable_keyboard_emulation():
    pass
''',

    'actions.py': '''
# ---- Cardputer port ----

async def microsd_upgrade(menu, label, item):
    # Upgrade Firmware > From MicroSD: COLDCARD .dfu files are machine code for
    # the real COLDCARD's STM32 chip, which this ESP32 can't run (the soft
    # secure element would refuse them anyway). Explain instead of failing.
    import features
    where = ('the %s folder on the MicroSD card' % features.SD_SUBDIR) \\
                if getattr(features, 'SD_SUBDIR', None) else 'the MicroSD card'
    await ux_show_story(\'\'\'\\
Firmware files from Coinkite (.dfu) can't be installed on this Cardputer. \\
They contain code for the real COLDCARD's chip. Nothing has been changed.

To move to a new COLDCARD release, build a new Cardputer image from it \\
(see BUILDING.md in the port's build kit) and install that with M5Launcher.

Before installing, make a backup to %s \\
(Advanced/Tools > Backup), then restore it afterwards.\'\'\' % where,
        title='Upgrades')

async def cp_key_storage(*a):
    # Advanced/Tools > Key Storage: internal flash or SD card (cp_keystore.py)
    import cp_keystore, ckcc
    from glob import dis
    se = ckcc._se()
    ks = se.store
    where = cp_keystore.key_dir_label()
    here = 'the SD card (%s)' % where if ks.loc == 'sd' else 'internal flash'
    ch = await ux_show_story(\'\'\'\\
Your key (encrypted seed, PINs and wrong-PIN count) is stored in %s.

1 = Internal flash: always there. Anyone holding the Cardputer can copy it.

2 = SD card (default), in %s. Without the card, the Cardputer holds nothing \\
secret. The card must be in to power on and log in, and to change PINs. \\
Once logged in you can take it out, e.g. to fetch a PSBT, and still sign.

Either way the PIN protects it the same. Press 1 or 2, or X to keep it.\'\'\' % (here, where),
        title='Key Storage', escape='12')
    if ch == '1' and ks.loc != 'flash':
        if not await ux_confirm('Move the key to internal flash? It will be deleted from the SD card.'):
            return
        dis.fullscreen('Moving...')
        try:
            se.ks_choice = 'flash'
            ks.move_to_flash(se.record())
        except Exception as exc:
            se.ks_choice = None
            await ux_show_story('Not moved: %s. Your key is still on the SD card.' % exc, title='Failed')
            return
        await ux_show_story('Your key is now in internal flash, and was deleted from the SD card.', title='Moved')
    elif ch == '2' and ks.loc != 'sd':
        if not cp_keystore.sd_present():
            await ux_show_story('No SD card found. Insert one and try again.', title='No Card')
            return
        if cp_keystore.sd_load():
            if not await ux_confirm('This card already holds a key, maybe from another wallet. Replace it with this one?'):
                return
        if not await ux_confirm('Move the key to the SD card? It will be erased from internal flash, '
                                'and this card will be needed to power on. Keep your backup words safe '
                                'in case the card fails.'):
            return
        dis.fullscreen('Moving...')
        try:
            se.ks_choice = None
            ks.move_to_sd(se.record())
        except Exception as exc:
            se.ks_choice = 'flash'
            await ux_show_story('Not moved: %s. Your key is still in internal flash.' % exc, title='Failed')
            return
        await ux_show_story('Your key is now on the SD card (%s) and was erased from internal flash.' % where,
                            title='Moved')

# no NFC chip on the Cardputer: features that would switch NFC on say so
# instead of starting a driver for hardware that isn't there
_cp_orig_change_nfc_enable = change_nfc_enable
async def change_nfc_enable(enable):
    import version
    if enable and not version.has_nfc:
        return
    return await _cp_orig_change_nfc_enable(enable)

_cp_orig_feature_requires_nfc = feature_requires_nfc
async def feature_requires_nfc():
    import version
    if not version.has_nfc:
        await ux_show_story("This feature needs NFC, which this device doesn't have.",
                            title='No NFC')
        return False
    return await _cp_orig_feature_requires_nfc()

async def cp_entropy_sources(*a):
    # Advanced/Tools > Entropy Sources: what goes into new seeds on this device
    import cp_entropy
    from glob import dis
    dis.fullscreen('Testing...')
    try:
        rows = cp_entropy.test_all()
        err = None
    except Exception as exc:
        rows = cp_entropy.status()
        err = str(exc)
    import version
    msg = 'LukewarmCard ADV, Keypad edition\\n\\n'
    for label, ok, detail in rows:
        mark = 'used' if ok else ('NOT USED' if ok is False else 'n/a')
        msg += '%s: %s\\n  %s\\n\\n' % (label, mark, detail)
    if err:
        msg += 'Chip RNG error: %s\\nNew seeds are blocked until this is fixed.\\n\\n' % err
    msg += ('A real COLDCARD mixes random bytes from its two secure elements into '
            'every new seed. Here the microphone and motion sensor noise take '
            'their places, always mixed with the ESP32 chip RNG. A sensor that '
            'fails is left out; the chip RNG alone is still used.')
    await ux_show_story(msg, title='Entropy')
''',

    'selftest.py': '''
# ---- Cardputer port: self-test for this hardware ----
# Left out (no such parts here): PSRAM, the secure-element genuine light
# (green/red), the SD activity light, NFC, the factory battery test. Added: microphone and motion sensor.
# The USB light test uses the StampS3A's RGB LED, lit white.

async def test_usb_light():
    import cp_board
    cp_board.led_hold(True)
    try:
        cp_board.led(48, 48, 48)
        label_test("USB light is on?")
        await wait_ok()
    finally:
        cp_board.led(0, 0, 0)
        cp_board.led_hold(False)

def _cp_sensor(key, label):
    import cp_board
    src = cp_board.test_sensors().get(key)
    if src is None:
        raise RuntimeError(label + " not found")
    try:
        src.open()
    except Exception as exc:
        raise RuntimeError("%s: %s" % (label, exc))
    return src

def _cp_bar(frac):
    n = max(0, min(8, int(frac * 8)))
    return '#' * n + '.' * (8 - n)

async def _cp_wait_for(src, title, prompt, read, threshold, timeout_ms=20000):
    # show a live level bar until read() reaches threshold
    import utime
    ux_clear_keys()
    deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
    shown = -1
    best = 0
    while 1:
        v = read()
        best = max(best, v)
        if v >= threshold:
            label_test(title, 'OK')
            await sleep_ms(700)
            return
        if utime.ticks_diff(deadline, utime.ticks_ms()) < 0:
            raise RuntimeError("%s: nothing detected" % title)
        b = _cp_bar(v / threshold)
        if b != shown:
            label_test(title + ': ' + prompt, b)
            shown = b
        await sleep_ms(0)
        if ux_poll_key():
            raise RuntimeError("%s aborted" % title)

async def test_mic():
    # pass when the microphone hears a sound clearly louder than the room
    src = _cp_sensor('mic', 'Microphone')
    try:
        label_test('Mic Test', 'Quiet...')
        base = 0
        for i in range(8):
            base = max(base, src.loudness())
        thresh = min(max(base * 3, 1500), 20000)
        await _cp_wait_for(src, 'Mic Test', 'clap', src.loudness, thresh)
    finally:
        src.close()

async def test_motion():
    # pass when the gyro sees the Cardputer turned (over 40 degrees/second)
    src = _cp_sensor('imu', 'Motion sensor')
    try:
        await _cp_wait_for(src, 'Gyro Test', 'move', src.turn_rate, 40.0)
    finally:
        src.close()

async def start_selftest():
    try:
        # (no battery test: it needs factory reference cells)
        await test_oled()
        await test_numpad()

        await test_usb_light()
        await test_mic()
        await test_motion()
        await test_microsd()

        settings.set('tested', True)
        import cp_board
        m = cp_board.mem_report()
        await ux_show_story("Selftest complete.\\n\\nMemory: %d KB free now, lowest %d KB "
                            "since power-on (%d KB in use)." % (m['now'], m['low'], m['py_used']),
                            'PASS')

    except (RuntimeError, AssertionError) as e:
        e = str(e) or problem_file_line(e)
        await ux_show_story("Test failed:" + chr(10) + str(e), 'FAIL')
''',

    'stash.py': '''
# ---- Cardputer port: one secret-cache expiry timer at a time (see PATCHES) ----
SensitiveValues._cp_timer = False
def _cp_arm(cls=SensitiveValues):
    if not cls._cp_timer:
        cls._cp_timer = True
        call_later_ms(CACHE_CHECK_RATE, cls.cache_check)
SensitiveValues._cp_arm = staticmethod(_cp_arm)
''',

    'vdisk.py': '''
# ---- Cardputer port: Virtual Disk on the SD card (cp_vdisk.py) ----
_cp_orig_vd_init = VirtDisk.__init__
def _cp_vd_init(self):
    # make / open the disk image first (needs the SD card; if it isn't in,
    # cp_vdisk retries when it shows up)
    import cp_vdisk
    if cp_vdisk.DISK.prepare(cp_vdisk._progress):
        cp_vdisk.DISK.write_ident()
    _cp_orig_vd_init(self)
VirtDisk.__init__ = _cp_vd_init

def _cp_vd_sample(self):
    # COLDCARD's sample() assumes the disk always mounts (PSRAM on a Mk4).
    # Here it's a file on the SD card: no card -> empty list, not a crash
    try:
        os.mount(VBLKDEV, '/vdisk', readonly=True)
    except Exception:
        return []
    try:
        return list(sorted(('/vdisk/'+fn, sz) for (fn,ty,_,sz) in os.ilistdir('/vdisk')
                                                    if ty == 0x8000))
    except Exception:
        return []
    finally:
        os.umount('/vdisk')
VirtDisk.sample = _cp_vd_sample

def _cp_vd_new_firmware(self, filename, sz):
    # a .dfu dropped on the drive: explain (see actions.microsd_upgrade)
    uasyncio.create_task(psram_upgrade(filename, sz))
VirtDisk.new_firmware = _cp_vd_new_firmware

async def psram_upgrade(filename, size):
    from actions import microsd_upgrade
    await microsd_upgrade(None, None, None)
''',

    'mk4.py': '''
# ---- Cardputer port ----
def make_psram_fs():
    # Mk4: README + version into the freshly-wiped RAM disk. Here the disk is
    # an image on the SD card (cp_vdisk.py), only touched while Virtual Disk
    # is on (or being formatted)
    import cp_vdisk
    cp_vdisk.DISK.write_ident()
''',
}


def die(msg):
    sys.exit('assemble.py: ' + msg)


def q1_only_modules(cc):
    # files COLDCARD freezes only into the Q build (shared/manifest_q1.py)
    import re
    txt = open(os.path.join(cc, 'shared', 'manifest_q1.py')).read()
    mods = set(re.findall(r"'([A-Za-z0-9_]+\.py)'", txt))
    if 'lcd_display.py' not in mods or 'ux_q1.py' not in mods:
        die('could not read Q-only module list from manifest_q1.py')
    return mods


def release_version(cc, history, fallback):
    # the version Coinkite's own build stamps in (stm32/*Makefile VERSION_STRING);
    # older trees: newest entry in the release history
    import re
    mk = ['MK-Makefile', 'MK4-Makefile']
    for m in mk:
        try:
            v = re.search(r'^VERSION_STRING\s*=\s*(\S+)', open(os.path.join(cc, 'stm32', m)).read(), re.M)
            if v:
                return v.group(1)
        except OSError:
            pass
    try:
        for ln in open(os.path.join(cc, 'releases', history)):
            if ln.startswith('## '):
                return ln.split()[1]
    except OSError:
        pass
    return fallback


def apply_patches(out, patches):
    for fn, old, new in patches:
        p = os.path.join(out, fn)
        s = open(p).read()
        n = s.count(old)
        if n != 1:
            die('patch for %s matched %d times (upstream changed?):\n  %r' % (fn, n, old[:120]))
        open(p, 'w').write(s.replace(old, new))


def main():
    cc, out, target = sys.argv[1], sys.argv[2], sys.argv[3]
    is_dev = '--dev' in sys.argv
    variant = 'mk4'
    if '--variant' in sys.argv and sys.argv[sys.argv.index('--variant') + 1] != 'mk4':
        die('this kit builds the Keypad edition only (--variant mk4)')
    layout = 'own'
    if '--layout' in sys.argv:
        layout = sys.argv[sys.argv.index('--layout') + 1]
    if layout not in ('own', 'launcher'):
        die('unknown layout %r (own or launcher)' % layout)
    shared = os.path.join(cc, 'shared')

    exclude = set(EXCLUDE) | q1_only_modules(cc)

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)

    # 1. copy
    for fn in sorted(os.listdir(shared)):
        if not fn.endswith('.py') or fn in exclude or fn.startswith('sim_'):
            continue
        src = os.path.realpath(os.path.join(shared, fn))
        if not os.path.exists(src):
            die('missing %s (git submodule update --init?)' % fn)
        shutil.copy(src, os.path.join(out, fn))

    # python parts of libngu (normally frozen by its own manifest)
    shutil.copy(os.path.join(cc, 'external', 'libngu', 'ngu', 'bip39.py'), out)

    # 1b. hashlib: COLDCARD (MicroPython 1.13) can call sha256().digest() more
    # than once; mainline 1.29 raises "hash is final" (seen with the USB
    # upload checksum). MicroPython 1.29 always maps "uhashlib" to the built-in,
    # so point COLDCARD's imports at libngu's sha256, which keeps 1.13
    # behaviour (cmodules/libngu-src/ngu/hash.c).
    n_hash = 0
    for fn in os.listdir(out):
        if not fn.endswith('.py'):
            continue
        p = os.path.join(out, fn)
        src = open(p).read()
        if 'uhashlib' not in src:
            continue
        new = src.replace('from uhashlib import sha256\n',
                          'from cp_hashlib import sha256    # Cardputer: repeatable digest()\n')
        if 'uhashlib' in new:
            die('%s: unexpected uhashlib use (upstream changed?)' % fn)
        open(p, 'w').write(new)
        n_hash += 1
    if n_hash < 10:
        die('expected COLDCARD uhashlib imports, found %d' % n_hash)

    # 2. patches (those for modules this variant leaves out are skipped)
    apply_patches(out, PATCHES + MK4_PATCHES)

    # 3. appends
    for fn, code in list(APPENDS.items()) + list(MK4_APPENDS.items()):
        with open(os.path.join(out, fn), 'a') as fp:
            fp.write('\n' + code)

    # 5. overlays
    for sub in ('common', variant, target):
        for src in sorted(glob.glob(os.path.join(PORT, 'hal', sub, '*.py'))):
            shutil.copy(src, os.path.join(out, os.path.basename(src)))

    # 6. build info
    try:
        rev = subprocess.check_output(['git', '-C', cc, 'log', '-1', '--format=%h'], text=True).strip()
    except Exception:
        rev = 'unknown'
    cc_ver = release_version(cc, 'History-Mk4.md', 'Mk4?')
    now = datetime.datetime.now(datetime.timezone.utc)
    with open(os.path.join(out, 'cp_buildinfo.py'), 'w') as fp:
        fp.write('# generated by assemble.py\n')
        fp.write('VERSION = %r\n' % ('%s-cp' % cc_ver))
        fp.write('DATE = %r\n' % now.strftime('%Y-%m-%d'))
        fp.write('TIMESTAMP = %r\n' % now.strftime('%y%m%d%H%M%S'))
        fp.write('BUILD_ID = %r\n' % ('cc:%s %s %s' % (rev, variant, now.isoformat())))
        fp.write('IS_DEV = %r\n' % is_dev)
        fp.write('TARGET = %r\n' % target)
        fp.write('VARIANT = %r\n' % variant)
        fp.write('LAYOUT = %r\n' % layout)

    mods = sorted(f for f in os.listdir(out) if f.endswith('.py'))
    print('assembled %d modules into %s (target=%s, variant=%s, layout=%s, coldcard %s @ %s)'
          % (len(mods), out, target, variant, layout, cc_ver, rev))


if __name__ == '__main__':
    main()
