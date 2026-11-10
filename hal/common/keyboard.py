# keyboard.py - Cardputer ADV keyboard for COLDCARD (replaces Q1 keyboard.py).
#
# The Cardputer ADV's 56 keys are scanned by a TCA8418 chip. cp_board delivers
# raw events (key number 1..80, pressed?) and this class turns them into the
# same character codes the Q1 keyboard produces (see charcodes.py).
#
# Layout (from M5Stack / cardputer-adv crate):
#   `  1 2 3 4 5 6 7 8 9 0 - = Bksp
#   Tab q w e r t y u i o p [ ] \
#   Fn Shft a s d f g h j k l ; ' Enter
#   Ctrl Opt Alt z x c v b n m , . / Space
#
# COLDCARD Q key mapping (user's choice, 2026-11-06):
#   Letters, numbers   same keys; Shift gives capitals and the symbols printed
#                      on the Cardputer keys (Shift+1 = !, Shift+; = :, ...)
#   Enter (OK)         Enter
#   Arrows             the Cardputer's arrow keys: Fn+;  Fn+.  Fn+,  Fn+/
#                      (up, down, left, right); plain ; . , / type normally
#   F1..F6             Fn+Z Fn+X Fn+C Fn+V Fn+B Fn+N   (the Q's SYM+Z..N)
# Not decided yet, kept from before:
#   Esc (cancel)       Fn+`   or   Alt
#   PgUp/PgDn          Fn+Shift+;  Fn+Shift+.
#   Home/End           Fn+Shift+,  Fn+Shift+/
#   Delete             Bksp       Shift+Bksp = clear field
#   QR                 Fn+Q
#   Caps lock          Ctrl+Shift
#
import utime, uasyncio
from numpad import NumpadBase
from charcodes import *
from cp_keys import key_name     # Cardputer key matrix layout (shared with mempad.py)

_SHIFTED = {
    '`':'~','1':'!','2':'@','3':'#','4':'$','5':'%','6':'^','7':'&','8':'*',
    '9':'(','0':')','-':'_','=':'+','[':'{',']':'}','\\':'|',';':':',"'":'"',
    ',':'<','.':'>','/':'?',
}
_FN = {
    '`': KEY_CANCEL, ';': KEY_UP, '.': KEY_DOWN, ',': KEY_LEFT, '/': KEY_RIGHT,
    'BKSP': KEY_DELETE, 'q': KEY_QR,
    'z': KEY_F1, 'x': KEY_F2, 'c': KEY_F3, 'v': KEY_F4, 'b': KEY_F5, 'n': KEY_F6,
}
_FN_SHIFT = {';': KEY_PAGE_UP, '.': KEY_PAGE_DOWN, ',': KEY_HOME, '/': KEY_END}
_SPECIAL = {'BKSP': KEY_DELETE, 'TAB': KEY_TAB, 'ENTER': KEY_ENTER, 'ALT': KEY_CANCEL}
_META = ('FN', 'SHIFT', 'CTRL', 'OPT')

class FullKeyboard(NumpadBase):

    def __init__(self):
        super().__init__()
        self.down = set()               # names currently held
        self._char_reported = set()
        self.torch_on = False
        self.caps_lock = False
        self.shift_down = False
        self.symbol_down = False        # shows Fn state in the status bar
        self.waiting_for_any = True
        self.lp_time = 0
        import cp_board
        self.src = cp_board.key_source(self.raw_event)
        # COLDCARD never calls start(): its own keypad drivers scan from the
        # moment they're created, so start reading keys now
        self.src.start()

    def start(self):
        self.src.start()

    def start_mash(self):
        super().start_mash()

    def stop_mash(self):
        super().stop_mash()

    def decode(self, name):
        # name of key just pressed -> COLDCARD char code, or None
        fn = 'FN' in self.down
        shift = 'SHIFT' in self.down
        if fn:
            if shift and name in _FN_SHIFT:
                return _FN_SHIFT[name]
            if name in _FN:
                return _FN[name]
        if name == 'BKSP' and shift:
            return KEY_CLEAR
        if name in _SPECIAL:
            return _SPECIAL[name]
        if name in _META:
            return None
        if len(name) == 1 and 'a' <= name <= 'z':
            return name.upper() if (shift ^ self.caps_lock) else name
        if shift:
            return _SHIFTED.get(name, name)
        return name

    def raw_event(self, number, pressed):
        # called by cp_board key source for each TCA8418 FIFO event
        name = key_name(number)
        if not name:
            return

        if self._mash_mode and pressed:
            self._mash_press_timestamp = self.mash_ticks()

        status_chg = {}
        if pressed:
            self.down.add(name)
            self.lp_time = utime.ticks_ms()
            if name in ('SHIFT', 'CTRL') and {'SHIFT', 'CTRL'} <= self.down \
                    and not self._mash_mode:
                self.caps_lock = not self.caps_lock
                status_chg['caps'] = int(self.caps_lock)
            ch = self.decode(name)
            if ch and ch not in self._char_reported:
                if not (self._mash_mode and self._mash_press_timestamp is None):
                    self._char_reported.add(ch)
                    ts = self._mash_press_timestamp if self._mash_mode else None
                    self._key_event(ch, ts)
                    self._mash_press_timestamp = None
        else:
            self.down.discard(name)

        sd = 'SHIFT' in self.down
        fd = 'FN' in self.down
        if sd != self.shift_down:
            self.shift_down = sd
            status_chg['shift'] = int(sd)
        if fd != self.symbol_down:
            self.symbol_down = fd
            status_chg['symbol'] = int(fd)

        if status_chg:
            try:
                from glob import dis
                uasyncio.create_task(dis.async_draw_status(**status_chg))
            except Exception:
                pass

        if self._char_reported and not (self.down - set(_META)):
            # all non-modifier keys up: report "all up"
            self._char_reported.clear()
            self._key_event('')

# EOF
