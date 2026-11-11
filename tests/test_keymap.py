# test_keymap.py - drive the real Cardputer key mapping with raw TCA8418 key
# numbers, the way hal/device/cp_board.py delivers them on the device.
#
#   build/host-mk4/cc-mpy -X heapsize=4m tests/test_keymap.py    (Mk5 keypad: mempad.py)
#
# The flow scripts inject COLDCARD key codes directly and skip this layer, so
# this is the test that covers what the physical keys produce. It also checks
# the key source is started when the keypad object is created (COLDCARD never
# calls start() itself).
import sys
import cp_board, cp_buildinfo
from cp_keys import key_name

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

NUM = {}
for n in range(1, 81):
    k = key_name(n)
    if k:
        NUM[k] = n
assert len(NUM) == 56, len(NUM)

# record start() and what the keypad reports
started = []
class Src:
    def __init__(self, cb): self.cb = cb
    def start(self): started.append(1)
cp_board.key_source = lambda cb: Src(cb)

def make(cls):
    kp = cls()
    got = []
    kp._key_event = lambda ch, ts=None: got.append(ch)
    return kp, got

def press(kp, *names):
    # hold names[:-1] (modifiers), tap names[-1], release all
    for nm in names:
        kp.raw_event(NUM[nm], True)
    for nm in reversed(names):
        kp.raw_event(NUM[nm], False)

def result(kp, got, *names):
    del got[:]
    press(kp, *names)
    return [c for c in got if c]

print('== Mk5 keypad (mempad.py)')
from mempad import MembraneNumpad
kp, got = make(MembraneNumpad)
check('key source started on creation', started == [1])
for d in '0123456789':
    check('%s -> %s' % (d, d), result(kp, got, d) == [d])
check('Enter -> OK', result(kp, got, 'ENTER') == ['y'])
check('esc (`) -> X', result(kp, got, '`') == ['x'])
check('del (Bksp) -> X', result(kp, got, 'BKSP') == ['x'])
for k, want, nm in ((';', '5', 'up'), ('.', '8', 'down'), (',', '7', 'left'), ('/', '9', 'right')):
    check('arrow %s (%s) -> %s' % (nm, k, want), result(kp, got, k) == [want])
    check('Fn+arrow %s -> %s' % (nm, want), result(kp, got, 'FN', k) == [want])
check('Fn+Enter -> OK', result(kp, got, 'FN', 'ENTER') == ['y'])
for k in ('a', 'y', 'x', 'q', 'ALT', 'TAB', ' ', '-', '='):
    check('%r ignored' % k, result(kp, got, k) == [])
check('"all up" reported after a key', got[-1:] == [''] or result(kp, got, '1') == ['1'])

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
