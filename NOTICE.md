# NOTICE: LukewarmCard ADV and the software it contains

LukewarmCard ADV is an **unofficial** port of COLDCARD firmware to the M5Stack
Cardputer ADV. It is **not affiliated with, endorsed by, or supported by
Coinkite Inc.** COLDCARD is a trademark of Coinkite Inc. M5Stack and Cardputer
are trademarks of M5Stack Technology Co. These names are used only to describe
what this software runs and what it runs on.

**Not for sale.** The COLDCARD licence includes the "Commons Clause": nobody
may sell this software, charge for support or hosting of it, or sell devices
whose value comes from it. That applies to LukewarmCard ADV and every copy of
it, including the firmware images.

Full licence texts are in the `licenses/` folder (and next to the firmware
images in each release).

| Component | Used for | Copyright | Licence | File |
|---|---|---|---|---|
| **COLDCARD firmware** (github.com/Coldcard/firmware) | all wallet logic; built into every image; parts of `hal/` adapted from its simulator | Coinkite Inc. | MIT + Commons Clause | `COLDCARD-COPYING-CC.txt` |
| **LukewarmCard ADV** (this port) | Cardputer support (`hal/`, `tools/`, `tests/`) | the LukewarmCard ADV contributors | MIT + Commons Clause | `../LICENSE` |
| **libngu** (in COLDCARD) | bitcoin crypto (C); a modified copy in `cmodules/libngu-src` | Switck | MIT, "for Bitcoin only" condition | `libngu-LICENSE.txt` |
| **libsecp256k1** (in libngu) | elliptic curve maths | Pieter Wuille, Bitcoin Core contributors | MIT | `secp256k1-COPYING.txt` |
| **cifra** (in libngu) | hashes, AES | Joseph Birr-Pixton | CC0 (public domain) | `cifra-COPYING.txt` |
| **bech32 reference code** (in libngu) | address encoding | Pieter Wuille | MIT | `bech32-LICENSE.txt` |
| **mpy-qr** (`cmodules/mpy-qr`) | QR codes | Coinkite; Project Nayuki (qrcodegen) | MIT | `mpy-qr-LICENSE.txt` |
| **MicroPython** v1.29.0 | the Python runtime | Damien P. George and contributors | MIT (some files other permissive licences, listed inside) | `MicroPython-LICENSE.txt` |
| **micropython-lib** usb-device / usb-device-hid (`hal/device/cp_usbcore.py`, `cp_usbhid.py`, renamed) | USB support | Angus Gratton, MicroPython contributors | MIT | `micropython-lib-LICENSE.txt` |
| **ESP-IDF** v5.5.4 and its components (FreeRTOS, TinyUSB, newlib, mbedTLS, ...) | ESP32-S3 system software, built into every image | Espressif Systems and component authors | Apache-2.0 (components: their own permissive licences, see the ESP-IDF source) | `ESP-IDF-LICENSE.txt` |
| **Bosch BMI270 configuration blob** (`hal/device/cp_bmi270_cfg.py`) | motion-sensor start-up data | Bosch Sensortec GmbH | BSD-3-Clause | `Bosch-BMI270-LICENSE.txt` |
| **M5Unified** (register values only, `hal/device/cp_sensors.py`) | microphone codec settings | M5Stack | MIT | `M5Unified-LICENSE.txt` |

## Changes made to COLDCARD

COLDCARD's Python code is used as published, except for small exact-match
edits made at build time by `tools/assemble.py` (each listed there with a
comment): screen size, keyboard, the SD card folder, a few on-screen texts,
self-test steps for this hardware, and menus for Entropy Sources and Key
Storage. The parts of COLDCARD that talk to its hardware (bootloader calls,
secure elements, PSRAM, USB) are replaced by the files in `hal/`.

## No warranty

Like COLDCARD itself, this software is provided "as is", without warranty
of any kind. It has no secure element; read the security section of
README.md before using it with real funds.
