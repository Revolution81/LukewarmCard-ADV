# test_launcher_layout.py - checks hal/device/cp_flashlayout.py (M5Launcher
# builds) against a fake esp32.Partition held in RAM.
#
#   build/host/cc-mpy -X heapsize=24m tests/test_launcher_layout.py
#
# Checks: the three regions never overlap and fit Launcher's 448K partition;
# littlefs works in its window and survives the scratch and SE regions being
# filled; a bigger partition (as after a resize by Launcher) still finds
# everything; a too-small one fails with a clear message; writes outside a
# window are refused; the fs holds a realistic number of settings files.
import sys, os
sys.path.insert(0, __file__.rsplit('/', 2)[0] + '/hal/device') if '/' in __file__ else None
sys.path.insert(0, 'hal/device')
import cp_flashlayout as L

FAILS = 0
def check(name, cond):
    global FAILS
    print('  ok  ' if cond else '  FAIL', name)
    if not cond:
        FAILS += 1


class FakePart:
    # same block protocol as esp32.Partition (4K blocks, NOR semantics:
    # erase -> 0xff, write can only clear bits)
    def __init__(self, size):
        self.mem = bytearray(b'\xff' * size)
        self.n = size // 4096
    def readblocks(self, b, buf, off=0):
        a = b * 4096 + off
        assert a + len(buf) <= len(self.mem)
        buf[:] = self.mem[a:a + len(buf)]
    def writeblocks(self, b, buf, off=0):
        a = b * 4096 + (off or 0)
        assert a + len(buf) <= len(self.mem)
        for i in range(len(buf)):
            self.mem[a + i] &= buf[i]
    def ioctl(self, op, arg):
        if op == 4: return self.n
        if op == 5: return 4096
        if op == 6:
            assert 0 <= arg < self.n
            self.mem[arg * 4096:(arg + 1) * 4096] = b'\xff' * 4096
            return 0
        return 0


print('== region layout')
check('SE, scratch, fs are contiguous and in order',
      L.SE_OFF == 0 and L.SE_OFF + L.SE_LEN == L.SCR_OFF and L.SCR_OFF + L.SCR_LEN == L.FS_OFF)
check('required size is 448K (what Launcher creates)', L.REQUIRED == 448 * 1024)
check('scratch holds PSBT in + out at 128K each', L.SCR_LEN >= 2 * 128 * 1024)
check('scratch holds a 128K backup', L.SCR_LEN >= 128 * 1024)

print('== too-small partition')
try:
    L.Layout(FakePart(384 * 1024))
    check('384K vfs rejected', False)
except OSError as e:
    check('384K vfs rejected with a clear message: %s' % e, 'needs 448K' in str(e))

print('== filesystem in its window')
part = FakePart(448 * 1024)              # exactly what Launcher made on the device
lay = L.Layout(part)
fs = lay.fs()
check('fs window is 160K', fs.ioctl(4, 0) * fs.ioctl(5, 0) == L.FS_LEN)
os.VfsLfs2.mkfs(fs, progsize=256)
os.mount(os.VfsLfs2(fs, progsize=256), '/lt')
os.mkdir('/lt/settings')
with open('/lt/settings/a.json', 'w') as f:
    f.write('{"chain":"BTC","words":12}' * 20)
os.umount('/lt')

print('== fill SE and scratch regions completely')
se = lay.se()
for i in range(se.ioctl(4, 0)):
    se.ioctl(6, i)
    se.writeblocks(i, bytes([0xA5]) * 4096, 0)
scr = lay.scratch()
for i in range(scr.ioctl(4, 0)):
    scr.ioctl(6, i)
    scr.writeblocks(i, bytes([i & 0xff]) * 4096, 0)

os.mount(os.VfsLfs2(fs, progsize=256), '/lt')
with open('/lt/settings/a.json') as f:
    check('fs file intact after SE+scratch filled', f.read() == '{"chain":"BTC","words":12}' * 20)
