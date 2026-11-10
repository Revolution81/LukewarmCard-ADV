#!/usr/bin/env python3
# make_collage.py - 2x2 collage of 240x135 screenshots (pixel-sharp, 3x),
# for the README.
#   tools/make_collage.py <out.jpg|png> <shot1.png> <shot2.png> <shot3.png> <shot4.png>
import sys
from PIL import Image, ImageDraw

out, shots = sys.argv[1], sys.argv[2:6]
S, PAD, R = 3, 36, 18
W, H = 240 * S, 135 * S
g = Image.new('RGB', (2 * W + 3 * PAD, 2 * H + 3 * PAD), (236, 236, 236))
for i, fn in enumerate(shots):
    x = PAD + (i % 2) * (W + PAD)
    y = PAD + (i // 2) * (H + PAD)
    im = Image.open(fn).convert('RGB').resize((W, H), Image.NEAREST)
    mask = Image.new('L', (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, W - 1, H - 1), radius=R, fill=255)
    g.paste(im, (x, y), mask)
g.save(out, quality=90, optimize=True)
print(out)
