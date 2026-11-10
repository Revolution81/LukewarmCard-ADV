# cp_usb.py - Cardputer port: the COLDCARD USB link on the ESP32-S3.
#
# A real COLDCARD is a USB HID device, VID 0xd13e / PID 0xcc10, with 64-byte
# interrupt IN and OUT endpoints and the report descriptor in COLDCARD's
# usb.py. Wallet software (Sparrow, Electrum, HWI, ckcc) finds it by those
# IDs and speaks COLDCARD's framed protocol over 64-byte reports.
#
# This module builds that same device with MicroPython's runtime USB support
# (machine.USBDevice + micropython-lib's usb.device, vendored as cp_usbcore /
# cp_usbhid) on the S3's native USB
# port. COLDCARD's own usb.py then runs unmodified on top of it: it calls
# pyb.usb_mode(...) to switch USB on (-> start()), and uses pyb.USB_HID()
# (-> port()) with recv(), send() and asyncio polling.
#
# Note: MicroPython normally starts USB after boot.py returns, which never
# happens in this firmware (COLDCARD runs inside _boot.py). Activating the
# runtime device here also starts TinyUSB, so nothing appears on the USB bus
# until COLDCARD enables USB (Settings > Hardware On/Off > USB Port).
#
# The RGB LED shows the link like the Mk4/Mk5's USB light: green while a
# computer has the device set up (checked every 250 ms, while USB is enabled).
#
import io, time
import cp_usbcore               # micropython-lib usb.device.core, renamed (no clash
from cp_usbhid import HIDInterface   # with COLDCARD's own usb.py)

_EP_IN_FLAG = 0x80
_RX_SLOTS = 8                   # 64-byte packets buffered from the host
_POLLIN, _POLLOUT = 0x01, 0x04
_STREAM_POLL = 3
_STREAM_CLOSE = 4
_EINVAL = 22


class _ColdcardHID(HIDInterface):
    # HID interface shaped like the real COLDCARD's: one IN and one OUT
    # interrupt endpoint, 64 bytes each.

    def __init__(self, report_desc, max_pkt, interval_ms):
        super().__init__(report_desc, interval_ms=interval_ms)
        self.max_pkt = max_pkt
        self.rx = [bytearray(max_pkt) for _ in range(_RX_SLOTS)]
        self.rx_len = [0] * _RX_SLOTS
        self.rx_head = 0        # next slot the host writes into
        self.rx_tail = 0        # next slot COLDCARD reads
        self.rx_count = 0
        self.rx_armed = False
        self.tx = bytearray(max_pkt)
        self.ep_in = None
        self.ep_out = None

    def desc_cfg(self, desc, itf_num, ep_num, strs):
        desc.interface(itf_num, 2, 0x03, 0x00, 0x00, 0)     # HID, 2 endpoints
        self.get_hid_descriptor(desc)
        self.ep_in = ep_num | _EP_IN_FLAG
        self.ep_out = ep_num
        self._int_ep = self.ep_in                           # used by HIDInterface.busy()
        desc.endpoint(self.ep_in, "interrupt", self.max_pkt, self.interval_ms)
        desc.endpoint(self.ep_out, "interrupt", self.max_pkt, self.interval_ms)
        self.idle_rate = 0
        self.protocol = 1

    def num_eps(self):
        return 1                # EP n IN + EP n OUT share one number

    def on_open(self):
        super().on_open()
        self.rx_head = self.rx_tail = self.rx_count = 0
        self.rx_armed = False
        self._arm()

    def on_reset(self):
        super().on_reset()
        self.rx_armed = False

    # ---- host -> device ----
    def _arm(self):
        # start a read into the next free slot (only one OUT transfer at a time)
        if self.rx_armed or not self.is_open() or self.rx_count >= _RX_SLOTS:
            return
        self.rx_armed = True
        try:
            self.submit_xfer(self.ep_out, self.rx[self.rx_head], self._rx_done)
        except RuntimeError:
            self.rx_armed = False

    def _rx_done(self, ep, result, nbytes):
        self.rx_armed = False
        if result == 0 and nbytes:          # XFER_SUCCESS
            self.rx_len[self.rx_head] = nbytes
            self.rx_head = (self.rx_head + 1) % _RX_SLOTS
            self.rx_count += 1
        self._arm()

    def take(self):
        # oldest buffered packet as bytes, or None
        if not self.rx_count:
            return None
        i = self.rx_tail
        pkt = bytes(self.rx[i][:self.rx_len[i]])
        self.rx_tail = (i + 1) % _RX_SLOTS
        self.rx_count -= 1
        self._arm()             # a slot is free again
        return pkt

    # ---- device -> host ----
    def can_send(self):
        return self.is_open() and not self.xfer_pending(self.ep_in)

    def put(self, buf):
        # queue one IN report; caller checked can_send()
        n = len(buf)
        self.tx[:n] = buf
        if n < self.max_pkt:
            self.tx[n:] = bytes(self.max_pkt - n)
        self.submit_xfer(self.ep_in, self.tx)


