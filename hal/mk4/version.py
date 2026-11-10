# version.py - Cardputer port, Mk4/Mk5 variant: hardware description for
# COLDCARD's shared code.
#
# This build runs the COLDCARD Mk4/Mk5 code path: numeric keypad UI and the
# 128x64 OLED display code (display.py, ux_mk4.py, mempad.py), the same
# modules a real Mk4 or Mk5 freezes. Mk4 and Mk5 run identical firmware; the
# only difference is mk_num, chosen in features.MK4_MODEL.
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

mk_num = 5 if features.MK4_MODEL == 5 else 4
hw_label = 'mk5' if mk_num == 5 else 'mk4'     # what COLDCARD's probe_system() reports
has_608 = True              # emulated SE1 (secel_soft)
has_se2 = True              # emulated SE2 (trick PINs)
has_psram = True            # flash-backed, see psram.py
has_membrane = True         # Mk4/Mk5 keypad (Cardputer keys, see mempad.py)
has_nfc = False             # TODO: M5Stack NFC Cap
has_qr = False
num_sd_slots = 1
has_battery = False         # as on a real Mk4/Mk5 (USB powered; battery UI is Q-only)
has_qwerty = False
is_edge = False
supports_hsm = features.ALLOW_HSM
is_factory_mode = False
is_devmode = cp_buildinfo.IS_DEV

def probe_system():
    pass

# EOF
