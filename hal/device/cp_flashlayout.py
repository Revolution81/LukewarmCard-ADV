# cp_flashlayout.py - Cardputer port: flash layout for M5Launcher builds.
#
# Normal builds use three data partitions (ccse, ccscratch, vfs). M5Launcher
# (bmorcelli/Launcher) only carries over standard FAT/SPIFFS/LittleFS data
# partitions, by label, and may resize them. So Launcher builds keep all of the
# port's data inside one partition labelled "vfs", at FIXED offsets from its
# start, sized to fit the 448K partition Launcher creates for a new app
# (0x70000, its minimum; confirmed on a real Cardputer ADV):
#
#   0x000000  32K   soft-SE state (2 x 16K slots, raw flash, power-cut safe)
#   0x008000 256K   PSBT scratch area (PSRAM replacement, raw flash):
#                   PSBT in + PSBT out at features.MAX_TXN_LEN (128K) each;
#                   backups (max 128K) also stage here
#   0x048000 160K   COLDCARD /flash filesystem (littlefs: settings etc.)
#   0x070000  ...   unused (anything past this is left alone)
#
# A resize by Launcher only moves the END of the partition, so none of these
# regions move. Raw regions keep real erase semantics: erasing the SE slots
# really erases them (no copy-on-write leftovers, unlike storing them as files).
#
SECTOR = 4096

SE_OFF,  SE_LEN  = 0x000000, 0x008000
SCR_OFF, SCR_LEN = 0x008000, 0x040000
FS_OFF,  FS_LEN  = 0x048000, 0x028000
REQUIRED = FS_OFF + FS_LEN          # 0x070000 = 448K


class Window:
    # block device over part of a partition (same block protocol as
    # esp32.Partition: 4K blocks, extended readblocks/writeblocks, ioctl)
    def __init__(self, part, offset, length):
        assert offset % SECTOR == 0 and length % SECTOR == 0
        self.part = part
        self.first = offset // SECTOR
        self.count = length // SECTOR

    def _chk(self, block, nbytes, off):
        last = (off + nbytes - 1) // SECTOR if nbytes else 0
        if block < 0 or block + last >= self.count:
            raise OSError(22)       # EINVAL: outside this window

    def readblocks(self, block, buf, off=0):
        self._chk(block, len(buf), off)
        return self.part.readblocks(self.first + block, buf, off)

    def writeblocks(self, block, buf, off=None):
        self._chk(block, len(buf), off or 0)
        if off is None:
            # simple interface: erase then write whole blocks
            for i in range((len(buf) + SECTOR - 1) // SECTOR):
                self.part.ioctl(6, self.first + block + i)
            return self.part.writeblocks(self.first + block, buf)
        return self.part.writeblocks(self.first + block, buf, off)

    def ioctl(self, op, arg):
        if op == 4:                 # block count
            return self.count
        if op == 5:                 # block size
            return SECTOR
        if op == 6:                 # erase one block
            if not (0 <= arg < self.count):
                raise OSError(22)
            return self.part.ioctl(6, self.first + arg)
        return self.part.ioctl(op, arg)     # init / deinit / sync


def part_size(part):
    return part.ioctl(4, 0) * part.ioctl(5, 0)


class Layout:
    def __init__(self, part):
        size = part_size(part)
        if size < REQUIRED:
            raise OSError("'vfs' partition is %dK, needs %dK" % (size // 1024, REQUIRED // 1024))
        self.part = part
        self.size = size

    def se(self):
        return Window(self.part, SE_OFF, SE_LEN)

    def scratch(self):
        return Window(self.part, SCR_OFF, SCR_LEN)

    def fs(self):
        return Window(self.part, FS_OFF, FS_LEN)

# EOF
