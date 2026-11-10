# psram.py - Cardputer port: replacement for COLDCARD's 4MB PSRAM scratch area.
#
# COLDCARD stages PSBTs (in & out), backups and BBQr data in PSRAM. The
# Cardputer ADV has no PSRAM, so this keeps the same API but stores the data
# in a dedicated flash partition (cp_board.scratch_device()), with a one-sector
# write cache. Sizes are capped by features.MAX_TXN_LEN (inputs and outputs
# each), since whole PSBTs are also read into the small RAM heap at times.
#
import features

class _Writer:
    # what write_at() returns: callers do  PSRAM.write_at(off, n)[:] = data
    def __init__(self, ps, offset, ln):
        self.ps, self.offset, self.ln = ps, offset, ln

    def __setitem__(self, sl, data):
        start = 0 if sl.start is None else sl.start
        stop = self.ln if sl.stop is None else sl.stop
        data = memoryview(data)[0:stop-start]
        self.ps.write(self.offset + start, data)

    def __len__(self):
        return self.ln

class PSRAMWrapper:
    base = 0
    length = 4 * features.MAX_TXN_LEN

    def __init__(self):
        import cp_board
        self.psram_write_count = 0
        self.dev = cp_board.scratch_device()
        self.length = min(self.length, self.dev.size)
        self.sec = self.dev.sector_size
        self._cache_n = -1
        self._cache = bytearray(self.sec)
        self._dirty = False

    def _load(self, n):
        if n == self._cache_n:
            return
        self.flush()
        self.dev.read(n * self.sec, self._cache)
        self._cache_n = n

    def flush(self):
        if self._dirty:
            self.dev.write_sector(self._cache_n * self.sec, self._cache)
            self._dirty = False

    def read_at(self, offset, ln):
        assert 0 <= offset and offset + ln <= self.length, (offset, ln)
        out = bytearray(ln)
        pos = 0
        while pos < ln:
            a = offset + pos
            n, o = divmod(a, self.sec)
            take = min(self.sec - o, ln - pos)
            if n == self._cache_n:
                out[pos:pos+take] = self._cache[o:o+take]
            else:
                self.dev.read(a, memoryview(out)[pos:pos+take])
            pos += take
        return bytes(out)

    def write_at(self, offset, ln):
        assert offset % 4 == 0, offset
        assert ln % 4 == 0, ln
        assert offset + ln <= self.length, (offset+ln)
        self.psram_write_count += 1
        return _Writer(self, offset, ln)

    def read(self, address, buf, cmd=None):
        buf[:] = self.read_at(address, len(buf))

    def write(self, address, buf):
        assert address + len(buf) <= self.length, (address, len(buf))
        self.psram_write_count += 1
        pos = 0
        ln = len(buf)
        mv = memoryview(buf)
        while pos < ln:
            a = address + pos
            n, o = divmod(a, self.sec)
            take = min(self.sec - o, ln - pos)
            self._load(n)
            self._cache[o:o+take] = mv[pos:pos+take]
            self._dirty = True
            pos += take
        # (cached sector is flushed when another sector is touched; read_at
        # serves the cached sector from RAM, so readers always see new data)

    def is_busy(self):
        return False
    def wait_done(self):
        return
    def chip_erase(self):
        return
    def sector_erase(self, address):
        return
    def block_erase(self, address):
        return

    def wipe_all(self):
        from glob import dis
        self._cache_n = -1
        self._dirty = False
        for pos in range(0, self.length, self.sec):
            self.dev.erase_sector(pos)
            dis.progress_bar_show(pos / self.length)

# EOF
