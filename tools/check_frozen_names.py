#!/usr/bin/env python3
# Fail if a frozen package directory shares a name with a frozen module.
# (micropython-lib's "usb" package once shadowed COLDCARD's usb.py, which broke
# login on the device.) Run by tools/build_device.sh on frozen_content.c.
import re, sys
names = re.findall(r'"([^"\\]+)\\0"', open(sys.argv[1]).read())
mods = {n[:-3] for n in names if n.endswith('.py') and '/' not in n}
pkgs = {n.split('/')[0] for n in names if '/' in n}
clash = sorted(mods & pkgs)
if clash:
    sys.exit('frozen package shadows module: %s' % ', '.join(clash))
print('frozen names ok: %d modules, no package/module clashes' % len(names))
