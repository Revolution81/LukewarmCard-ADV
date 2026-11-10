# mempad.py - Cardputer port, Mk4/Mk5 variant: stands in for COLDCARD's
# membrane keypad driver (same class name, MembraneNumpad).
#
# The Mk4/Mk5 keypad has 12 keys: 0-9, OK (y) and X (x). The Cardputer's
# TCA8418 keyboard events (cp_board.key_source) are turned into exactly those
# 12 codes, so COLDCARD's Mk4 UI code (ux_mk4.py, menus, PIN entry) sees a
# normal Mk4 keypad.
#
# Cardputer key -> Mk4/Mk5 key (user's choice, 2026-11-06)
#   0-9                       0-9
#   Enter (ok)                OK (check mark)
#   esc (`) or del (Bksp)     X (cancel / back)
#   arrow keys ;  .  ,  /     5  8  7  9   (up, down, left, right, like the
#                                          Mk5's arrow keys 5/8/7/9)
# Works with or without Fn held. Every other key is ignored, as a Mk5 has
# no other keys.
#
import utime
from numpad import NumpadBase
from cp_keys import key_name

_MAP = {
    '0':'0', '1':'1', '2':'2', '3':'3', '4':'4',
    '5':'5', '6':'6', '7':'7', '8':'8', '9':'9',
    'ENTER':'y',
    'BKSP':'x', '`':'x',
    ';':'5', '.':'8', ',':'7', '/':'9',
}
_META = ('FN', 'SHIFT', 'CTRL', 'OPT')


class MembraneNumpad(NumpadBase):

    def __init__(self):
        super().__init__()
        self.down = set()               # Cardputer key names currently held
        self._char_reported = set()
        self.waiting_for_any = True
        self.lp_time = 0
        import cp_board
        self.src = cp_board.key_source(self.raw_event)
        # COLDCARD never calls start(): the real membrane driver scans from
        # the moment it's created, so start reading keys now
        self.src.start()

    def start(self):
        self.src.start()

    def raw_event(self, number, pressed):
        # called by cp_board key source for each TCA8418 FIFO event
        name = key_name(number)
        if not name:
            return

        if self._mash_mode and pressed:
            self._mash_press_timestamp = self.mash_ticks()

        if pressed:
            self.down.add(name)
            self.lp_time = utime.ticks_ms()
            ch = _MAP.get(name)
            if ch and ch not in self._char_reported:
                if not (self._mash_mode and self._mash_press_timestamp is None):
                    self._char_reported.add(ch)
                    ts = self._mash_press_timestamp if self._mash_mode else None
                    self._key_event(ch, ts)
                    self._mash_press_timestamp = None
        else:
            self.down.discard(name)

        if self._char_reported and not (self.down - set(_META)):
            # all keys up: report "all up", as the membrane driver does
            self._char_reported.clear()
            self._key_event('')

# EOF
