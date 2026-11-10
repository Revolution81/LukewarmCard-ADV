# cp_usb.py - Cardputer port, desktop test build: the COLDCARD USB link over
# a Unix datagram socket, the same transport as COLDCARD's own simulator
# (unix/variant/pyb.py). Each datagram is one 64-byte HID report.
#
# HWI and ckcc-protocol look for a COLDCARD simulator at
# /tmp/ckcc-simulator.sock, so with CP_USB_SOCK set to that path the desktop
# build can be driven by the real wallet tools (tests/test_usb_hwi.sh).
# Default path: <work folder>/usb.sock, so normal test runs don't clash.
#
import os, socket, struct, errno
import cp_board

_PORT = None


def _sock_path():
    return os.getenv('CP_USB_SOCK') or (cp_board.WORK + '/usb.sock')


class SimHID:
    def __init__(self):
        self.path = _sock_path()
        self.pipe = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        addr = struct.pack('H108s', socket.AF_UNIX, self.path.encode())
        try:
            os.remove(self.path)
        except OSError:
            pass
        self.pipe.bind(addr)
        self.last_from = None
        self.enabled = True
        print('[usb] listening on %s' % self.path)

    def recv(self, buf, timeout=0):
        maxlen = buf if isinstance(buf, int) else len(buf)
        self.pipe.setblocking(not timeout)
        try:
            msg, frm = self.pipe.recvfrom(maxlen)
        except OSError as exc:
            if exc.args[0] == errno.EAGAIN:
                return None if isinstance(buf, int) else 0
            raise
        self.last_from = frm
        if not self.enabled:
            return None if isinstance(buf, int) else 0
        if isinstance(buf, int):
            return msg
        buf[0:len(msg)] = msg
        return len(msg)

    def send(self, buf):
        if not self.enabled or self.last_from is None:
            return None
        try:
            return self.pipe.sendto(buf, self.last_from)
        except OSError as exc:
            if exc.args[0] == errno.ENOENT:
                return None         # client went away
            raise


def start(vid, pid, hid_info, serial, dev_build=False, msc=False):
    # (msc: no USB drive on the desktop build; the Virtual Disk image is
    # still used by the firmware, tests write into it directly)
    global _PORT
    if _PORT is None:
        _PORT = SimHID()
    _PORT.enabled = True
    print('[usb] on: %04x:%04x serial %s' % (vid, pid, serial))


def stop():
    if _PORT:
        _PORT.enabled = False
    print('[usb] off')


def port():
    return _PORT

# EOF
