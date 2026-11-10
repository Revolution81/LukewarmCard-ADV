# cp_board.py - M5Stack Cardputer ADV (ESP32-S3FN8, 8MB flash, no PSRAM).
#
# Pin map from M5Stack docs (docs.m5stack.com/en/core/Cardputer-Adv):
#   LCD ST7789V2 240x135:  MOSI 35, SCK 36, DC 34, CS 37, RST 33, backlight 38
#   Keyboard TCA8418:      I2C SDA 8, SCL 9, INT 11, address 0x34
#   Same I2C bus:          ES8311 codec 0x18, BMI270 motion sensor 0x68
#   Microphone (I2S):      BCLK 41, WS 43, DIN 46 (ES8311 ADC)
#   RGB LED (WS2812):      GPIO 21
#   microSD (SPI):         CS 12, MOSI 14, SCK 40, MISO 39
#   Battery:               ADC on GPIO 10 via 2:1 divider
#
import machine, esp32, os, utime, micropython
import cardputer, cp_buildinfo

IS_DEV = cp_buildinfo.IS_DEV
LCD_W, LCD_H = 240, 135

# If the picture is mirrored, offset, or blue-tinted on your unit, adjust these.
LCD_MADCTL = 0x60          # landscape, keyboard below (MV|MX); try 0xA0 if upside down
LCD_X_OFF = 40
LCD_Y_OFF = 53             # some panels need 52
LCD_INVERT = True          # IPS panel: inversion on
LCD_SPI_HZ = 40_000_000

PIN_MAP = {
    'SD_DETECT': ('v', 1),      # no card-detect switch; mount attempt decides
}

_machine = machine
def real_machine():
    return _machine

# ---- display ----

