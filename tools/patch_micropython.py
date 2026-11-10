#!/usr/bin/env python3
# patch_micropython.py - small compatibility edits to MicroPython v1.29.0 for
# COLDCARD's code (which was written for Coinkite's older MicroPython).
# Run by setup.sh and both build scripts; idempotent; fails loudly if a
# target text isn't found (e.g. after a MicroPython upgrade).
#
#   tools/patch_micropython.py <micropython dir>
import os, sys

MPY = sys.argv[1]

PATCHES = [
    # COLDCARD calls bytearray('text') in places (e.g. the Mk4/Mk5 text entry
    # screen, used for passphrases and nicknames). Older MicroPython built the
    # bytearray from the string's bytes; 1.29 raises "string argument without
    # an encoding". Restore the old behaviour (UTF-8 bytes of the string).
    ('py/objarray.c',
     '''        if (mp_obj_is_str(args[0]) && n_args == 1) {
            #if MICROPY_ERROR_REPORTING <= MICROPY_ERROR_REPORTING_TERSE
            // Match bytes_make_new.
            mp_raise_TypeError(MP_ERROR_TEXT("wrong number of arguments"));
            #else
            mp_raise_TypeError(MP_ERROR_TEXT("string argument without an encoding"));
            #endif
        }''',
     '''        // Cardputer port: COLDCARD relies on bytearray(str) working
        // (older MicroPython); fall through and copy the string's bytes.'''),
]

bad = 0
for fn, old, new in PATCHES:
    p = os.path.join(MPY, fn)
    s = open(p).read()
    if new in s:
        continue                    # already applied
    if s.count(old) != 1:
        print('patch_micropython: %s: expected text not found (MicroPython changed?)' % fn)
        bad += 1
        continue
    open(p, 'w').write(s.replace(old, new))
    print('patch_micropython: patched', fn)
sys.exit(1 if bad else 0)
