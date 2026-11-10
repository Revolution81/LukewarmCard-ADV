# cp_sensors.py - Cardputer ADV: the microphone and the motion sensor, used
# only as extra noise sources for COLDCARD's random numbers (cp_entropy.py).
#
# A real COLDCARD Mk4/Mk5/Q mixes in random bytes from its two secure-element
# chips (SE1, SE2) every time it makes a seed. The Cardputer has no such
# chips, so these two sensors take their places:
#
#   SE1 share (32 bytes) <- microphone: ES8311 codec ADC, analog MEMS mic,
#                          read over I2S (BCLK 41, WS 43, DIN 46), 16 kHz
#   SE2 share (8 bytes)  <- motion sensor: Bosch BMI270 accelerometer + gyro,
#                          I2C address 0x68, 1600 Hz, most sensitive ranges
#
# Both sit on the I2C bus the keyboard uses (SDA 8, SCL 9). Register values
# for the ES8311 come from M5Stack's M5Unified (Cardputer ADV microphone
# callback); the BMI270 start-up sequence follows Bosch's BMI270_SensorAPI.
#
# Each source's collect(update) feeds raw samples to update() and returns a
# short health verdict. Nothing here decides how the bytes are used: the
# chip's own random generator is always mixed in as well (cp_entropy.py).
import utime

# ---- health checks (shared by both sources) ----

class Unhealthy(Exception):
    # source answered, but its numbers don't look like noise
    pass

def check_noise(vals, min_distinct, max_run):
    # vals: sequence of ints. Enough different values, and no long stretch of
    # the same value (a stuck or disconnected input repeats itself).
    seen = set()
    run = best = 1
    prev = None
    for v in vals:
        seen.add(v)
        if v == prev:
            run += 1
            if run > best:
                best = run
        else:
            run = 1
        prev = v
    if len(seen) < min_distinct:
        raise Unhealthy('flat (%d values)' % len(seen))
    if best > max_run:
        raise Unhealthy('stuck (%d repeats)' % best)
    return len(seen)


# ---- Bosch BMI270 ----

_CHIP_ID = 0x00
_STATUS = 0x03
_DATA_ACC = 0x0C            # acc x,y,z then gyr x,y,z: 12 bytes, little-endian
_INTERNAL_STATUS = 0x21
_ACC_CONF = 0x40
_ACC_RANGE = 0x41
_GYR_CONF = 0x42
_GYR_RANGE = 0x43
_INIT_CTRL = 0x59
_INIT_ADDR_0 = 0x5B
_INIT_DATA = 0x5E
_PWR_CONF = 0x7C
_PWR_CTRL = 0x7D
_CMD = 0x7E