os.umount('/lt')
buf = bytearray(4096)
se.readblocks(7, buf, 0)
check('SE region intact after fs use', buf == bytes([0xA5]) * 4096)
last = scr.ioctl(4, 0) - 1
scr.readblocks(last, buf, 0)
check("scratch region intact (last block)", buf == bytes([last & 0xff]) * 4096)
check('nothing written past the fs window',
      part.mem[L.REQUIRED:] == b'\xff' * (len(part.mem) - L.REQUIRED))

print('== bounds')
for name, dev, blk in (('SE', se, se.ioctl(4, 0)), ('scratch', scr, scr.ioctl(4, 0)), ('fs', fs, fs.ioctl(4, 0))):
    try:
        dev.writeblocks(blk, b'x' * 16, 0)
        check('%s refuses write past its end' % name, False)
    except OSError:
        check('%s refuses write past its end' % name, True)
try:
    se.readblocks(7, bytearray(8), 4092)        # straddles the end of block 7
    check('SE refuses read straddling its end', False)
except OSError:
    check('SE refuses read straddling its end', True)

print('== Launcher resized the partition bigger (copied as-is)')
big = FakePart(0x200000)
big.mem[:len(part.mem)] = part.mem
lay2 = L.Layout(big)
os.mount(os.VfsLfs2(lay2.fs(), progsize=256), '/lt')
with open('/lt/settings/a.json') as f:
    check('fs still mounts and reads after resize to 2M', f.read().startswith('{"chain"'))
os.umount('/lt')
lay2.se().readblocks(0, buf, 0)
check('SE data still at the same place after resize', buf == bytes([0xA5]) * 4096)

print('== soft-SE slot format on the SE window (same format as cp_board.SEStore)')
# same slot format as hal/device/cp_board.SEStore; exercised through the window
import ngu
class SEStore:
    SLOT = 16 * 1024
    def __init__(self, dev): self.p = dev
    def save(self, seq, data):
        hdr = b'CPS1' + seq.to_bytes(4, 'little') + len(data).to_bytes(4, 'little')
        blob = hdr + data + bytes(ngu.hash.sha256s(hdr + data))
        blob += b'\xff' * (-len(blob) % 4096)
        base = (seq % 2) * self.SLOT // 4096
        for i in range(self.SLOT // 4096):
            self.p.ioctl(6, base + i)
        self.p.writeblocks(base, blob, 0)
    def read(self, n):
        hdr = bytearray(12)
        self.p.readblocks(n * self.SLOT // 4096, hdr, 0)
        ln = int.from_bytes(hdr[8:12], 'little')
        body = bytearray(ln + 32)
        self.p.readblocks(n * self.SLOT // 4096, body, 12)
        return bytes(hdr[:4]), int.from_bytes(hdr[4:8], 'little'), \
            bytes(ngu.hash.sha256s(hdr + body[:ln])) == bytes(body[ln:]), bytes(body[:ln])
st = SEStore(lay.se())
st.save(1, b'seed-record-1' * 100)
st.save(2, b'seed-record-2' * 600)        # bigger than one 4K block
m, s1, ok1, d1 = st.read(1)
m0, s2, ok2, d2 = st.read(0)
check('slot 1 = seq 1, hash ok', m == b'CPS1' and s1 == 1 and ok1 and d1 == b'seed-record-1' * 100)
check('slot 0 = seq 2, hash ok', m0 == b'CPS1' and s2 == 2 and ok2 and d2 == b'seed-record-2' * 600)
os.mount(os.VfsLfs2(fs, progsize=256), '/lt')
check('fs unaffected by SE writes', open('/lt/settings/a.json').read().startswith('{"chain"'))
os.umount('/lt')

print('== settings capacity (160K littlefs)')
# COLDCARD writes each settings record as a ~4K file in /flash/settings and
# deletes the old one after saving; allow plenty of extras
os.mount(os.VfsLfs2(fs, progsize=256), '/lt')
n = 0
try:
    for n in range(1, 41):
        with open('/lt/settings/s%02d.aes' % n, 'wb') as f:
            f.write(bytes(4096))
except OSError:
    n -= 1
check('fits at least 20 settings files (fits %d)' % n, n >= 20)
for i in range(1, n + 1):
    os.remove('/lt/settings/s%02d.aes' % i)
os.umount('/lt')

print('\n%d failure(s)' % FAILS)
sys.exit(1 if FAILS else 0)
