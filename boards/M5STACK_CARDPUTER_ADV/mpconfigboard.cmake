# M5Stack Cardputer ADV running the COLDCARD port.
# ESP32-S3FN8: 8MB flash, no PSRAM. Radios are compiled out.
set(IDF_TARGET esp32s3)

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.240mhz
    boards/sdkconfig.flash_qio_80m
    ${MICROPY_BOARD_DIR}/sdkconfig.board
)

set(MICROPY_FROZEN_MANIFEST ${MICROPY_BOARD_DIR}/manifest.py)

# LAYOUT=launcher (tools/build_device.sh): single 'vfs' data partition for
# M5Launcher. Uses its own build directory, so switching never mixes configs.
if("$ENV{CP_LAYOUT}" STREQUAL "launcher")
    list(APPEND SDKCONFIG_DEFAULTS ${MICROPY_BOARD_DIR}/sdkconfig.launcher)
endif()