class BMI270:
    name = 'Motion sensor'
    FRAMES = 64             # 64 x 12 bytes, ~40 ms at 1600 Hz

    def __init__(self, i2c, addrs=(0x68, 0x69)):
        self.i2c = i2c
        self.addrs = addrs
        self.addr = None

    def _w(self, reg, val):
        self.i2c.writeto_mem(self.addr, reg, bytes((val,)))

    def _r(self, reg, n=1):
        return self.i2c.readfrom_mem(self.addr, reg, n)

    def _find(self):
        for a in self.addrs:
            try:
                if self.i2c.readfrom_mem(a, _CHIP_ID, 1)[0] == 0x24:
                    return a
            except OSError:
                pass
        raise OSError('not found')

    def _start(self):
        # Bosch's bmi270_init(): soft reset, upload the 8K configuration in
        # chunks, check the sensor accepted it.
        from cp_bmi270_cfg import CONFIG
        self.addr = self._find()
        self._w(_CMD, 0xB6)                     # soft reset
        utime.sleep_ms(2)
        try:
            self._r(_CHIP_ID)                   # dummy read after reset
        except OSError:
            pass
        self._w(_PWR_CONF, 0x00)                # advanced power save off
        utime.sleep_us(450)
        self._w(_INIT_CTRL, 0x00)
        step = 64                               # must be even
        for i in range(0, len(CONFIG), step):
            w = i // 2                          # address is in 16-bit words
            self.i2c.writeto_mem(self.addr, _INIT_ADDR_0, bytes((w & 0x0F, w >> 4)))
            self.i2c.writeto_mem(self.addr, _INIT_DATA, CONFIG[i:i + step])
        self._w(_INIT_CTRL, 0x01)
        utime.sleep_ms(20)
        st = self._r(_INTERNAL_STATUS)[0] & 0x0F
        if st != 1:
            raise OSError('init failed (%d)' % st)
        # 1600 Hz, high-performance filters, smallest ranges (most noise per bit)
        self._w(_ACC_CONF, 0xAC)
        self._w(_ACC_RANGE, 0x00)               # +-2 g
        self._w(_GYR_CONF, 0xEC)
        self._w(_GYR_RANGE, 0x04)               # +-125 deg/s
        self._w(_PWR_CTRL, 0x00)                # sensors off until needed

    # ---- streaming (self-test) ----
    def open(self):
        if self.addr is None:
            self._start()
        self._w(_PWR_CTRL, 0x0E)                # acc + gyro + temperature on
        utime.sleep_ms(50)                      # gyro start-up time

    def close(self):
        try:
            self._w(_PWR_CTRL, 0x00)
        except OSError:
            pass

    def frame(self, timeout_ms=500):
        # next 12-byte reading (acc x,y,z, gyr x,y,z), waiting for fresh data
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms)
        while not (self._r(_STATUS)[0] & 0x40):         # gyro data ready
            if utime.ticks_diff(deadline, utime.ticks_ms()) < 0:
                raise OSError('no data')
            utime.sleep_us(200)
        return self._r(_DATA_ACC, 12)

    def turn_rate(self):
        # fastest rotation on any axis right now, degrees per second
        # (+-125 deg/s range: 262.1 counts per deg/s)
        d = self.frame()
        m = 0
        for k in (6, 8, 10):
            v = d[k] | (d[k + 1] << 8)
            v = v - 65536 if v & 0x8000 else v
            m = max(m, abs(v))
        return m / 262.1

    # ---- entropy ----
    def collect(self, update):
        self.open()
        try:
            gx = []
            frames = []
            while len(gx) < self.FRAMES:
                d = self.frame()
                update(d)
                gx.append(d[6] | (d[7] << 8))
                frames.append(bytes(d))
        finally:
            self.close()
        check_noise(frames, 8, 4)               # whole readings keep changing
        n = check_noise(gx, 3, 16)              # and the gyro's low bits move
        return 'OK (%d gyro levels)' % n


# ---- ES8311 codec + microphone ----

_ES_ON = (
    (0x00, 0x80),           # chip state machine on
    (0x01, 0xBA),           # clocks from BCLK (no MCLK wire)
    (0x02, 0x18),           # pre-multiplier x8: 16 kHz * 32 bits * 8 = 256 fs
    (0x0D, 0x01),           # analog power up
    (0x0E, 0x02),           # PGA + ADC modulator on
    (0x14, 0x18),           # input Mic1p-Mic1n, PGA +24 dB (M5Unified: 0 dB)
    (0x17, 0xBF),           # ADC volume 0 dB
    (0x1C, 0x6A),           # equaliser bypass, remove DC offset
)
_ES_OFF = ((0x0D, 0xFC), (0x0E, 0x6A), (0x00, 0x00))

