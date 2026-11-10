# cp_board.py - DESKTOP TEST version of the Cardputer board layer.
#
# Lets the exact firmware Python run under unix MicroPython:
#   * LCD -> 240x135 RGB565 framebuffer, saved as screenshots on request
#   * /flash -> littlefs on a file, /sd -> FAT image file
#   * SE store and PSRAM scratch -> files
#   * keys are injected by the test harness (host_test.py)
#
import os, sys
import cp_buildinfo

IS_DEV = cp_buildinfo.IS_DEV
LCD_W, LCD_H = 240, 135
WORK = os.getenv('CP_WORK') or (os.getcwd() + '/cp-work')
assert WORK.startswith('/'), 'CP_WORK must be absolute'

PIN_MAP = {
    'SD_DETECT': ('v', 1),      # "card inserted"; mount failures handled by COLDCARD
}

_machine = None
def real_machine():
    global _machine
    if _machine is None:
        import machine
        _machine = machine
    return _machine

def _mkdirs(p):
    try:
        os.mkdir(p)
    except OSError:
        pass

# ---- LCD ----

def _outside_heap(n):
    # framebuffer in C malloc memory, so heap measurements match the device
    # (the real ST7789 keeps its pixels in the panel, not in our RAM)
    try:
        import ffi, uctypes
        libc = ffi.open('libc.so.6')
        p = libc.func('p', 'calloc', 'ii')(n, 1)
        return uctypes.bytearray_at(p, n)
    except Exception:
        return bytearray(n)

