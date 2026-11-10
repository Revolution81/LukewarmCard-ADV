# test_usb_msc.py - the Virtual Disk's USB drive (hal/device/cp_usbmsc.py)
# against a fake USB controller, playing the computer's side of USB Mass
# Storage (Bulk-Only Transport + SCSI) the way Windows/macOS/Linux do.
# Uses the exact device files. Run by tests/test_usb.sh:
#   CC_USB_PY=<coldcard shared/usb.py> build/host/cc-mpy -X heapsize=4m tests/test_usb_msc.py
import sys, os, struct

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1

class _Builtin:
    def __init__(self):
        self.desc_dev = bytes([18, 1, 0, 2, 0xef, 2, 1, 64, 0x3a, 0x30, 5, 0x40, 0, 1, 1, 2, 3, 1])
        self.desc_cfg = b''
        self.itf_max = self.ep_max = 0
        self.str_max = 1

class FakeUSBDevice:
    BUILTIN_NONE = _Builtin()
    BUILTIN_DEFAULT = _Builtin()
    def __init__(self):
        self._active = False
        self.pending = {}
        self.stalled = set()
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
    def stall(self, ep, *v):
        if v:
            (self.stalled.add if v[0] else self.stalled.discard)(ep)
        return ep in self.stalled

class FakeMachine:
    USBDevice = FakeUSBDevice
    @staticmethod
    def idle():
        pass

sys.modules['machine'] = FakeMachine
sys.path.insert(0, 'hal/device')
import cp_usb, cp_usbcore, cp_usbmsc
sys.path.remove('hal/device')
import cp_vdisk

class RamDisk:
    # stands in for cp_vdisk.DISK (the SD-card image): same host_* calls
    def __init__(self, blocks=8192):
        self.data = bytearray(blocks * 512)
        self.n = blocks
        self.inserted = False
        self.attention = False
        self.writes = 0
        self.syncs = 0
    def ioctl(self, op, arg):
        return self.n if op == 4 else 512
    def host_ready(self):
        return self.inserted
    def host_read(self, lba, buf):
        buf[:] = self.data[lba * 512:lba * 512 + len(buf)]
    def host_write(self, lba, buf):
        self.data[lba * 512:lba * 512 + len(buf)] = buf
        self.writes += 1
    def host_sync(self):
        self.syncs += 1
    def take_attention(self):
        a = self.attention
        self.attention = False
        return a

disk = RamDisk()
cp_vdisk.DISK = disk

src = open(os.getenv('CC_USB_PY')).read()
blk = src[src.index('hid_descp = bytes(['):]
blk = blk[:blk.index('])') + 2]
blk = '\n'.join(ln.split('#')[0] for ln in blk.split('\n'))
HID_DESC = eval(blk.split('=', 1)[1].strip())

print("== COLDCARD's usb_mode('MSC+HID', ...) -> HID + mass storage")
cp_usb.start(0xd13e, 0xcc10, (0, 0, 64, 5, HID_DESC), 'C0FFEE000001', msc=True)
hw = cp_usbcore.get()._usbd
cfg = hw.desc_cfg
itfs, eps = [], []
off = 0
while off < len(cfg):
    l, t = cfg[off], cfg[off + 1]
    if t == 4:
        itfs.append(bytes(cfg[off:off + l]))
    elif t == 5:
        eps.append(bytes(cfg[off:off + l]))
    off += l
check('two interfaces', cfg[4] == 2 and len(itfs) == 2)
check('interface 0 = COLDCARD HID (wallet software unchanged)', itfs[0][5:8] == b'\x03\x00\x00')
check('interface 1 = mass storage, SCSI, bulk-only', itfs[1][5:8] == b'\x08\x06\x50')
bulk = sorted((e[2], e[3] & 3, struct.unpack_from('<H', e, 4)[0]) for e in eps if e[3] & 3 == 2)
check('bulk IN 0x82 + OUT 0x02, 64 bytes', bulk == [(0x02, 2, 64), (0x82, 2, 64)])

# the host sets the configuration: TinyUSB calls open once per interface,
# with that interface's part of the descriptor
starts = []
off = 9
while off < len(cfg):
    if cfg[off + 1] == 4:
        starts.append(off)
    off += cfg[off]
starts.append(len(cfg))
for a, b in zip(starts, starts[1:]):
    hw.open_cb(memoryview(cfg)[a:b])
EP_IN, EP_OUT = 0x82, 0x02
check('waiting for a command', EP_OUT in hw.pending)

print('== GET MAX LUN (class request)')
r = hw.ctrl_cb(1, struct.pack('<BBHHH', 0xA1, 0xFE, 0, 1, 1))
check('one drive (LUN 0)', bytes(r) == b'\x00')