class ES8311Mic:
    name = 'Microphone'
    ADDR = 0x18
    RATE = 16000
    SETTLE = 2400           # frames always thrown away at start-up (150 ms)
    MAX_SETTLE_MS = 1500    # ...then wait up to this long for a live signal
    FRAMES = 2048           # frames used (128 ms)
    CHUNK = 1024            # bytes per I2S read (256 stereo frames)

    def __init__(self, i2c):
        self.i2c = i2c

    def _regs(self, seq):
        for reg, val in seq:
            self.i2c.writeto_mem(self.ADDR, reg, bytes((val,)))

    # ---- streaming (self-test) ----
    def open(self):
        from machine import I2S, Pin
        try:
            self.i2c.readfrom_mem(self.ADDR, 0xFD, 1)    # chip id register
        except OSError:
            raise OSError('not found')
        # clocks first: the codec runs from BCLK
        self.i2s = I2S(0, sck=Pin(41), ws=Pin(43), sd=Pin(46), mode=I2S.RX,
                       bits=16, format=I2S.STEREO, rate=self.RATE, ibuf=8192)
        self.buf = bytearray(self.CHUNK)
        try:
            self._regs(_ES_ON)
            self.settle_ms = self._settle()
        except Exception:
            self.close()
            raise

    def close(self):
        if getattr(self, 'i2s', None) is None:
            return
        try:
            self._regs(_ES_OFF)
        except OSError:
            pass
        self.i2s.deinit()
        self.i2s = None

    def _settle(self):
        # The codec's ADC outputs zeros for a while after power-up (start-up
        # ramp + DC filter), longer than a fixed delay covers. Throw away
        # SETTLE frames, then keep reading until the signal moves (or give up
        # after MAX_SETTLE_MS; collect() then reports it). -> ms waited
        t0 = utime.ticks_ms()
        n = 0
        while True:
            mv = self.read()
            n += len(mv)
            waited = utime.ticks_diff(utime.ticks_ms(), t0)
            if n >= self.SETTLE * 4 and (_varies(mv) or waited > self.MAX_SETTLE_MS):
                return waited

    def read(self):
        # next chunk of 16-bit stereo samples (little-endian L, R, L, R...)
        got = self.i2s.readinto(self.buf)
        return memoryview(self.buf)[:got]

    def loudness(self):
        # half the peak-to-peak swing of the next chunk, 0..32767, on the
        # louder channel (the mic is on one of them)
        mv = self.read()
        lo = [32767, 32767]
        hi = [-32768, -32768]
        for j in range(0, len(mv) - 1, 2):
            v = mv[j] | (mv[j + 1] << 8)
            v = v - 65536 if v & 0x8000 else v
            c = (j >> 1) & 1
            if v < lo[c]:
                lo[c] = v
            if v > hi[c]:
                hi[c] = v
        return max(hi[0] - lo[0], hi[1] - lo[1]) // 2

    # ---- entropy ----
    def collect(self, update):
        self.open()
        left, right = _NoiseStats(), _NoiseStats()
        try:
            n = 0
            while n < self.FRAMES * 4:
                mv = self.read()
                got = len(mv)
                if not got:
                    continue
                update(mv)
                for j in range(0, got - 3, 4):
                    left.add(mv[j] | (mv[j + 1] << 8))
                    right.add(mv[j + 2] | (mv[j + 3] << 8))
                n += got
        finally:
            self.close()
        # the mic is on one channel; the other may be silent or a copy
        best = max(left, right, key=lambda c: c.distinct())
        if best.distinct() < 8:
            if best.distinct() == 1:
                raise Unhealthy('silent (all %d), waited %d ms' % (best.last, self.settle_ms))
            raise Unhealthy('flat (%d values)' % best.distinct())
        if best.longest > 64:
            raise Unhealthy('stuck (%d repeats)' % best.longest)
        return 'OK (%d+ levels)' % best.distinct()


def _varies(mv):
    # any change among the first 64 samples of a chunk (either channel)
    n = min(len(mv), 256) & ~1
    if n < 4:
        return False
    first = (mv[0], mv[1], mv[2], mv[3])
    for j in range(4, n - 3, 4):
        if (mv[j], mv[j + 1], mv[j + 2], mv[j + 3]) != first:
            return True
    return False


class _NoiseStats:
    # distinct values (counted up to 64) and longest run, without storing samples
    def __init__(self):
        self.seen = set()
        self.last = None
        self.run = 0
        self.longest = 0

    def add(self, v):
        if len(self.seen) < 64:
            self.seen.add(v)
        if v == self.last:
            self.run += 1
            if self.run > self.longest:
                self.longest = self.run
        else:
            self.run = 1
            self.last = v

    def distinct(self):
        return len(self.seen)

# EOF
