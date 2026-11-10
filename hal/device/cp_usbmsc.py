# cp_usbmsc.py - Cardputer port: USB mass-storage interface for COLDCARD's
# Virtual Disk (the disk itself is cp_vdisk.py, an image on the SD card).
#
# Standard USB Mass Storage, Bulk-Only Transport with SCSI commands, which
# Windows, macOS and Linux all drive with their built-in drivers:
#
#   computer -> 31-byte Command Block Wrapper (CBW) on bulk OUT
#            <-> optional data (bulk IN for reads, bulk OUT for writes)
#   device   -> 13-byte Command Status Wrapper (CSW) on bulk IN
#
# Built on micropython-lib's runtime USB (cp_usbcore.Interface), next to the
# COLDCARD HID interface in cp_usb.py. Full-speed USB: 64-byte packets, but
# each transfer moves up to 4K at once.
#
# Commands: TEST UNIT READY, REQUEST SENSE, INQUIRY, MODE SENSE(6/10),
# START STOP UNIT, PREVENT/ALLOW MEDIUM REMOVAL, READ FORMAT CAPACITIES,
# READ CAPACITY(10), READ(10), WRITE(10), VERIFY(10), SYNCHRONIZE CACHE.
# Anything else fails with ILLEGAL REQUEST (data padded / drained, never a
# stall, so every host recovers the same way).
#
# "No medium" until Virtual Disk is on (disk.host_ready()), and a "medium
# changed" notice when it comes back, so the computer re-reads the drive.
import struct
from cp_usbcore import Interface

_EP_IN_FLAG = 0x80
_MPS = 64
_CHUNK = 4096                   # bytes per data transfer (8 blocks)
_BLOCK = 512

# class requests
_REQ_GET_MAX_LUN = 0xFE
_REQ_BOT_RESET = 0xFF

# sense keys / codes
_NO_SENSE = (0, 0, 0)
_NOT_READY_NO_MEDIUM = (0x02, 0x3A, 0x00)
_UNIT_ATTENTION_CHANGED = (0x06, 0x28, 0x00)
_ILLEGAL_OPCODE = (0x05, 0x20, 0x00)
_ILLEGAL_LBA = (0x05, 0x21, 0x00)
_MEDIUM_ERROR = (0x03, 0x11, 0x00)
_WRITE_ERROR = (0x03, 0x0C, 0x00)

_ST_CBW, _ST_DATA_IN, _ST_DATA_OUT, _ST_CSW = range(4)


