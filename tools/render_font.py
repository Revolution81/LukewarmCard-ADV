#!/usr/bin/env python3
#
# Re-render COLDCARD Q's Iosevka font at Cardputer size (7x12 cells, so the
# Q's 34x10 character grid fits a 240x135 screen).
#
# Uses Coinkite's own misc/q1font/render.py, with its size constants and a few
# hand-tuned pixel offsets scaled down. Each substitution must match exactly,
# so an upstream change to render.py fails loudly here instead of silently.
#
# Usage: render_font.py <coldcard-repo> <output.py> [font_size]
#
import os, sys, shutil, tempfile, subprocess

cc, out = sys.argv[1], os.path.abspath(sys.argv[2])
font_size = int(sys.argv[3]) if len(sys.argv) > 3 else 12
src_dir = os.path.join(cc, 'misc', 'q1font')

SUBS = [
    ("FONT_SIZE = 18", f"FONT_SIZE = {font_size}"),
    ("CELL_SIZE = (9, 22)", "CELL_SIZE = (7, 12)"),
    ("keycap_font = ImageFont.truetype(FONT, FONT_SIZE-7)",
     "keycap_font = ImageFont.truetype(FONT, max(6, FONT_SIZE-5))"),
    # box-drawing chars: thinner lines, offsets scaled from 22px to 12px cell
    ("    lw = 2      # line width", "    lw = 1      # line width"),
    ("    mh1 = (h // 2) - lw + 3+4    # top", "    mh1 = (h // 2) + 2    # top"),
    ("    mh2 = (h // 2) - lw - 5    # bot", "    mh2 = (h // 2) - 4    # bot"),
    ("        draw.line( (mw-1, 0, mw-1, h), width=lw, fill=255)",
     "        draw.line( (mw, 0, mw, h), width=lw, fill=255)"),
    ("        draw.line( (mw+2, 0, mw+2, h), width=lw, fill=255)",
     "        draw.line( (mw+1, 0, mw+1, h), width=lw, fill=255)"),
    ("            this_y = -4", "            this_y = -2"),
    ("            this_y = 1          # perfect", "            this_y = 0"),
    # tab keycap art
    ("            draw.rectangle( ( 2,4, 2+2, CELL_H-7), 'white')",
     "            draw.rectangle( ( 1,2, 1+1, CELL_H-4), 'white')"),
    ("            draw.rectangle( ( 1,4, 1+1, CELL_H-7), 'black')", "            pass"),
    ("            draw.rounded_rectangle( ( 0,0, (CELL_W*2)-1, CELL_H-1), 4, outline='white')\n            #img.save('tab-key-framed.png')",
     "            draw.rounded_rectangle( ( 0,0, (CELL_W*2)-1, CELL_H-1), 2, outline='white')"),
    ("            this_y += 5\n", "            this_y += 1\n"),
    ("            draw.rounded_rectangle( ( 0,0, (CELL_W*2)-1, CELL_H-1), 4, outline='white')\n        else:",
     "            draw.rounded_rectangle( ( 0,0, (CELL_W*2)-1, CELL_H-1), 2, outline='white')\n        else:"),
    ("                x_shift += 1\n            elif ch == KEY_QR:\n                x_shift += 3\n            else:\n                x_shift += 3",
     "                x_shift += 0\n            elif ch == KEY_QR:\n                x_shift += 1\n            else:\n                x_shift += 1"),
]

with tempfile.TemporaryDirectory() as tmp:
    for fn in ['render.py', 'template.py', 'iosevka-extrabold.ttf']:
        shutil.copy(os.path.join(src_dir, fn), tmp)
    p = os.path.join(tmp, 'render.py')
    s = open(p).read()
    for old, new in SUBS:
        if s.count(old) != 1:
            sys.exit("render.py changed upstream; substitution not found once:\n  %r" % old)
        s = s.replace(old, new)
    open(p, 'w').write(s)

    r = subprocess.run([sys.executable, 'render.py'], cwd=tmp, capture_output=True, text=True)
    print(r.stdout[-600:])
    if r.returncode:
        sys.exit(r.stderr[-2000:])

    shutil.copy(os.path.join(tmp, 'font_iosevka.py'), out)
    shutil.copy(os.path.join(tmp, 'sample.png'), os.path.splitext(out)[0] + '-sample.png')
    print('wrote', out)