class ST7789:
    def __init__(self):
        from machine import Pin, SPI
        # SPI(2) = SPI3_HOST; the SD card uses SPI2_HOST (SDCard slot=3)
        self.spi = SPI(2, baudrate=LCD_SPI_HZ, polarity=0, phase=0,
                       sck=Pin(36), mosi=Pin(35), miso=None)
        self.dc = Pin(34, Pin.OUT, value=1)
        self.cs = Pin(37, Pin.OUT, value=1)
        self.rst = Pin(33, Pin.OUT, value=1)
        self._wbuf = bytearray(4)
        self._init_panel()

    def _cmd(self, c, data=None):
        self.cs(0)
        self.dc(0)
        self.spi.write(bytes((c,)))
        if data:
            self.dc(1)
            self.spi.write(data)
        self.cs(1)

    def _init_panel(self):
        self.rst(0); utime.sleep_ms(10); self.rst(1); utime.sleep_ms(120)
        self._cmd(0x01)                     # SWRESET
        utime.sleep_ms(150)
        self._cmd(0x11)                     # SLPOUT
        utime.sleep_ms(120)
        self._cmd(0x3A, b'\x55')            # COLMOD 16-bit
        self._cmd(0x36, bytes((LCD_MADCTL,)))
        self._cmd(0x21 if LCD_INVERT else 0x20)
        self._cmd(0x13)                     # NORON
        self.fill_black()
        self._cmd(0x29)                     # DISPON

    def fill_black(self):
        self._set_window(0, 0, LCD_W, LCD_H)
        line = bytes(LCD_W * 2 * 9)
        for _ in range(LCD_H // 9):
            self.write_data(line)

    def _set_window(self, x, y, w, h):
        x += LCD_X_OFF
        y += LCD_Y_OFF
        b = self._wbuf
        b[0] = x >> 8; b[1] = x & 0xff; b[2] = (x+w-1) >> 8; b[3] = (x+w-1) & 0xff
        self._cmd(0x2A, b)
        b[0] = y >> 8; b[1] = y & 0xff; b[2] = (y+h-1) >> 8; b[3] = (y+h-1) & 0xff
        self._cmd(0x2B, b)
        self.cs(0)
        self.dc(0)
        self.spi.write(b'\x2c')             # RAMWR; data follows
        self.dc(1)
        self.cs(1)

    def write_data(self, buf):
        self.cs(0)
        self.dc(1)
        self.spi.write(buf)
        self.cs(1)

_LCD = None
def lcd_dev():
    global _LCD
    if _LCD is None:
        _LCD = ST7789()
    return _LCD

_BL = None
def backlight(v):
    global _BL
    if _BL is None:
        _BL = machine.PWM(machine.Pin(38), freq=2000)
    v = max(0, min(255, int(v)))
    _BL.duty_u16(v * 257)

# ---- randomness / identity ----

def rng_bytes(buf):
    # hardware TRNG; raises if the entropy source is not on (fail closed)
    cardputer.rng_bytes(buf)

def chip_id():
    return cardputer.chip_id()

# ---- flash partitions ----

def _part(label):
    p = esp32.Partition.find(esp32.Partition.TYPE_DATA, label=label)
    if not p:
        raise OSError('no partition ' + label)
    return p[0]

# M5Launcher builds keep SE state, scratch and /flash inside one 'vfs'
# partition at fixed offsets (see cp_flashlayout.py). Normal builds use the
# three separate partitions in boards/.../partitions.csv.
import cp_buildinfo
LAUNCHER = getattr(cp_buildinfo, 'LAYOUT', 'own') == 'launcher'
_LAYOUT = None

def _layout():
    global _LAYOUT
    if _LAYOUT is None:
        import cp_flashlayout
        _LAYOUT = cp_flashlayout.Layout(_part('vfs'))
    return _LAYOUT

def _se_dev():
    return _layout().se() if LAUNCHER else _part('ccse')

def _scratch_dev():
    return _layout().scratch() if LAUNCHER else _part('ccscratch')

def _fs_dev():
    return _layout().fs() if LAUNCHER else _part('vfs')

class PartFlash:
    # raw partition with 4K erase sectors (PSRAM replacement)
    sector_size = 4096
    def __init__(self, dev):
        self.p = dev
        self.size = self.p.ioctl(4, 0) * self.p.ioctl(5, 0)
    def read(self, addr, buf):
        self.p.readblocks(addr // 4096, buf, addr % 4096)
    def write_sector(self, addr, data):
        self.p.ioctl(6, addr // 4096)                # erase
        self.p.writeblocks(addr // 4096, data, 0)
    def erase_sector(self, addr):
        self.p.ioctl(6, addr // 4096)

def scratch_device():
    return PartFlash(_scratch_dev())

class SEStore:
    # soft-SE state: two 16K slots in partition 'ccse', newest valid one wins,
    # so a power cut mid-write can't lose the seed/PIN record.
    SLOT = 16 * 1024
    def __init__(self):
        self.p = _se_dev()
    def _read_slot(self, n):
        hdr = bytearray(12)
        self.p.readblocks(n * self.SLOT // 4096, hdr, 0)
        if hdr[0:4] != b'CPS1':
            return None, -1
        seq = int.from_bytes(hdr[4:8], 'little')
        ln = int.from_bytes(hdr[8:12], 'little')
        if not (0 < ln <= self.SLOT - 44):
            return None, -1
        body = bytearray(ln + 32)
        self.p.readblocks(n * self.SLOT // 4096, body, 12)
        import ngu
        if bytes(ngu.hash.sha256s(hdr + body[:ln])) != bytes(body[ln:]):
            return None, -1
        return bytes(body[:ln]), seq
    def load(self):
        best, bseq = None, -1
        for n in (0, 1):
            d, s = self._read_slot(n)
            if d is not None and s > bseq:
                best, bseq = d, s
        self._seq = bseq
        return best
    def save(self, data):
        import ngu
        if not hasattr(self, '_seq'):
            self.load()
        seq = self._seq + 1
        n = seq % 2
        hdr = b'CPS1' + seq.to_bytes(4, 'little') + len(data).to_bytes(4, 'little')
        blob = hdr + data + bytes(ngu.hash.sha256s(hdr + data))
        blob += b'\xff' * (-len(blob) % 4096)
        base = n * self.SLOT // 4096
        for i in range(self.SLOT // 4096):
            self.p.ioctl(6, base + i)
        self.p.writeblocks(base, blob, 0)
        if self._read_slot(n) != (data, seq):
            raise OSError(5)
        # good copy written: erase the older one, so no stale record (e.g. a
        # wiped seed) stays behind in the other slot
        other = (1 - n) * self.SLOT // 4096
        for i in range(self.SLOT // 4096):
            self.p.ioctl(6, other + i)
        self._seq = seq
    def erase(self):
        self._seq = -1
        for i in range(2 * self.SLOT // 4096):
            self.p.ioctl(6, i)

def se_store():
    return SEStore()

# ---- microSD ----

_SD = None
def sd_block_device():
    global _SD
    if _SD is None:
        from machine import Pin
        # slot=3 = SPI2_HOST on the ESP32-S3 in MicroPython 1.29 (slot 2 is
        # SPI3_HOST, which the LCD already uses as machine.SPI(2); using it
        # made every SD mount fail on real hardware)
        _SD = machine.SDCard(slot=3, width=1, sck=Pin(40), miso=Pin(39), mosi=Pin(14),
                             cs=Pin(12), freq=20_000_000)
    return _SD

def sd_release():
    global _SD
    if _SD is not None:
        try:
            _SD.deinit()
        except Exception:
            pass
        _SD = None

# ---- battery ----

def batt_volts():
    # Not read yet: the ADC shares hardware with the entropy source that
    # cardputer.entropy() keeps running. Reported as "external power".
    return None

# ---- shared I2C bus: keyboard, codec (microphone), motion sensor ----

_I2C = None
def i2c():
    global _I2C
    if _I2C is None:
        from machine import Pin, I2C
        _I2C = I2C(0, sda=Pin(8), scl=Pin(9), freq=400_000)
    return _I2C

def entropy_sources():
    # extra noise for the "secure element" random shares (cp_entropy.py)
    import cp_sensors
    bus = i2c()
    return {'mic': cp_sensors.ES8311Mic(bus), 'imu': cp_sensors.BMI270(bus)}

def mem_report():
    # RAM headroom. MicroPython's heap grows on demand out of the system
    # (ESP-IDF) heap, so what matters is the system heap's free space, and
    # its low-water mark since power-on (IDF tracks it). -> KB
    import gc, esp32
    gc.collect()
    free = low = 0
    for total, f, largest, minfree in esp32.idf_heap_info(esp32.HEAP_DATA):
        free += f
        low += minfree
    return dict(now=(free + gc.mem_free()) // 1024, low=low // 1024,
                py_used=gc.mem_alloc() // 1024)

def test_sensors():
    # microphone + motion sensor, for the self-test
    return entropy_sources()

# ---- RGB LED: WS2812 on the StampS3A, GPIO 21 ----
# Used as the COLDCARD "USB light": white in the self-test, green while a
# computer has the USB link set up.

_LED_PIN = None
_LED_NOW = None
_LED_HELD = False

def led(r, g, b):
    global _LED_PIN, _LED_NOW
    c = (r, g, b)
    if c == _LED_NOW:
        return
    from machine import Pin, bitstream
    if _LED_PIN is None:
        _LED_PIN = Pin(21, Pin.OUT, value=0)
    # WS2812 timing (ns): 0 = 400 high / 850 low, 1 = 800 / 450; GRB order
    bitstream(_LED_PIN, 0, (400, 850, 800, 450), bytes((g, r, b)))
    _LED_NOW = c

def led_hold(on):
    # self-test owns the LED while True (the USB status ignores it)
    global _LED_HELD
    _LED_HELD = bool(on)

def led_held():
    return _LED_HELD

def usb_connected():
    # a computer has set up the USB link and it's active
    import cardputer
    return cardputer.usb_state() == 1

# ---- keyboard: TCA8418 ----

class TCA8418:
    ADDR = 0x34

    def __init__(self, cb):
        from machine import Pin
        self.cb = cb
        self.i2c = i2c()
        self.int_pin = Pin(11, Pin.IN, Pin.PULL_UP)
        self._w(0x1D, 0x7F)                 # KP_GPIO1: rows 0..6 in keypad
        self._w(0x1E, 0xFF)                 # KP_GPIO2: cols 0..7 in keypad
        self._w(0x1F, 0x00)                 # KP_GPIO3: cols 8,9 not used
        self._drain()
        self._w(0x02, 0x1F)                 # clear INT_STAT
        self._w(0x01, self._r(0x01) | 0x01) # CFG: key event interrupt enable
        self._w(0x02, 0x1F)

    def _w(self, reg, val):
        self.i2c.writeto_mem(self.ADDR, reg, bytes((val,)))

    def _r(self, reg):
        return self.i2c.readfrom_mem(self.ADDR, reg, 1)[0]

    def _drain(self, deliver=False):
        for _ in range(16):
            n = self._r(0x03) & 0x0F        # KEY_LCK_EC: events queued
            if not n:
                break
            for _ in range(n):
                ev = self._r(0x04)          # KEY_EVENT_A
                if deliver and ev:
                    self.cb(ev & 0x7F, bool(ev & 0x80))
        self._w(0x02, 0x1F)

    def start(self):
        # called once by keyboard.py / mempad.py when they're created
        if getattr(self, '_started', False):
            return
        self._started = True
        import uasyncio
        uasyncio.create_task(self._task())

    async def _task(self):
        # Poll the key-event FIFO every 10 ms. The INT pin only lets us look
        # again sooner; key events are never missed if it isn't wired as
        # expected, since the FIFO count is read either way.
        import uasyncio
        while True:
            try:
                if self._r(0x03) & 0x0F:
                    self._drain(deliver=True)
                    await uasyncio.sleep_ms(2)
                    continue
            except OSError as exc:
                print("kbd i2c: %r" % exc)
            await uasyncio.sleep_ms(10)

def key_source(cb):
    return TCA8418(cb)

# ---- power / lifecycle ----

def reset():
    machine.reset()

def bootloader():
    # ROM download mode, for esptool. Always available: nothing can lock it.
    machine.bootloader()

def halt():
    # stop here until the user power-cycles or presses reset
    while True:
        utime.sleep(60)

def wipe_settings():
    try:
        for fn in os.listdir('/flash/settings'):
            os.remove('/flash/settings/' + fn)
    except OSError:
        pass

def _storage_error(exc):
    # can't continue without storage: say why on screen, then stop
    lcd_dev()
    backlight(255)
    try:
        import lcd
        lcd.fill_rect(lcd_dev(), 0, 0, LCD_W, LCD_H, 0)
    except Exception:
        pass
    print('Storage error:', exc)
    try:
        import framebuf
        fb = framebuf.FrameBuffer(bytearray(LCD_W * 16 // 8), LCD_W, 16, framebuf.MONO_HLSB)
        for i, ln in enumerate(('Storage error', str(exc)[:29])):
            fb.fill(0); fb.text(ln, 0, 4, 1)
            import lcd
            lcd.send_mono(lcd_dev(), 0, 40 + i * 24, LCD_W, 16, _hlsb_to_vlsb(fb, LCD_W, 16), LCD_W, 16, 0xFFFF, 0)
    except Exception:
        pass
    halt()

def _hlsb_to_vlsb(fb, w, h):
    # tiny helper for _storage_error: lcd.send_mono takes MONO_VLSB data
    import framebuf
    out = bytearray(w * h // 8)
    v = framebuf.FrameBuffer(out, w, h, framebuf.MONO_VLSB)
    v.blit(fb, 0, 0)
    return out

def early_init():
    # 1) true entropy source on before anything can ask for random bytes
    cardputer.entropy(True)

    # 2) COLDCARD's /flash filesystem (littlefs): partition "vfs", or its
    #    filesystem window in a Launcher build
    try:
        bdev = _fs_dev()
    except OSError as exc:
        _storage_error(exc)
    try:
        os.mount(os.VfsLfs2(bdev, progsize=256), '/flash')
    except OSError:
        os.VfsLfs2.mkfs(bdev, progsize=256)
        os.mount(os.VfsLfs2(bdev, progsize=256), '/flash')
    try:
        os.mkdir('/flash/settings')
    except OSError:
        pass

    # 3) screen on early (black), backlight up
    lcd_dev()
    backlight(255)

# EOF
