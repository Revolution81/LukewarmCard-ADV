# usb_test_commands.py - Cardputer port, desktop test build only.
#
# COLDCARD's own version (left out of every build by tools/assemble.py) adds
# simulator-only USB commands, including EVAL/EXEC which run arbitrary code.
# This one only accepts XKEY: HWI sends it to a COLDCARD simulator right
# after "sign transaction" to press OK automatically. It is ignored here, so
# the test scripts approve on screen with the keypad, as a person would on
# the device. Device builds never contain this file.

def do_usb_command(cmd, args):
    if cmd == 'XKEY':
        return None
    return b'err_Unknown SIMULATOR cmd'

# EOF
