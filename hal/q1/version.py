# version.py - Cardputer port: hardware description for COLDCARD's shared code.
#
# The Cardputer runs COLDCARD Q (Q1) firmware logic: QWERTY keyboard + colour
# LCD, so has_qwerty=True and hw_label='q1'. Q1 hardware the Cardputer lacks
# (QR scanner, NFC, second SD slot) is switched off here.
#
import features, cp_buildinfo
from public_constants import MAX_UPLOAD_LEN_MK4

MAX_TXN_LEN = features.MAX_TXN_LEN
MAX_UPLOAD_LEN = min(MAX_UPLOAD_LEN_MK4, 2 * MAX_TXN_LEN)

def decode_firmware_header(hdr):
    from sigheader import FWH_PY_FORMAT
    import ustruct
    magic_value, timestamp, version_string = ustruct.unpack_from(FWH_PY_FORMAT, hdr)[0:3]
    parts = ['%02x' % i for i in timestamp]
    date = '20' + '-'.join(parts[0:3])
    vers = bytes(version_string).rstrip(b'\0').decode()
    return date, vers, ''.join(parts[:-2])

def get_mpy_version():
    # (date, version label, timestamp digits)
    return cp_buildinfo.DATE, cp_buildinfo.VERSION, cp_buildinfo.TIMESTAMP

def get_fw_header():
    raise OSError('no fw header')

def get_header_value(fld_name):
    if fld_name == 'timestamp':
        import ubinascii
        return ubinascii.unhexlify(cp_buildinfo.TIMESTAMP + '0000')
    return 0

def get_is_devmode():
    return cp_buildinfo.IS_DEV

def is_fresh_version():
    return False

def serial_number():
    import cp_board
    return ''.join('%02X' % b for b in cp_board.chip_id())

def nfc_presence_check():
    return False

hw_label = 'q1'
has_608 = True              # emulated SE1 (secel_soft)
has_se2 = True              # emulated SE2 (trick PINs)
has_psram = True            # flash-backed, see psram.py
has_membrane = False
has_nfc = False             # TODO: M5Stack NFC Cap
has_qr = False              # no camera
num_sd_slots = 1
has_battery = True
has_qwerty = True
is_edge = False
supports_hsm = features.ALLOW_HSM
mk_num = 4
is_factory_mode = False
is_devmode = cp_buildinfo.IS_DEV

def probe_system():
    pass

# EOF
