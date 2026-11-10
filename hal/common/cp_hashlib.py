# cp_hashlib.py - Cardputer port: sha256 with MicroPython 1.13 semantics.
#
# COLDCARD calls sha256().digest() more than once (e.g. the USB upload
# checksum: read by the 'sha2' command and again when signing). Mainline
# MicroPython 1.29's hashlib raises "hash is final" on the second call.
# libngu's sha256 (added by this port, cmodules/libngu-src/ngu/hash.c)
# leaves the state alone in digest(). tools/assemble.py rewrites COLDCARD's
# "from uhashlib import sha256" to import from here.
import ngu
sha256 = ngu.hash.sha256

# EOF
