# test_entropy.py - the extra randomness sources (hal/common/cp_entropy.py,
# hal/device/cp_sensors.py) without hardware.
#
# Fake I2C devices stand in for the BMI270 motion sensor and the ES8311 codec,
# and a fake machine.I2S for the microphone stream. Uses the exact device
# files. Run with the desktop build:
#   build/host-mk4/cc-mpy -X heapsize=4m tests/test_entropy.py
#
# Checks: BMI270 start-up follows Bosch's sequence and uploads the config
# blob byte for byte; codec registers match M5Unified; healthy sensors are
# mixed in; flat/stuck/missing sensors are reported and left out without
# blocking; the chip RNG is mandatory; COLDCARD's callgate gets the right
# lengths.
import sys, os

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

def noise(n):
    return os.urandom(n)

def fill(buf, data):
    for i in range(len(buf)):
        buf[i] = data[i]

def good_chip(buf):
    fill(buf, noise(len(buf)))

# ---- fake I2C devices ----
class FakeBMI270:
    def __init__(self, gyro_mode='noise'):
        self.regs = bytearray(256)
        self.regs[0x00] = 0x24
        self.cfg = bytearray(8192)
        self.addr = 0
        self.reset_count = 0
        self.gyro_mode = gyro_mode
        self.log = []
    def write(self, reg, data):
        self.log.append((reg, bytes(data)))
        if reg == 0x5B:
            self.addr = (data[0] & 0x0F) | (data[1] << 4)
            return
        if reg == 0x5E:
            # INIT_ADDR must be set before every chunk (Bosch's procedure)
            b = self.addr * 2
            self.cfg[b:b + len(data)] = data
            self.addr = None
            return
        if reg == 0x7E and data[0] == 0xB6:
            self.reset_count += 1
            self.cfg = bytearray(8192)
        if reg == 0x59 and data[0] == 1:
            from cp_bmi270_cfg import CONFIG
            ok = bytes(self.cfg) == CONFIG and self.regs[0x7C] & 1 == 0
            self.regs[0x21] = 1 if ok else 2
        self.regs[reg] = data[0]
    def read(self, reg, n):
        if reg == 0x03:
            return bytes((0xC0 if self.regs[0x7D] & 0x06 == 0x06 else 0,))
        if reg == 0x0C:
            if self.gyro_mode == 'stuck':
                return bytes(12)
            return noise(12)
        return bytes(self.regs[reg:reg + n])

class FakeES8311:
    def __init__(self, mode='noise'):
        self.regs = bytearray(256)
        self.regs[0xFD] = 0x83
        self.mode = mode
        self.reads = 0          # chunks read since power-up
        self.log = []
    def write(self, reg, data):
        self.log.append((reg, data[0]))
        self.regs[reg] = data[0]
    def read(self, reg, n):
        return bytes(self.regs[reg:reg + n])
    def powered(self):
        return self.regs[0x00] == 0x80 and self.regs[0x0D] == 0x01

class FakeI2C:
    def __init__(self, devs):
        self.devs = devs
    def _dev(self, a):
        if a not in self.devs:
            raise OSError(19)       # ENODEV: nobody answers
        return self.devs[a]
    def writeto_mem(self, a, reg, data):
        self._dev(a).write(reg, data)
    def readfrom_mem(self, a, reg, n):
        return self._dev(a).read(reg, n)

