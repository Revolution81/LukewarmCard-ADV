# LukewarmCard ADV, Keypad edition: first release

**A poor man's port of COLDCARD firmware to the M5Stack Cardputer ADV.**
Runs Coinkite's COLDCARD Mk4/Mk5 firmware **5.6.3**, essentially unmodified.

> **Unofficial.** Not affiliated with, endorsed by, or supported by Coinkite
> Inc. COLDCARD is a trademark of Coinkite; the name is used only to say what
> this runs.

> **Security: it's lukewarm, not cold.** No secure-element chips. Your
> encrypted seed (internal flash or SD card) is protected only by your PIN,
> and anyone who copies it can guess PINs on a computer. Anyone with the
> device can install modified firmware. **Use a strong BIP-39 passphrase,
> keep amounts small, treat it as a learning and tinkering device.**

## Files

| File | Use |
|---|---|
| `lukewarmcard-adv-keypad-5.6.3-launcher.bin` | install with **M5Launcher** (copy to the SD card, pick it in Launcher) |
| `lukewarmcard-adv-keypad-5.6.3-full-flash.bin` | write at offset **0x0** with esptool or a web flasher (replaces Launcher) |
| `SHA256SUMS.txt` | check your download |
| `NOTICE.md`, `LICENSE`, `*-LICENSE.txt` | licences: keep them with the images if you share them |

## What works (tested on a Cardputer ADV)

- Create or import a wallet; PIN, trick PINs, BIP-39 passphrase
- Sparrow / Electrum / HWI over USB: detect, show xpubs, **sign and send**
- PSBTs from the microSD card (stored in an `MK5` folder), paper wallets, backups and restore
- Encrypted key on the SD card (default when a card is in) or internal flash: Advanced/Tools > Key Storage
- Extra randomness for new seeds from the microphone and motion sensor, mixed with the ESP32's hardware RNG: Advanced/Tools > Entropy Sources
- Self-test for this hardware (keys, LED, mic, gyro, SD, memory)
- Virtual Disk (a 4MB USB drive stored on the SD card): passes all desktop tests, not yet confirmed with a computer on real hardware

## Keys

0-9 as on a COLDCARD; **Enter** = OK; **esc** (`) or **del** = X; **; . , /** = up, down, left, right.

## Good to know

- Identifies itself to computers with Coinkite's USB IDs (VID d13e / PID cc10)
  so wallet software uses the COLDCARD protocol. USB name strings say "LukewarmCard".
- Firmware updates from Coinkite (.dfu files) don't install on it; new
  COLDCARD releases are built into new images with the build kit in this
  repository (BUILDING.md).
- **Not for sale:** MIT + Commons Clause, same as COLDCARD. Free to use,
  change and share; never charge for it or for devices with it installed.
- Before installing over an existing wallet: Advanced/Tools > Backup.

The QWERTY edition (COLDCARD Q firmware) builds and passes the desktop tests
but hasn't been tried on a Cardputer yet; it will follow later.