TAG = [0]
def scsi(cdb, length=0, data_in=True, out_data=None):
    # one command: CBW -> data -> CSW. Returns (data, status, residue)
    TAG[0] += 1
    cbw = struct.pack('<4sIIBBB', b'USBC', TAG[0], length, 0x80 if data_in else 0, 0, len(cdb)) \
        + cdb + bytes(16 - len(cdb))
    buf = hw.pending.pop(EP_OUT)
    buf[:31] = cbw
    hw.xfer_cb(EP_OUT, 0, 31)
    got = b''
    sent = 0
    for _ in range(10000):
        if EP_IN in hw.pending:
            b = bytes(hw.pending.pop(EP_IN))
            if len(b) == 13 and b[:4] == b'USBS':
                sig, tag, res, st = struct.unpack('<4sIIB', b)
                assert tag == TAG[0], 'tag'
                hw.xfer_cb(EP_IN, 0, 13)
                return got, st, res
            got += b
            hw.xfer_cb(EP_IN, 0, len(b))
        elif EP_OUT in hw.pending and not data_in and sent < length:
            b = hw.pending.pop(EP_OUT)
            k = min(len(b), length - sent)
            b[:k] = out_data[sent:sent + k]
            sent += k
            hw.xfer_cb(EP_OUT, 0, k)
        else:
            raise AssertionError('stuck')
    raise AssertionError('no CSW')

def sense():
    d, st, _ = scsi(b'\x03\x00\x00\x00\x12\x00', 18)
    return d[2] & 0xF, d[12]

print('== Virtual Disk off: drive with no medium')
d, st, _ = scsi(b'\x12\x00\x00\x00\x24\x00', 36)
check('INQUIRY: removable, names itself', st == 0 and d[1] & 0x80 and d[8:16] == b'Lukewarm')
d, st, _ = scsi(b'\x00' * 6)
check('TEST UNIT READY fails', st == 1)
check('REQUEST SENSE: not ready, medium not present', sense() == (0x02, 0x3A))
d, st, res = scsi(b'\x25' + bytes(9), 8)
check('READ CAPACITY fails, host gets padding + full residue', st == 1 and len(d) == 8 and res == 8)

print('== Virtual Disk on')
disk.inserted = True
disk.attention = True
d, st, _ = scsi(b'\x00' * 6)
check('first command: "medium changed" (host re-reads the drive)',
      st == 1 and sense() == (0x06, 0x28))
d, st, _ = scsi(b'\x00' * 6)
check('then ready', st == 0)
d, st, _ = scsi(b'\x25' + bytes(9), 8)
check('READ CAPACITY: 8192 x 512 = 4MB', st == 0 and struct.unpack('>II', d) == (8191, 512))
d, st, _ = scsi(b'\x23' + bytes(6) + b'\x00\x0c\x00', 12)
check('READ FORMAT CAPACITIES', st == 0 and struct.unpack_from('>I', d, 4)[0] == 8192)
d, st, _ = scsi(b'\x1a\x00\x3f\x00\x04\x00', 4)
check('MODE SENSE(6): not write-protected', st == 0 and d[2] & 0x80 == 0)

print('== write and read back (like copying a PSBT onto the drive)')
payload = bytes((i * 7 + 3) & 0xFF for i in range(512 * 20))       # 20 blocks, > one 4K chunk
cdb = struct.pack('>BBIBHB', 0x2A, 0, 1000, 0, 20, 0)
d, st, res = scsi(cdb, len(payload), data_in=False, out_data=payload)
check('WRITE(10) 20 blocks @1000: ok', st == 0 and res == 0)
check('landed on the disk', disk.data[1000 * 512:1020 * 512] == payload)
cdb = struct.pack('>BBIBHB', 0x28, 0, 1000, 0, 20, 0)
d, st, res = scsi(cdb, len(payload))
check('READ(10) gives it back', st == 0 and d == payload and res == 0)
d, st, _ = scsi(b'\x35' + bytes(9))
check('SYNCHRONIZE CACHE flushes', st == 0 and disk.syncs == 1)

print('== mistakes the host might make')
cdb = struct.pack('>BBIBHB', 0x28, 0, 8190, 0, 5, 0)
d, st, res = scsi(cdb, 5 * 512)
check('read past the end: fails, ILLEGAL REQUEST', st == 1 and sense() == (0x05, 0x21))
d, st, res = scsi(b'\x9e\x10' + bytes(14), 32)
check('unknown command (READ CAPACITY 16): fails, padded', st == 1 and len(d) == 32
      and sense() == (0x05, 0x20))
d, st, res = scsi(b'\xaa' + bytes(11), 1024, data_in=False, out_data=bytes(1024))
check('unknown write-type command: data drained, fails', st == 1)
d, st, _ = scsi(b'\x00' * 6)
check('still in step afterwards', st == 0)

print('== host ejects the drive')
d, st, _ = scsi(b'\x1b\x00\x00\x00\x02\x00')
check('START STOP UNIT (eject): ok, flushed', st == 0 and disk.syncs == 2)

print('== Virtual Disk switched off while plugged in')
disk.inserted = False
d, st, _ = scsi(b'\x00' * 6)
check('medium gone', st == 1 and sense() == (0x02, 0x3A))

print('== BOT reset (class request) recovers')
hw.ctrl_cb(1, struct.pack('<BBHHH', 0x21, 0xFF, 0, 1, 0))
hw.ctrl_cb(3, struct.pack('<BBHHH', 0x21, 0xFF, 0, 1, 0))
d, st, _ = scsi(b'\x12\x00\x00\x00\x24\x00', 36)
check('next command works', EP_OUT in hw.pending and st == 0 and len(d) == 36)

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
