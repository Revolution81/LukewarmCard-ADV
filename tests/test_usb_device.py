# test_usb_device.py - checks hal/device/cp_usb.py (the Cardputer's USB link)
# without hardware: MicroPython's USB stack above machine.USBDevice is plain
# Python (micropython-lib usb.device, shipped as hal/device/cp_usbcore.py and
# cp_usbhid.py), so a fake machine.USBDevice stands in for TinyUSB and this
# test plays the PC side. Uses the exact files frozen into the device.
#
# Run by tests/test_usb.sh:
#   CC_USB_PY=<coldcard shared/usb.py> build/host/cc-mpy -X heapsize=4m tests/test_usb_device.py
#
# Checks: device + configuration descriptors match a real COLDCARD (VID/PID,
# HID class, 64-byte interrupt IN and OUT endpoints, COLDCARD's report
# descriptor), packets flow both ways in order, back-pressure when the
# receive buffer is full, send() busy/None semantics, and that COLDCARD's
# receive loop (asyncio waiting on the port) wakes up when the PC sends.
import sys, os, struct

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

# ---- fake machine.USBDevice (what TinyUSB provides on the ESP32-S3) ----
class _Builtin:
    def __init__(self, desc_dev):
        self.desc_dev = desc_dev
        self.desc_cfg = b''
        self.itf_max = 0
        self.ep_max = 0
        self.str_max = 1

class FakeUSBDevice:
    # MicroPython's default device descriptor (VID 0x303a etc), overridden by config
    _DD = bytes([18, 1, 0x00, 0x02, 0xef, 2, 1, 64, 0x3a, 0x30, 0x05, 0x40,
                 0x00, 0x01, 1, 2, 3, 1])
    BUILTIN_NONE = _Builtin(_DD)
    BUILTIN_DEFAULT = _Builtin(_DD)

    def __init__(self):
        self._active = False
        self.pending = {}
        self.builtin_driver = self.BUILTIN_NONE

    def config(self, desc_dev, desc_cfg, strs, open_cb, reset_cb, ctrl_cb, xfer_cb):
        self.desc_dev, self.desc_cfg, self.strs = bytes(desc_dev), bytes(desc_cfg), strs
        self.open_cb, self.reset_cb, self.ctrl_cb, self.xfer_cb = open_cb, reset_cb, ctrl_cb, xfer_cb

    def active(self, *v):
        r = self._active
        if v:
            self._active = bool(v[0])
        return r

    def submit_xfer(self, ep, data):
        assert ep not in self.pending, 'double submit on %02x' % ep
        self.pending[ep] = data
        return True

class FakeMachine:
    USBDevice = FakeUSBDevice
    @staticmethod
    def idle():
        pass

sys.modules['machine'] = FakeMachine
sys.path.insert(0, 'hal/device')
import cp_usb, cp_usbcore, cp_usbhid     # the device's USB files, nothing else
sys.path.remove('hal/device')
from asyncio import core
import asyncio

print('== COLDCARD\'s own "usb" module still loads next to the USB code')
# regression: micropython-lib's "usb" package used to shadow COLDCARD's
# usb.py on the device ("no module named 'usb.enable_usb'" after login)
import usb
check('"usb" is COLDCARD\'s usb.py (has enable_usb)', hasattr(usb, 'enable_usb'))

# COLDCARD's real values, read from its usb.py
src = open(os.getenv('CC_USB_PY')).read()
blk = src[src.index('hid_descp = bytes(['):]
blk = blk[:blk.index('])') + 2]
blk = '\n'.join(ln.split('#')[0] for ln in blk.split('\n'))
HID_DESC = eval(blk.split('=', 1)[1].strip())
VID, PID = 0xd13e, 0xcc10
HID_INFO = (0x0, 0x0, 64, 5, HID_DESC)       # exactly what COLDCARD passes

print('== start, as COLDCARD calls it (pyb.usb_mode -> cp_usb.start)')
cp_usb.start(VID, PID, HID_INFO, 'C0FFEE000001', dev_build=False)
hw = cp_usbcore.get()._usbd
port = cp_usb.port()
check('USB activated', hw.active())
check('send() before the PC configures us -> None', port.send(bytes(64)) is None)

print('== device descriptor')
dd = hw.desc_dev
(bl, bt, bcd, cls, sub, proto, mps0, vid, pid, bcddev, im, ip, isn, ncfg) = \
    struct.unpack('<BBHBBBBHHHBBBB', dd)
check('VID d13e / PID cc10 (what Sparrow/HWI look for)', (vid, pid) == (VID, PID))
check('class defined at interface level', (cls, sub, proto) == (0, 0, 0))
check('one configuration', ncfg == 1)
check('manufacturer string', hw.strs[im] == 'LukewarmCard')
check('product string', hw.strs[ip] == 'LukewarmCard ADV')
check('serial number = chip id', hw.strs[isn] == 'C0FFEE000001')

print('== configuration descriptor')
cfg = hw.desc_cfg
total = struct.unpack_from('<H', cfg, 2)[0]
check('wTotalLength matches', total == len(cfg))
check('one interface', cfg[4] == 1)
off, itfs, eps, hids = 0, [], [], []
while off < len(cfg):
    l, t = cfg[off], cfg[off + 1]
    if t == 4:
        itfs.append(cfg[off:off + l])
    elif t == 5:
        eps.append(cfg[off:off + l])
    elif t == 0x21:
        hids.append(cfg[off:off + l])
    off += l
check('interface: HID class, 2 endpoints, no boot protocol',
      len(itfs) == 1 and itfs[0][4] == 2 and tuple(itfs[0][5:8]) == (3, 0, 0))
