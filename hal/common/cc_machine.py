# cc_machine.py - Cardputer port: wrapper around the real "machine" module.
#
# COLDCARD addresses STM32 pins by name, e.g. Pin('SD_ACTIVE'). cc_boot installs
# this module as sys.modules['machine'] so those names resolve here:
#   * names in cp_board.PIN_MAP become real GPIOs
#   * names for hardware the Cardputer lacks become harmless dummy pins
#   * names the Q1 uses to *detect* hardware (LCD_TEAR, STRAP_MK5, NFC_*) raise
#     ValueError, exactly like on a board without them
#
import cp_board
_real = cp_board.real_machine()

# re-export everything from the real module
for _n in dir(_real):
    if not _n.startswith('__'):
        globals()[_n] = getattr(_real, _n)

_DETECT_ONLY = {'LCD_TEAR', 'STRAP_MK5', 'NFC_SDA', 'NFC_SCL', 'REV_D'}

class _DummyPin:
    # output pins for LEDs etc. that don't exist here
    def __init__(self, name, value=0):
        self.name = name
        self._v = int(value)
    def value(self, v=None):
        if v is None:
            return self._v
        self._v = int(v)
    def __call__(self, v=None):
        return self.value(v)
    def on(self):
        self._v = 1
    def off(self):
        self._v = 0
    def irq(self, *a, **k):
        return None
    def init(self, *a, **k):
        pass

_RP = getattr(_real, 'Pin', None)     # (desktop test build has no Pin)

class Pin:
    # constructor-compatible facade: Pin('NAME', ...) or Pin(<gpio number>, ...)
    IN = getattr(_RP, 'IN', 1)
    OUT = getattr(_RP, 'OUT', 3)
    OUT_OD = getattr(_RP, 'OPEN_DRAIN', OUT)
    OPEN_DRAIN = OUT_OD
    PULL_UP = getattr(_RP, 'PULL_UP', 2)
    PULL_DOWN = getattr(_RP, 'PULL_DOWN', 1)
    PULL_NONE = None
    IRQ_FALLING = getattr(_RP, 'IRQ_FALLING', 2)
    IRQ_RISING = getattr(_RP, 'IRQ_RISING', 1)
    ALT = None
    AF8_UART4 = None

    def __new__(cls, name, *a, **kw):
        if isinstance(name, int):
            return _real.Pin(name, *a, **kw)
        if name in _DETECT_ONLY:
            raise ValueError(name)
        if name in cp_board.PIN_MAP:
            # int => real GPIO number; ('v', n) => dummy pin reading n
            fixed = cp_board.PIN_MAP[name]
            if isinstance(fixed, int):
                return _real.Pin(fixed, *a, **kw)
            return _DummyPin(name, fixed[1])
        # anything else: a dummy output that remembers its value
        return _DummyPin(name, kw.get('value', 0))

def unique_id():
    # 12 bytes like STM32 (version.serial_number() indexes into it)
    cid = cp_board.chip_id()
    return bytes(cid + cid)[0:12]

def reset():
    cp_board.reset()

def soft_reset():
    cp_board.reset()

def bootloader():
    cp_board.bootloader()

# EOF
