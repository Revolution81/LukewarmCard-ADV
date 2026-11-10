# pyb.py - Cardputer port: the bits of the STM32 "pyb" module COLDCARD uses.
import cp_board

_umode = None
_UNSET = object()

def usb_mode(nm=_UNSET, vid=None, pid=None, hid=None, **kws):
    # COLDCARD's usb.py: usb_mode('MSC+HID', vid=, pid=, hid=(...)) switches
    # USB on, usb_mode(None) off, usb_mode() reads the current mode.
    # HID (wallet software) + MSC (Virtual Disk, cp_vdisk.py / cp_usbmsc.py)
    # via cp_usb.py on the device; a simulator socket on the desktop build.
    global _umode
    if nm is not _UNSET:
        import cp_usb
        if nm:
            if 'HID' not in nm or hid is None:
                raise ValueError('only COLDCARD HID mode is supported')
            import version
            cp_usb.start(vid, pid, hid, version.serial_number(),
                         dev_build=cp_board.IS_DEV, msc=('MSC' in nm))
        else:
            cp_usb.stop()
        _umode = nm
    return _umode

def hid_keyboard(*a, **k):
    return None

class USB_VCP:
    @staticmethod
    def isconnected():
        return False
    @staticmethod
    def any():
        return False

def USB_HID():
    # the one HID port (cp_usb.HIDPort on the device, SimHID on desktop)
    import cp_usb
    p = cp_usb.port()
    if p is None:
        raise OSError('USB not enabled')
    return p

class _SDBlock:
    # COLDCARD calls pyb.SDCard() then os.mount(sd, '/sd').
    # Wraps the board's microSD block device, created lazily.
    _dev = None

    def __init__(self):
        pass

    def _bd(self):
        if _SDBlock._dev is None:
            _SDBlock._dev = cp_board.sd_block_device()
        return _SDBlock._dev

    def power(self, st=0):
        if not st:
            cp_board.sd_release()
            _SDBlock._dev = None
        return False

    def present(self):
        return True

    def info(self):
        bd = self._bd()
        n = bd.ioctl(4, 0)
        return (n * 512, 512, 0, b'', b'')

    # block device protocol, so os.mount(SDCard(), ...) works
    def readblocks(self, *a):
        return self._bd().readblocks(*a)
    def writeblocks(self, *a):
        return self._bd().writeblocks(*a)
    def ioctl(self, op, arg):
        return self._bd().ioctl(op, arg)

def SDCard():
    # Whole card, or (features.SD_SUBDIR set, e.g. the Mk5 build) one folder
    # of it served as the card's root: see cp_sdsub.py
    import features
    import cp_sdsub
    return cp_sdsub.SubdirVfs(_SDBlock(), getattr(features, 'SD_SUBDIR', None) or '')

class ExtInt:
    IRQ_RISING = 1
    IRQ_FALLING = 2
    IRQ_RISING_FALLING = 3
    def __init__(self, *a, **kw):
        pass

class Timer:
    def __init__(self, *a, **k):
        pass
    def init(self, **k):
        pass
    def deinit(self):
        pass

class LED:
    def __init__(self, n):
        self.n = n
    def on(self):
        cp_board.backlight(255)
    def off(self):
        cp_board.backlight(0)
    def intensity(self, v=None):
        if v is not None:
            cp_board.backlight(v)

class Flash:
    # COLDCARD's /flash filesystem: the board mounts it before main starts
    def __init__(self, *a, **k):
        raise OSError(19)

# EOF
