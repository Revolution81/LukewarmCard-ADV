# uzlib.py - compatibility: MicroPython 1.21+ replaced uzlib with "deflate".
import deflate, io

def decompress(data, wbits=15, bufsize=0):
    if wbits < 0:
        fmt, w = deflate.RAW, -wbits
    elif wbits >= 25:
        fmt, w = deflate.GZIP, wbits - 16
    else:
        fmt, w = deflate.ZLIB, wbits
    with deflate.DeflateIO(io.BytesIO(data), fmt, w) as d:
        return d.read()

class DecompIO:
    def __init__(self, stream, wbits=15):
        fmt = deflate.RAW if wbits < 0 else deflate.ZLIB
        self._d = deflate.DeflateIO(stream, fmt, abs(wbits))
    def read(self, *a):
        return self._d.read(*a)
    def readinto(self, *a):
        return self._d.readinto(*a)
    def readline(self, *a):
        return self._d.readline(*a)

# EOF
