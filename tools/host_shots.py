#!/usr/bin/env python3
# Convert desktop-test screenshots (raw big-endian RGB565, 240x135) to PNG.
# Usage: host_shots.py <shots-dir> [scale]   -> writes <name>.png next to each
import os, sys, struct
from PIL import Image

W, H = 240, 135
d = sys.argv[1]
scale = int(sys.argv[2]) if len(sys.argv) > 2 else 3

for fn in sorted(os.listdir(d)):
    if not fn.endswith('.rgb565'):
        continue
    raw = open(os.path.join(d, fn), 'rb').read()
    img = Image.new('RGB', (W, H))
    px = img.load()
    for i in range(W * H):
        v = struct.unpack_from('>H', raw, i * 2)[0]
        r = ((v >> 11) & 0x1f) * 255 // 31
        g = ((v >> 5) & 0x3f) * 255 // 63
        b = (v & 0x1f) * 255 // 31
        px[i % W, i // W] = (r, g, b)
    if scale > 1:
        img = img.resize((W * scale, H * scale), Image.NEAREST)
    out = os.path.join(d, fn[:-7] + '.png')
    img.save(out)
    print(out)
