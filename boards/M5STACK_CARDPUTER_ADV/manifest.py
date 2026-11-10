# Frozen modules for the Cardputer COLDCARD firmware.
# CP_PY_DIR is set by tools/build_device.sh (output of tools/assemble.py).
import os

include("$(MPY_DIR)/extmod/asyncio")

# No require("usb-device-hid"): it freezes a package named "usb", which
# shadows COLDCARD's usb.py. Vendored as hal/device/cp_usbcore.py / cp_usbhid.py.

# opt=0 keeps assert statements: COLDCARD relies on them for validation
freeze(os.environ["CP_PY_DIR"], opt=0)