class FakeLCD:
    def __init__(self):
        self.fb = _outside_heap(LCD_W * LCD_H * 2)
        self.win = (0, 0, LCD_W, LCD_H)
        self.pos = 0
        self.brightness = 255
        self.writes = 0

    def _set_window(self, x, y, w, h):
        self.win = (x, y, w, h)
        self.pos = 0

    def write_data(self, buf):
        x0, y0, w, h = self.win
        fb = self.fb
        n = len(buf) // 2
        p = self.pos
        for i in range(n):
            px, py = x0 + (p % w), y0 + (p // w)
            if 0 <= px < LCD_W and 0 <= py < LCD_H:
                o = (py * LCD_W + px) * 2
                fb[o] = buf[2*i]
                fb[o+1] = buf[2*i+1]
            p += 1
        self.pos = p
        self.writes += 1

    def save(self, fname):
        # raw big-endian RGB565; tools/host_shots.py converts to PNG
        with open(fname, 'wb') as f:
            f.write(self.fb)

_LCD = None
def lcd_dev():
    global _LCD
    if _LCD is None:
        _LCD = FakeLCD()
    return _LCD

def backlight(v):
    lcd_dev().brightness = v

# ---- randomness / ids ----

def rng_bytes(buf):
    buf[:] = os.urandom(len(buf))

def entropy_sources():
    # desktop build: no microphone or motion sensor (tests inject fakes)
    return {}

class _SimMic:
    # desktop stand-in for the self-test: quiet, then a "clap"
    def open(self):
        self.n = 0
    def close(self):
        pass
    def loudness(self):
        import utime
        utime.sleep_ms(16)
        self.n += 1
        return 120 + (self.n % 7) * 10 if self.n < 40 else 21000

class _SimMotion:
    # desktop stand-in: still, then turned
    def open(self):
        self.n = 0
    def close(self):
        pass
    def turn_rate(self):
        import utime
        utime.sleep_ms(5)
        self.n += 1
        return 0.4 if self.n < 150 else 95.0

def mem_report():
    # desktop: fixed-size heap (-X heapsize), no system heap
    import gc
    gc.collect()
    return dict(now=gc.mem_free() // 1024, low=gc.mem_free() // 1024,
                py_used=gc.mem_alloc() // 1024)

def test_sensors():
    # desktop has no microphone or motion sensor: simulated for the self-test
    print('[selftest] simulated microphone + motion sensor (desktop)')
    return {'mic': _SimMic(), 'imu': _SimMotion()}

# RGB LED and USB status: recorded, so tests can check them
LED_LOG = []
_LED_NOW = None
_LED_HELD = False
USB_CONNECTED = False

def led(r, g, b):
    global _LED_NOW
    if (r, g, b) != _LED_NOW:
        _LED_NOW = (r, g, b)
        LED_LOG.append(_LED_NOW)
        print('[led] %r' % (_LED_NOW,))

def led_hold(on):
    global _LED_HELD
    _LED_HELD = bool(on)

def led_held():
    return _LED_HELD

def usb_connected():
    return USB_CONNECTED

def chip_id():
    return b'\xc0\xff\xee\x00\x00\x01'

# ---- storage ----

class FileStore:
    def __init__(self, fn):
        self.fn = fn
    def load(self):
        try:
            with open(self.fn, 'rb') as f:
                return f.read()
        except OSError:
            return None
    def save(self, data):
        with open(self.fn + '.tmp', 'wb') as f:
            f.write(data)
        os.rename(self.fn + '.tmp', self.fn)
    def erase(self):
        try:
            os.remove(self.fn)
        except OSError:
            pass

def se_store():
    return FileStore(WORK + '/se.bin')

class FileFlash:
    # raw flash partition emulation: 4K erase sectors
    sector_size = 4096
    def __init__(self, fn, size):
        self.fn, self.size = fn, size
        try:
            os.stat(fn)
        except OSError:
            with open(fn, 'wb') as f:
                f.write(b'\xff' * size)
    def read(self, addr, buf):
        with open(self.fn, 'rb') as f:
            f.seek(addr)
            f.readinto(buf)
    def write_sector(self, addr, data):
        assert addr % self.sector_size == 0 and len(data) == self.sector_size
        with open(self.fn, 'r+b') as f:
            f.seek(addr)
            f.write(data)
    def erase_sector(self, addr):
        self.write_sector(addr - (addr % self.sector_size), b'\xff' * self.sector_size)

def scratch_device():
    return FileFlash(WORK + '/scratch.bin', 1024 * 1024)

class FileBlockDev:
    # block device over a file, for littlefs (/flash) and FAT (/sd)
    def __init__(self, fn, nblocks, bsize=512):
        self.fn, self.n, self.bs = fn, nblocks, bsize
        try:
            os.stat(fn)
        except OSError:
            with open(fn, 'wb') as f:
                f.seek(nblocks * bsize - 1)
                f.write(b'\0')
        self.f = open(fn, 'r+b')
    def readblocks(self, n, buf, off=0):
        self.f.seek(n * self.bs + off)
        self.f.readinto(buf)
    def writeblocks(self, n, buf, off=None):
        self.f.seek(n * self.bs + (off or 0))
        self.f.write(buf)
        self.f.flush()
    def ioctl(self, op, arg):
        if op == 4: return self.n
        if op == 5: return self.bs
        if op == 6: return 0
        return 0

_SD = None
def sd_block_device():
    # tests "pull the card" by creating <work>/card-out (host_test: cardout)
    global _SD
    try:
        os.stat(WORK + '/card-out')
        _SD = None
        raise OSError(19)
    except OSError as exc:
        if exc.args and exc.args[0] == 19:
            raise
    if _SD is None:
        fn = WORK + '/sdcard.img'
        new = True
        try:
            os.stat(fn)
            new = False
        except OSError:
            pass
        _SD = FileBlockDev(fn, 64 * 2048)       # 64MB
        if new:
            os.VfsFat.mkfs(_SD)
    return _SD

def sd_release():
    pass

def batt_volts():
    return None         # "on USB power"

# ---- keyboard ----

class HostKeys:
    # test harness calls .press(name) / .type(text)
    def __init__(self, cb):
        self.cb = cb
    def start(self):
        pass

_KEYS = None
def key_source(cb):
    global _KEYS
    _KEYS = HostKeys(cb)
    return _KEYS

# ---- power / lifecycle ----

class Reboot(Exception):
    pass

def reset():
    print("[cp_board] reset requested")
    raise SystemExit(3)

def bootloader():
    print("[cp_board] bootloader requested")
    raise SystemExit(4)

def halt():
    # test aid: keep the last screen (e.g. logout) as shots/halt.png
    try:
        try:
            os.mkdir(WORK + '/shots')
        except OSError:
            pass
        lcd_dev().save(WORK + '/shots/halt.rgb565')
    except Exception:
        pass
    print("[cp_board] halt")
    raise SystemExit(5)

def wipe_settings():
    try:
        for fn in os.listdir('/flash/settings'):
            os.remove('/flash/settings/' + fn)
    except OSError:
        pass

def early_init():
    _mkdirs(WORK)
    bd = FileBlockDev(WORK + '/flash.img', 2048, 512)     # 1MB littlefs
    try:
        os.mount(os.VfsLfs2(bd), '/flash')
    except OSError:
        os.VfsLfs2.mkfs(bd)
        os.mount(os.VfsLfs2(bd), '/flash')
    try:
        os.mkdir('/flash/settings')
    except OSError:
        pass

# EOF
