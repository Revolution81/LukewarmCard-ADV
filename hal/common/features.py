# features.py - Cardputer port: what COLDCARD features are enabled.
#
# Edit this file and rebuild to add or remove features. It is frozen into the
# firmware, so it can't be changed on the device itself.
#
# Nothing in this port can damage the Cardputer: no eFuses are ever burned, so
# it can always be reflashed over USB (power off, hold G0, plug in), and
# "brick" only erases data.

# --- Trick PINs ------------------------------------------------------------

# "Brick Self", "Countdown & Brick", "Last Chance" and Danger Zone > Nuke
# Device. On a real COLDCARD these destroy the secure elements forever.
# Here "brick" = erase PIN, seed, trick PINs and all settings, show "Bricked",
# and stop; after a power cycle it's a blank device (restore from your words).
# False hides them from the menus (and any brick trick acts as "wipe seed").
ALLOW_BRICK_OPTIONS = True

# Trick PINs that wipe the seed (Wipe & Reboot, Silent Wipe, Wipe -> Wallet,
# Say Wiped Stop, Wipe & Countdown, Policy Unlock & Wipe). These only erase
# the seed, the device keeps working. Hidden from menus when False.
ALLOW_WIPE_OPTIONS = True

# Duress wallets, "Look Blank", "Just Reboot", Delta Mode, login countdown.
ALLOW_DURESS_OPTIONS = True

# --- Failed PIN attempts -------------------------------------------------

# A real COLDCARD bricks itself after 13 wrong PINs. Choose what this port does
# when the limit is reached:
#   'brick' - like COLDCARD: erase everything (see above), blank after power cycle
#   'wipe'  - erase the seed only; PIN and settings stay
#   'none'  - keep counting, never erase (attempts shown, nothing destroyed)
MAX_PIN_ATTEMPTS = 13
ON_MAX_PIN_ATTEMPTS = 'brick'

# --- Other features ------------------------------------------------------

# HSM mode needs a USB host link to the wallet software; off until USB is ported.
ALLOW_HSM = False

# Key Teleport and other QR-camera-only features have no camera here; they
# remain reachable via microSD where COLDCARD supports that.

# Biggest PSBT we'll accept (bytes). Limited by RAM on the ESP32-S3.
# M5Launcher builds have a smaller scratch area (2 x MAX_TXN_LEN must fit in
# 256K, see hal/device/cp_flashlayout.py), so they accept up to 128K.
import cp_buildinfo
if getattr(cp_buildinfo, 'LAYOUT', 'own') == 'launcher':
    MAX_TXN_LEN = 128 * 1024
else:
    MAX_TXN_LEN = 256 * 1024

# Where this firmware keeps its files on the microSD card. None = whole card.
# A folder name = the firmware only sees and writes that folder (created on
# first use), and "Format SD Card" empties just that folder. Lets the Q and
# Mk5 firmwares (and Launcher) share one card.
if getattr(cp_buildinfo, 'VARIANT', 'q1') == 'mk4':
    SD_SUBDIR = 'MK5'
else:
    SD_SUBDIR = None

# Where new wallets keep the encrypted seed / PIN record (cp_keystore.py):
# 'sd' = on the microSD card (SD_SUBDIR/.keystore) when a card is inserted at
# the time the first PIN is set, else internal flash. 'flash' = always
# internal flash. Either can be changed later: Advanced/Tools > Key Storage.
KEY_STORE_DEFAULT = 'sd'

# --- Mk4/Mk5 firmware variant only (tools/build_*.sh --variant mk4) ------

# Which COLDCARD this build reports itself as: 4 = Mk4, 5 = Mk5. They run
# identical firmware; this only sets version.mk_num / hw_label.
MK4_MODEL = 5

# How the Mk4/Mk5's 128x64 OLED picture is shown on the 240x135 LCD:
#   'fit'    - full width, twice as tall (240x128), easy to read
#   'actual' - 1:1 pixels, centred (small, but pixel-exact)
MK4_SCREEN = 'fit'

# OLED colours, as RGB565 (white on black like the real OLED)
MK4_FG_COLOR = 0xFFFF
MK4_BG_COLOR = 0x0000


def max_attempts_text():
    # replaces COLDCARD's "will always brick after 13 failed PIN attempts"
    if ON_MAX_PIN_ATTEMPTS == 'brick':
        return 'this Cardputer erases everything (blank device) after %d failed PIN attempts.' % MAX_PIN_ATTEMPTS
    if ON_MAX_PIN_ATTEMPTS == 'wipe':
        return 'this Cardputer wipes the seed after %d failed PIN attempts.' % MAX_PIN_ATTEMPTS
    return 'this Cardputer only counts failed PIN attempts (it never wipes).'


def limit_action_text():
    # login warning when few PIN attempts remain
    if ON_MAX_PIN_ATTEMPTS == 'brick':
        return 'this Cardputer ERASES EVERYTHING and resets to blank. (Restore from your seed words.)'
    if ON_MAX_PIN_ATTEMPTS == 'wipe':
        return 'this Cardputer WIPES THE SEED. (You can restore from your seed words.)'
    return 'the limit is reached. (Nothing will be erased on this Cardputer.)'


def trick_menu_allowed(flags):
    # Used by the trick PIN menus to hide disabled options.
    from trick_pins import TC_BRICK, TC_WIPE
    if (flags & TC_BRICK) and not ALLOW_BRICK_OPTIONS:
        return False
    if (flags & TC_WIPE) and not ALLOW_WIPE_OPTIONS:
        return False
    return True

# EOF