check('HID descriptor reports COLDCARD report-descriptor length (%d)' % len(HID_DESC),
      len(hids) == 1 and struct.unpack_from('<H', hids[0], 7)[0] == len(HID_DESC))
ep_info = sorted((e[2], e[3] & 3, struct.unpack_from('<H', e, 4)[0], e[6]) for e in eps)
check('endpoints: OUT 0x01 + IN 0x81, interrupt, 64 bytes, every 5 ms',
      ep_info == [(0x01, 3, 64, 5), (0x81, 3, 64, 5)])

print('== PC asks for the report descriptor')
req = struct.pack('<BBHHH', 0x81, 6, 0x2200, 0, len(HID_DESC))
rv = hw.ctrl_cb(1, req)     # stage SETUP
check('GET_DESCRIPTOR(Report) returns COLDCARD\'s descriptor exactly', bytes(rv) == HID_DESC)

print('== PC configures the device')
hw.open_cb(memoryview(cfg)[9:])
check('OUT endpoint armed for the first packet', 0x01 in hw.pending)

def pc_write(pkt):
    buf = hw.pending.pop(0x01)
    buf[:len(pkt)] = pkt
    hw.xfer_cb(0x01, 0, len(pkt))

def pc_read():
    data = bytes(hw.pending.pop(0x81))
    hw.xfer_cb(0x81, 0, len(data))
    return data

print('== PC -> device')
check('nothing readable yet', port.ioctl(3, 1) == 0)
for i in range(3):
    pc_write(bytes([i]) * 64)
check('readable after PC writes', port.ioctl(3, 1) == 1)
got = [port.recv(64, timeout=5000) for _ in range(3)]
check('3 packets received in order', got == [bytes([i]) * 64 for i in range(3)])
check('recv(timeout) with nothing waiting -> None', port.recv(64, timeout=20) is None)

print('== back-pressure: PC sends faster than COLDCARD reads')
for i in range(8):
    pc_write(bytes([0x40 + i]) * 64)
check('buffer full (8): OUT endpoint not re-armed', 0x01 not in hw.pending)
check('first buffered packet comes out first', port.recv(64, timeout=100) == bytes([0x40]) * 64)
check('slot freed: OUT endpoint re-armed', 0x01 in hw.pending)
rest = [port.recv(64, timeout=100) for _ in range(7)]
check('remaining 7 in order', rest == [bytes([0x41 + i]) * 64 for i in range(7)])

print('== device -> PC')
msg = bytes([0x85]) + b'okay' + bytes(59)
check('send() queues a report -> 64', port.send(msg) == 64)
check('second send() while PC hasn\'t read -> 0 (COLDCARD retries)', port.send(msg) == 0)
check('writable flag clear while busy', port.ioctl(3, 4) == 0)
check('PC reads the exact report', pc_read() == msg)
check('writable again', port.ioctl(3, 4) == 4)
check('short send() padded to 64 bytes', port.send(b'\x81x') == 2 and pc_read() == b'\x81x' + bytes(62))

print('== COLDCARD-style wait (asyncio queue_read on the port)')
woke = []
async def waiter():
    yield core._io_queue.queue_read(port)
    woke.append(port.recv(64, timeout=100))
async def pc_later():
    await asyncio.sleep_ms(150)
    pc_write(b'\x80' + b'ping' + bytes(59))
async def main():
    t = asyncio.create_task(waiter())
    await pc_later()
    for _ in range(20):
        if woke:
            break
        await asyncio.sleep_ms(10)
asyncio.run(main())
check('waiting task woke with the PC\'s packet', woke == [b'\x80' + b'ping' + bytes(59)])

print('== USB light (RGB LED): green while a computer has the link')
import cp_board
async def run_for(ms):
    await asyncio.sleep_ms(ms)
cp_board.USB_CONNECTED = True
asyncio.run(run_for(600))
check('connected -> LED green', cp_board.LED_LOG[-1] == cp_usb.LED_GREEN)
cp_board.USB_CONNECTED = False
asyncio.run(run_for(600))
check('cable pulled / host gone -> LED off', cp_board.LED_LOG[-1] == cp_usb.LED_OFF)
cp_board.led_hold(True)
cp_board.led(48, 48, 48)            # self-test lights it white
cp_board.USB_CONNECTED = True
asyncio.run(run_for(600))
check('self-test holding the LED: USB status leaves it alone',
      cp_board.LED_LOG[-1] == (48, 48, 48))
cp_board.led_hold(False)
asyncio.run(run_for(600))
check('after the self-test: green again', cp_board.LED_LOG[-1] == cp_usb.LED_GREEN)
cp_usb.stop()
asyncio.run(run_for(600))
check('USB switched off in COLDCARD -> LED off, watcher ends',
      cp_board.LED_LOG[-1] == cp_usb.LED_OFF and cp_usb._MON is None)
cp_usb.start(VID, PID, HID_INFO, 'C0FFEE000001', dev_build=False)
asyncio.run(run_for(600))
check('USB on again -> watcher back, green', cp_usb._MON is not None
      and cp_board.LED_LOG[-1] == cp_usb.LED_GREEN)
cp_board.USB_CONNECTED = False
asyncio.run(run_for(400))

print('== unplug / reset')
hw.pending.clear()          # TinyUSB cancels pending transfers on bus reset
hw.reset_cb()
check('send() after reset -> None', port.send(bytes(64)) is None)
hw.open_cb(memoryview(cfg)[9:])
check('re-enumerated: OUT armed again', 0x01 in hw.pending)

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
