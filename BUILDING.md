# Building LukewarmCard ADV images yourself

When Coinkite releases new COLDCARD firmware, you can turn it into new
LukewarmCard ADV images with one command. The build fetches COLDCARD's source at
the version you name, applies this port's small set of adjustments, runs the
test suites on your computer (create a wallet, back up and restore, sign a
transaction, talk to wallet software over USB, and more), and only then builds
the images.

You get the Keypad edition images plus checksums and licences in
`dist/<version>/`:

| File | What it is |
|---|---|
| `lukewarmcard-adv-keypad-<ver>-launcher.bin` | install with M5Launcher |
| `lukewarmcard-adv-keypad-<ver>-full-flash.bin` | whole flash at 0x0 (replaces Launcher) |
| `SHA256SUMS.txt`, `BUILDINFO.txt` | checksums, and which COLDCARD source was used |
| `NOTICE.md`, `LICENSE`, `*-LICENSE.txt` | licences: keep them with the images if you share them |

## Which version to build

| You type | You get |
|---|---|
| `latest-mk5` | the newest Mk4/Mk5 release tag (e.g. `2026-09-30T2026-v5.6.3`) |
| a tag name | exactly that release, from [Coinkite's tags](https://github.com/Coldcard/firmware/tags) |
| `master` | Coinkite's newest code, including unreleased work |
| nothing | the commit this port was last tested with |

Coinkite tags each product line's releases separately; `latest-mk5` picks
the newest Mk4/Mk5 one, which is what this kit builds.

## Option A: on GitHub, nothing to install

1. Make a GitHub repository (private is fine) and upload the contents of this
   kit to it, including the hidden `.github` folder.
2. Open the repository's **Actions** tab, choose **Build LukewarmCard images**,
   click **Run workflow**, keep `latest-mk5` (or type another version) and run.
3. After about 30 minutes, open the finished run and download the artifact
   at the bottom of the page. It contains `dist/` with the images, and the
   test logs.

It also checks for a new Mk4/Mk5 release every Monday. When there is one, it
builds and tests it and publishes the images under **Releases** in your
repository. If you don't want that, delete the `schedule:` lines in
`.github/workflows/build.yml`.

## Option B: Docker, on Windows, macOS or Linux

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/),
then in a terminal in this folder:

```
docker build -t lukewarmcard .
docker run --rm -v "$PWD:/port" -v cc-src:/src lukewarmcard latest-mk5
```

(On Windows PowerShell use `${PWD}` instead of `$PWD`.) The first build image
takes a while to download (it has the ESP32 compiler in it). Later runs reuse
it, and `-v cc-src:/src` keeps the downloaded sources between runs.

## Option C: directly on Linux

```
# once: ESP32 compiler (about 2 GB)
git clone -b v5.5.4 --recursive https://github.com/espressif/esp-idf.git ~/esp-idf
~/esp-idf/install.sh esp32s3
sudo apt install build-essential libffi-dev pkg-config git python3-pip
pip install embit pillow ckcc-protocol
pip install --ignore-requires-python hwi==3.2.0      # optional: the USB test

# each new release
tools/build_release.sh latest-mk5
```

Useful settings: `LAYOUTS=launcher` builds only the M5Launcher image,
`SKIP_TESTS=1` skips the tests (don't, for a new version).

## Installing a new version

1. On the Cardputer: **Advanced/Tools > Backup > Backup System**. The backup
   goes to the `MK5` folder on the SD card. Write down the backup words.
2. Check the image: compare its SHA-256 with `SHA256SUMS.txt`.
3. Put the `-launcher.bin` on the SD card and install it with M5Launcher.
4. Start it, choose a PIN, then **Import Existing > Restore Backup** with the
   backup words.

Firmware upgrades from inside the firmware (**Upgrade Firmware > From
MicroSD**) don't work on the Cardputer: Coinkite's `.dfu` files contain code
for the real COLDCARD's chip. The firmware says so on screen if you try.

## Sharing the images

The licence (MIT + Commons Clause, see NOTICE.md) lets you share them freely,
as long as `NOTICE.md`, `LICENSE` and the licence files go with them (the
build puts them next to the images, and the GitHub release attaches them) and
nobody is charged for them.

## If the build stops

**"patch for X.py matched 0 times"**: this port changes a handful of lines in
COLDCARD's code (screen size, the SD card folder, a few texts; they are listed
in `tools/assemble.py`). Each change must find its exact original text, so if
Coinkite rewrote that part the build stops instead of guessing. Nothing is
broken; the port needs a small update for that version. Send the log to
whoever maintains your copy of the port (or to Claude) together with the
version you tried.

**A test failed**: COLDCARD now behaves differently in a way the tests
noticed (new screen, new question during setup). The logs are in
`build/release-logs/`. Same as above: the port needs an update before that
version should go on your Cardputer.

**"NOTE: COLDCARD now uses libngu ..."**: Coinkite updated their crypto
library. This port carries its own copy (with small changes for the ESP32),
so their update isn't in your build. It usually doesn't matter; check
Coinkite's change log for libngu fixes.

Images from a stopped build are never put in `dist/`.