class HIDPort(io.IOBase):
    # What COLDCARD's usb.py gets from pyb.USB_HID(): the same methods as
    # the STM32 port's pyb.USB_HID, and pollable by asyncio.

    def __init__(self, itf):
        self.itf = itf

    def recv(self, buf, timeout=0):
        # recv(64, timeout=ms) -> bytes or None; recv(bytearray) -> count
        deadline = time.ticks_add(time.ticks_ms(), timeout)
        while True:
            pkt = self.itf.take()
            if pkt is not None:
                break
            if not timeout or time.ticks_diff(deadline, time.ticks_ms()) <= 0:
                return None if isinstance(buf, int) else 0
            time.sleep_ms(1)        # lets the USB task run
        if isinstance(buf, int):
            return pkt
        n = min(len(buf), len(pkt))
        buf[:n] = pkt[:n]
        return n

    def send(self, buf):
        # -> 64 when queued, 0 if the previous report hasn't gone yet
        # (COLDCARD retries), None if the host isn't connected
        if not self.itf.is_open():
            return None
        if not self.itf.can_send():
            return 0
        self.itf.put(buf)
        return len(buf)

    def ioctl(self, req, arg):
        if req == _STREAM_POLL:
            ret = 0
            if (arg & _POLLIN) and self.itf.rx_count:
                ret |= _POLLIN
            if (arg & _POLLOUT) and self.itf.can_send():
                ret |= _POLLOUT
            return ret
        if req == _STREAM_CLOSE:
            return 0
        # anything else (e.g. "file descriptor?") is unsupported. Must be an
        # error, not 0: 0 would claim to be fd 0 (stdin) to select.poll.
        return -_EINVAL


_ITF = None
_PORT = None
_ON = False
_MON = None

LED_GREEN = (0, 40, 0)
LED_OFF = (0, 0, 0)

def _show_link():
    import cp_board
    if cp_board.led_held():
        return                  # self-test is using the LED
    c = LED_GREEN if (_ON and cp_board.usb_connected()) else LED_OFF
    cp_board.led(*c)

async def _monitor():
    global _MON
    import asyncio
    try:
        while _ON:
            try:
                _show_link()
            except Exception as exc:
                print('usb led: %r' % exc)
            await asyncio.sleep_ms(250)
    finally:
        _MON = None
        try:
            _show_link()        # off
        except Exception:
            pass


_MSC = None

def start(vid, pid, hid_info, serial, dev_build=False, msc=False):
    # hid_info = (subclass, protocol, max packet, poll interval ms, report desc),
    # exactly what COLDCARD passes to pyb.usb_mode()
    global _ITF, _PORT, _ON, _MON, _MSC
    _sub, _proto, max_pkt, interval, report_desc = hid_info
    if _ITF is None:
        _ITF = _ColdcardHID(report_desc, max_pkt, interval)
        _PORT = HIDPort(_ITF)
    itfs = [_ITF]
    if msc:
        # COLDCARD asks for 'MSC+HID': the Virtual Disk drive (shows "no
        # medium" until Virtual Disk is switched on, like the Mk4/Mk5)
        if _MSC is None:
            import cp_usbmsc, cp_vdisk
            _MSC = cp_usbmsc.MSCInterface(cp_vdisk.DISK)
        itfs.append(_MSC)
    cp_usbcore.get().init(
        *itfs,
        builtin_driver=bool(dev_build),     # dev builds keep the USB serial REPL
        id_vendor=vid,
        id_product=pid,
        manufacturer_str='LukewarmCard',
        product_str='LukewarmCard ADV',
        serial_str=serial,
    )
    _ON = True
    if _MON is None:
        import asyncio
        _MON = asyncio.create_task(_monitor())


def stop():
    global _ON
    _ON = False                 # monitor turns the LED off and ends
    try:
        cp_usbcore.get().active(False)
    except Exception:
        pass


def port():
    return _PORT

# EOF
