#!/usr/bin/env python3
# make_mockups.py - put desktop-test screenshots onto a photo of a Cardputer
# ADV, for the README / release page.
#
#   tools/make_mockups.py <photo> <x0,y0,x1,y1> <out dir> <shot.png>...
#
# <x0,y0,x1,y1>: the screen's black area in the photo (pixels). The photo is
# upscaled 3x, the area is blacked out (rounded corners) and each 240x135
# screenshot is scaled into it, centred, with the LCD's aspect ratio.
# Also writes gallery.jpg: all mockups in a grid.
import sys, os
from PIL import Image, ImageDraw

photo, rect, out = sys.argv[1], sys.argv[2], sys.argv[3]
shots = sys.argv[4:]
S = 3
x0, y0, x1, y1 = [int(v) * S for v in rect.split(',')]
os.makedirs(out, exist_ok=True)

base = Image.open(photo).convert('RGB')
base = base.resize((base.width * S, base.height * S), Image.LANCZOS)

made = []
for shot in shots:
    im = base.copy()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((x0, y0, x1, y1), radius=5 * S, fill=(0, 0, 0))
    sc = Image.open(shot).convert('RGB')
    # pixel-perfect upscale first, then smooth to the final size
    sc = sc.resize((sc.width * 4, sc.height * 4), Image.NEAREST)
    w = (x1 - x0) - 2 * S
    h = round(w * 135 / 240)
    if h > (y1 - y0) - 2 * S:
        h = (y1 - y0) - 2 * S
        w = round(h * 240 / 135)
    sc = sc.resize((w, h), Image.LANCZOS)
    im.paste(sc, (x0 + ((x1 - x0) - w) // 2, y0 + ((y1 - y0) - h) // 2))
    name = os.path.splitext(os.path.basename(shot))[0]
    fn = os.path.join(out, 'lukewarmcard-adv-' + name.split('_', 1)[-1] + '.jpg')
    im.save(fn, quality=88, optimize=True)
    made.append(im)
    print(fn)

# gallery: 2 columns, scaled down
cols = 2
tw = base.width // 2
th = base.height // 2
rows = (len(made) + cols - 1) // cols
pad = 24
g = Image.new('RGB', (cols * tw + (cols + 1) * pad, rows * th + (rows + 1) * pad), (255, 255, 255))
for i, im in enumerate(made):
    g.paste(im.resize((tw, th), Image.LANCZOS),
            (pad + (i % cols) * (tw + pad), pad + (i // cols) * (th + pad)))
g.save(os.path.join(out, 'gallery.jpg'), quality=88, optimize=True)
print(os.path.join(out, 'gallery.jpg'))