CODEC = None
I2S_LOG = []
class FakeI2S:
    RX = 1
    STEREO = 1
    MONO = 0
    def __init__(self, id, sck=None, ws=None, sd=None, mode=None, bits=None,
                 format=None, rate=None, ibuf=None):
        I2S_LOG.append(dict(id=id, sck=sck, ws=ws, sd=sd, bits=bits, format=format,
                            rate=rate))
        self.open = True
    def readinto(self, buf):
        n = len(buf)
        if CODEC is not None and CODEC.powered():
            CODEC.reads += 1
        else:
            if CODEC is not None:
                CODEC.reads = 0
        if CODEC is None or not CODEC.powered() or CODEC.mode == 'silent' \
                or (CODEC.mode == 'late' and CODEC.reads <= 30):
            # 'late': the real ES8311 sends zeros for a while after power-up
            buf[:] = bytes(n)
        elif CODEC.mode == 'flat':
            buf[:] = b'\x10\x00\x00\x00' * (n // 4)
        else:
            # mic on the left slot, right slot silent (as on the ADV)
            r = noise(n // 2)
            for j in range(n // 4):
                buf[4 * j] = r[2 * j]
                buf[4 * j + 1] = r[2 * j + 1] & 0x03
                buf[4 * j + 2] = buf[4 * j + 3] = 0
        return n
    def deinit(self):
        self.open = False
        I2S_LOG.append('deinit')

class FakePin:
    IN = OUT = PULL_UP = 0
    def __init__(self, n, *a, **kw):
        self.n = n
    def __eq__(self, o):
        return self.n == (o.n if isinstance(o, FakePin) else o)

class FakeMachine:
    I2S = FakeI2S
    Pin = FakePin

sys.modules['machine'] = FakeMachine
sys.path.insert(0, 'hal/device')
import cp_sensors, cp_bmi270_cfg
sys.path.remove('hal/device')
import cp_board, cp_entropy, ckcc
import ngu

def setup(imu=None, mic=None, chip=None):
    # fresh cp_entropy state with the given fake hardware
    global CODEC
    devs = {}
    if imu:
        devs[0x68] = imu
    if mic:
        devs[0x18] = mic
    CODEC = mic
    bus = FakeI2C(devs)
    cp_board.entropy_sources = lambda: {'mic': cp_sensors.ES8311Mic(bus),
                                        'imu': cp_sensors.BMI270(bus)}
    cp_board.rng_bytes = chip or good_chip
    cp_entropy._sources = None
    cp_entropy._status = {}

def stat():
    return {lab: (ok, d) for lab, ok, d in cp_entropy.status()}

print('== config blob')
check('8192 bytes, sha256 as recorded', len(cp_bmi270_cfg.CONFIG) == 8192 and
      ngu.hash.sha256s(cp_bmi270_cfg.CONFIG) == __import__("ubinascii").unhexlify(cp_bmi270_cfg.SHA256))

print('== healthy sensors')
imu, mic = FakeBMI270(), FakeES8311()
setup(imu, mic)
a = cp_entropy.share(1, 32)
b = cp_entropy.share(2, 8)
s = stat()
check('SE1 share 32 bytes, SE2 share 8 bytes', len(a) == 32 and len(b) == 8)
check('chip RNG used', s['Chip RNG'][0] is True)
check('microphone used: %s' % s['Microphone'][1], s['Microphone'][0] is True)
check('motion sensor used: %s' % s['Motion sensor'][1], s['Motion sensor'][0] is True)
check('BMI270: one soft reset, config accepted (byte-exact upload)',
      imu.reset_count == 1 and imu.regs[0x21] == 1)
check('BMI270: advanced power save off before upload',
      [r for r, d in imu.log].index(0x7C) < [r for r, d in imu.log].index(0x5E))
check('BMI270: 1600 Hz, +-2 g, +-125 dps',
      (imu.regs[0x40], imu.regs[0x41], imu.regs[0x42], imu.regs[0x43]) == (0xAC, 0, 0xEC, 4))
check('BMI270: sensors switched off again after sampling', imu.regs[0x7D] == 0)
want_on = [(0x00, 0x80), (0x01, 0xBA), (0x02, 0x18), (0x0D, 0x01), (0x0E, 0x02),
           (0x14, 0x18), (0x17, 0xBF), (0x1C, 0x6A)]
check('ES8311: M5Unified power-up sequence (PGA +24 dB)', mic.log[:8] == want_on)
check('ES8311: powered down afterwards', mic.log[8:11] == [(0x0D, 0xFC), (0x0E, 0x6A), (0x00, 0x00)])
cfg = I2S_LOG[0]
check('I2S: pins 41/43/46, 16-bit stereo, 16 kHz',
      cfg['sck'] == 41 and cfg['ws'] == 43 and cfg['sd'] == 46 and cfg['bits'] == 16
      and cfg['format'] == FakeI2S.STEREO and cfg['rate'] == 16000)
check('I2S released afterwards', I2S_LOG[-1] == 'deinit')
c = cp_entropy.share(1, 32)
check('BMI270 started only once per power-up', (cp_entropy.share(2, 8), imu.reset_count)[1] == 1)
check('every share different', a != c)

print('== the sensors really are mixed in')
FIXED = bytes(range(32))
def fixed_chip(buf):
    fill(buf, FIXED)
setup(FakeBMI270(), FakeES8311(), chip=fixed_chip)
x1, x2 = cp_entropy.share(1, 32), cp_entropy.share(1, 32)
check('same chip bytes, different mic noise -> different share', x1 != x2)
chip_only = ngu.hash.sha256s(b'cardputer-se' + b'\x01' + FIXED)
check('share is not just the chip bytes', x1 != chip_only)

print('== sensors missing')
setup(None, None, chip=fixed_chip)
y = cp_entropy.share(1, 32)
s = stat()
check('still makes a share (never blocks a seed)', len(y) == 32)
check('without sensors = chip RNG only (today\'s behaviour)', y == chip_only)
check('microphone reported not found: %s' % s['Microphone'][1],
      s['Microphone'] == (False, 'not found'))
cp_entropy.share(2, 8)
check('motion sensor reported not found', stat()['Motion sensor'] == (False, 'not found'))

print('== microphone slow to start (zeros for ~0.5 s after power-up, as on the hardware)')
setup(FakeBMI270(), FakeES8311('late'))
cp_entropy.share(1, 32)
check('waits for the signal, then used: %s' % stat()['Microphone'][1], stat()['Microphone'][0] is True)

print('== sensors present but not noisy')
setup(FakeBMI270('stuck'), FakeES8311('flat'))
cp_entropy.share(1, 32); cp_entropy.share(2, 8)
s = stat()
check('flat microphone -> not used: %s' % s['Microphone'][1],
      s['Microphone'][0] is False and ('flat' in s['Microphone'][1] or 'silent' in s['Microphone'][1]))
check('stuck motion sensor -> not used: %s' % s['Motion sensor'][1],
      s['Motion sensor'][0] is False)
setup(FakeBMI270(), FakeES8311('silent'))
cp_entropy.share(1, 32)
check('silent microphone -> not used: %s' % stat()['Microphone'][1],
      stat()['Microphone'][0] is False)

print('== chip RNG is mandatory')
def dead_chip(buf):
    raise RuntimeError('entropy source off')
setup(FakeBMI270(), FakeES8311(), chip=dead_chip)
try:
    cp_entropy.share(1, 32)
    check('chip RNG off -> refuses', False)
except RuntimeError:
    check('chip RNG off -> refuses (no seed from sensors alone)', True)
setup(FakeBMI270(), FakeES8311(), chip=lambda b: fill(b, bytes(len(b))))
try:
    cp_entropy.share(2, 8)
    check('chip RNG all zeros -> refuses', False)
except RuntimeError:
    check('chip RNG all zeros -> refuses', True)

print('== desktop build: no sensors')
cp_board.entropy_sources = lambda: {}
cp_board.rng_bytes = good_chip
cp_entropy._sources = None
cp_entropy._status = {}
st = cp_entropy.test_all()
check('test_all() -> 3 rows, sensors "not on this build"',
      len(st) == 3 and st[1][1] is None and st[1][2] == 'not on this build')

print('== self-test readings (live loudness / turn rate)')
mic = FakeES8311()
setup(FakeBMI270(), mic)
m = cp_sensors.ES8311Mic(FakeI2C({0x18: mic}))
m.open()
lv = m.loudness()
m.close()
check('mic loudness from a noisy signal: %d' % lv, 0 < lv <= 32767)
check('mic released after the test', I2S_LOG[-1] == 'deinit' and mic.regs[0x00] == 0)
imu = FakeBMI270()
g = cp_sensors.BMI270(FakeI2C({0x68: imu}))
g.open()
tr = g.turn_rate()
g.close()
check('gyro turn rate in deg/s: %.1f' % tr, 0 <= tr <= 125.1)
check('gyro powered down after the test', imu.regs[0x7D] == 0)

print('== COLDCARD\'s callgate (ckcc.gate 26 -> callgate.read_rng)')
setup(FakeBMI270(), FakeES8311())
for src, n in ((1, 32), (2, 8)):
    buf = bytearray(33)
    rv = ckcc.gate(26, buf, src)
    check('read_rng(%d): rc 0, length byte %d' % (src, n), rv == 0 and buf[0] == n)
check('read_rng(3) -> ERANGE', ckcc.gate(26, bytearray(33), 3) == 34)

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
