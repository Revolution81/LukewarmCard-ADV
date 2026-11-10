# cc_boot.py - start COLDCARD on the Cardputer (equivalent of the Q's bootrom
# + stm32/COLDCARD/initfs.c). Imported by _boot.py (device) or the desktop
# test harness. Does not return.
import sys
import cp_board

# entropy source on, /flash mounted, display/keyboard bus up
cp_board.early_init()

# COLDCARD names STM32 pins: route "machine" through our wrapper
import cc_machine
sys.modules['machine'] = cc_machine

import main     # COLDCARD's main.py; runs forever

# EOF