class MSCInterface(Interface):
    def __init__(self, disk, vendor=b'Lukewarm', product=b'LukewarmCard ADV'):
        super().__init__()
        self.disk = disk
        self.vendor = vendor
        self.product = product
        self.ep_in = self.ep_out = None
        self.cbw = bytearray(_MPS)
        self.buf = bytearray(_CHUNK)
        self.csw = bytearray(13)
        self.sense = _NO_SENSE
        self._reset_state()

    def _reset_state(self):
        self.state = _ST_CBW
        self.tag = 0
        self.expect = 0             # dCBWDataTransferLength
        self.done = 0               # data bytes moved so far
        self.status = 0
        self.lba = 0
        self.blocks = 0
        self.zero = False           # sending padding instead of disk data
        self.discard = False        # draining OUT data we won't keep

    # ---- descriptors ----
    def desc_cfg(self, desc, itf_num, ep_num, strs):
        desc.interface(itf_num, 2, 0x08, 0x06, 0x50)   # MSC, SCSI, bulk-only
        self.ep_in = ep_num | _EP_IN_FLAG
        self.ep_out = ep_num
        desc.endpoint(self.ep_in, "bulk", _MPS, 0)
        desc.endpoint(self.ep_out, "bulk", _MPS, 0)

    def num_eps(self):
        return 1

    def on_open(self):
        super().on_open()
        self._reset_state()
        self._rx_cbw()

    def on_reset(self):
        super().on_reset()
        self._reset_state()

    def on_interface_control_xfer(self, stage, request):
        bmRequestType, bRequest = request[0], request[1]
        if (bmRequestType & 0x60) != 0x20:      # class requests only
            return False
        if bRequest == _REQ_GET_MAX_LUN:
            return b'\x00' if stage == 1 else True
        if bRequest == _REQ_BOT_RESET:
            if stage == 1:
                self._reset_state()
            elif stage == 3:
                self._rx_cbw()
            return True
        return False

    # ---- transfers ----
    def _rx_cbw(self):
        self.state = _ST_CBW
        if self.is_open() and not self.xfer_pending(self.ep_out):
            self.submit_xfer(self.ep_out, self.cbw, self._got_cbw)

    def _got_cbw(self, ep, result, n):
        if result != 0:
            return
        c = self.cbw
        if n != 31 or c[0:4] != b'USBC':
            self._rx_cbw()                       # not a command: wait for one
            return
        self.tag = struct.unpack_from('<I', c, 4)[0]
        self.expect = struct.unpack_from('<I', c, 8)[0]
        self.data_in = bool(c[12] & 0x80)
        self.done = 0
        self.status = 0
        self.zero = self.discard = False
        cb = bytes(c[15:15 + (c[14] & 0x1F)])
        try:
            self._command(cb)
        except Exception as exc:
            print('msc: %r' % exc)
            self._fail(_MEDIUM_ERROR)

    def _command(self, cb):
        op = cb[0]
        d = self.disk

        if op == 0x12:                                  # INQUIRY
            r = bytearray(36)
            r[1] = 0x80                                 # removable
            r[2] = 0x04
            r[3] = 0x02
            r[4] = 31
            r[8:16] = self.vendor
            r[16:32] = self.product
            r[32:36] = b'1.00'
            return self._reply(r)

        if op == 0x03:                                  # REQUEST SENSE
            k, asc, ascq = self.sense
            self.sense = _NO_SENSE
            r = bytearray(18)
            r[0] = 0x70
            r[2] = k
            r[7] = 10
            r[12] = asc
            r[13] = ascq
            return self._reply(r)

        # everything else needs the medium
        if not d.host_ready():
            return self._fail(_NOT_READY_NO_MEDIUM)
        if d.take_attention():
            # first command after the medium (re)appeared: "medium changed",
            # so the computer drops its cached copy and re-reads the drive
            return self._fail(_UNIT_ATTENTION_CHANGED)

        if op == 0x00 or op == 0x1E or op == 0x2F:      # TUR, PREVENT/ALLOW, VERIFY
            return self._finish()
        if op == 0x1B:                                  # START STOP UNIT
            if (cb[4] & 3) == 2:                        # eject: host is done
                d.host_sync()
            return self._finish()
        if op == 0x35:                                  # SYNCHRONIZE CACHE
            d.host_sync()
            return self._finish()

        n = d.ioctl(4, 0)
        if op == 0x25:                                  # READ CAPACITY(10)
            return self._reply(struct.pack('>II', n - 1, _BLOCK))
        if op == 0x23:                                  # READ FORMAT CAPACITIES
            return self._reply(struct.pack('>4sIB3s', b'\x00\x00\x00\x08', n, 0x02,
                                           _BLOCK.to_bytes(3, 'big')))
        if op == 0x1A:                                  # MODE SENSE(6)
            return self._reply(b'\x03\x00\x00\x00')
        if op == 0x5A:                                  # MODE SENSE(10)
            return self._reply(b'\x00\x06\x00\x00\x00\x00\x00\x00')

        if op == 0x28 or op == 0x2A:                    # READ(10) / WRITE(10)
            lba, cnt = struct.unpack_from('>IxH', cb, 2)
            if lba + cnt > n:
                return self._fail(_ILLEGAL_LBA)
            self.lba, self.blocks = lba, cnt
            if op == 0x28:
                self.state = _ST_DATA_IN
                return self._tx_more()
            self.state = _ST_DATA_OUT
            return self._rx_more()

        return self._fail(_ILLEGAL_OPCODE)

    def _reply(self, data):
        # short data-in reply (fits one transfer)
        n = min(len(data), self.expect)
        self.buf[:n] = data[:n]
        self.done = n
        if n:
            self.submit_xfer(self.ep_in, memoryview(self.buf)[:n], self._sent_reply)
        else:
            self._send_csw()

    def _sent_reply(self, ep, result, n):
        self._send_csw()

    def _fail(self, sense):
        # command failed: remember why, move/drain the data the host expects,
        # then report failure
        self.sense = sense
        self.status = 1
        if self.expect and self.done < self.expect:
            if self.data_in:
                self.zero = True
                self.state = _ST_DATA_IN
                return self._tx_more()
            self.discard = True
            self.state = _ST_DATA_OUT
            return self._rx_more()
        self._send_csw()

    def _finish(self):
        self._send_csw()

    # data in (READ(10), or padding)
    def _tx_more(self):
        left = self.expect - self.done
        if self.zero:
            if left <= 0:
                return self._send_csw()
            k = min(left, _CHUNK)
            mv = memoryview(self.buf)[:k]
            for i in range(k):
                mv[i] = 0
            self.submit_xfer(self.ep_in, mv, self._sent_data)
            return
        if not self.blocks:
            # host asked for more than the command covers: pad
            if left > 0:
                self.zero = True
                return self._tx_more()
            return self._send_csw()
        k = min(self.blocks, _CHUNK // _BLOCK)
        mv = memoryview(self.buf)[:k * _BLOCK]
        try:
            self.disk.host_read(self.lba, mv)
        except Exception:
            self.blocks = 0
            return self._fail(_MEDIUM_ERROR)
        self.lba += k
        self.blocks -= k
        self.submit_xfer(self.ep_in, mv, self._sent_data)

    def _sent_data(self, ep, result, n):
        self.done += n
        if result != 0:
            return
        self._tx_more()

    # data out (WRITE(10), or draining)
    def _rx_more(self):
        left = self.expect - self.done
        if self.discard:
            if left <= 0:
                return self._send_csw()
            k = min(left, _CHUNK)
        else:
            if not self.blocks or left <= 0:
                return self._send_csw()
            k = min(self.blocks, _CHUNK // _BLOCK) * _BLOCK
        self.rx_len = k
        self.submit_xfer(self.ep_out, memoryview(self.buf)[:k], self._got_data)

    def _got_data(self, ep, result, n):
        if result != 0:
            return
        self.done += n
        if not self.discard:
            k = n // _BLOCK
            if k:
                try:
                    self.disk.host_write(self.lba, memoryview(self.buf)[:k * _BLOCK])
                except Exception:
                    self.blocks = 0
                    return self._fail(_WRITE_ERROR)
                self.lba += k
                self.blocks -= k
            if n < self.rx_len:                 # short packet: host stopped early
                self.blocks = 0
        self._rx_more()

    # status
    def _send_csw(self):
        self.state = _ST_CSW
        residue = max(0, self.expect - self.done)
        if self.zero or self.discard:
            residue = self.expect           # nothing useful was moved
        struct.pack_into('<4sIIB', self.csw, 0, b'USBS', self.tag, residue, self.status)
        self.submit_xfer(self.ep_in, self.csw, self._sent_csw)

    def _sent_csw(self, ep, result, n):
        self._rx_cbw()

# EOF
