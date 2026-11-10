#define MICROPY_HW_BOARD_NAME               "M5Stack Cardputer ADV (COLDCARD port)"
#define MICROPY_HW_MCU_NAME                 "ESP32-S3"

// No radios: a signing device has no use for them, and leaving them out
// frees RAM. (Also means esp_random() needs the SAR-ADC entropy source,
// which modcardputer.c enables at boot; see libngu random_backend.h.)
#define MICROPY_PY_NETWORK_WLAN             (0)
#define MICROPY_PY_BLUETOOTH                (0)
#define MICROPY_PY_ESPNOW                   (0)
// No network stack at all: no sockets, TLS, WebREPL or mDNS (also drops the
// espressif/mdns dependency; tools/build_device.sh removes it).
#define MICROPY_PY_NETWORK                  (0)
#define MICROPY_PY_NETWORK_LAN              (0)
#define MICROPY_PY_NETWORK_PPP_LWIP         (0)
#define MICROPY_HW_ENABLE_MDNS_QUERIES      (0)
#define MICROPY_HW_ENABLE_MDNS_RESPONDER    (0)

// libngu build settings. cmodules/libngu.cmake sets these too, but
// MicroPython's qstr scan doesn't see user-module compile definitions, so they
// are repeated here (every compile step includes this header). Keep in sync.
#ifndef NGU_ESP32_RNG_IS_TRUE_RANDOM
#define NGU_ESP32_RNG_IS_TRUE_RANDOM        1   // see random_backend.h: fails closed if entropy is off
#endif
#ifndef NGU_USE_MBEDTLS
#define NGU_USE_MBEDTLS                     0
#endif
#ifndef NGU_INCL_AES
#define NGU_INCL_AES                        1
#endif
#ifndef NGU_INCL_SCHNORR
#define NGU_INCL_SCHNORR                    0
#endif
#ifndef NGU_INCL_MUSIG
#define NGU_INCL_MUSIG                      0
#endif
#define MICROPY_PY_MACHINE_DAC              (0)

#define MICROPY_HW_I2C0_SCL                 (9)
#define MICROPY_HW_I2C0_SDA                 (8)
