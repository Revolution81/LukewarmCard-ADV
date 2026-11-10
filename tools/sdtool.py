# sdtool.py - run with the desktop-test cc-mpy to manage the emulated SD card.
#   cc-mpy sdtool.py <sdcard.img> ls [folder]
#   cc-mpy sdtool.py <sdcard.img> put <local-file> <name-on-card>   (folders created)
#   cc-mpy sdtool.py <sdcard.img> get <name-on-card> <local-file>
#   cc-mpy sdtool.py <sdcard.img> rm <file-or-folder>                (folders: with contents)
import os, sys

class BD:
    def __init__(self, fn):
        self.f = open(fn, 'r+b')
        self.f.seek(0, 2)
        self.n = self.f.tell() // 512
    def readblocks(self, n, buf):
        self.f.seek(n * 512)
        self.f.readinto(buf)
    def writeblocks(self, n, buf):
        self.f.seek(n * 512)
        self.f.write(buf)
        self.f.flush()
    def ioctl(self, op, arg):
        return self.n if op == 4 else 512 if op == 5 else 0

img, cmd = sys.argv[1], sys.argv[2]
try:
    os.stat(img)
except OSError:
    # create a 64MB card image, FAT formatted (same as cp_board host)
    with open(img, 'wb') as f:
        f.seek(64 * 2048 * 512 - 1)
        f.write(b'\0')
    os.VfsFat.mkfs(BD(img))
os.mount(os.VfsFat(BD(img)), '/sdx')
if cmd == 'ls':
    d = '/sdx/' + (sys.argv[3].strip('/') if len(sys.argv) > 3 else '')
    for fn in os.listdir(d):
        st = os.stat(d.rstrip('/') + '/' + fn)
        print(fn + ('/' if st[0] & 0x4000 else ''), st[6])
elif cmd == 'put':
    with open(sys.argv[3], 'rb') as f:
        data = f.read()
    parts = sys.argv[4].split('/')[:-1]
    for i in range(len(parts)):
        try:
            os.mkdir('/sdx/' + '/'.join(parts[:i + 1]))
        except OSError:
            pass
    with open('/sdx/' + sys.argv[4], 'wb') as f:
        f.write(data)
    print('put', len(data))
elif cmd == 'get':
    with open('/sdx/' + sys.argv[3], 'rb') as f:
        data = f.read()
    with open(sys.argv[4], 'wb') as f:
        f.write(data)
    print('got', len(data))
elif cmd == 'rm':
    def rm(p):
        if os.stat(p)[0] & 0x4000:
            for fn in os.listdir(p):
                rm(p + '/' + fn)
            os.rmdir(p)
        else:
            os.remove(p)
    rm('/sdx/' + sys.argv[3].strip('/'))
    print('removed', sys.argv[3])
os.umount('/sdx')
