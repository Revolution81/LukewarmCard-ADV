//
// random_backend.h - fail-closed target entropy selection
//
#pragma once

#include <stdbool.h>
#include <stdint.h>

#if MICROPY_PY_THREAD && !MICROPY_PY_THREAD_GIL
# error "ngu.random requires the GIL when threads are enabled"
#endif

// Every backend returns false when it cannot provide a word. This lets the
// caller clean sensitive state before raising a MicroPython exception.
// Cardputer port: NGU_TARGET_ESP32 comes from cmodules/libngu.cmake. MicroPython's
// ESP32 build also compiles user-module sources in the top-level .elf target,
// where IDF's ESP_PLATFORM is not defined, so don't rely on ESP_PLATFORM alone.
#if defined(ESP_PLATFORM) || (defined(NGU_TARGET_ESP32) && NGU_TARGET_ESP32)
# if NGU_ESP32_RNG_IS_TRUE_RANDOM != 1
#  error "NGU_ESP32_RNG_IS_TRUE_RANDOM=1 required; see README"
# endif
# include "esp_system.h"
// Cardputer port: esp_random() is only a TRUE random source while RF is on
// or bootloader_random_enable() is active. Radios are compiled out of this
// firmware, so modcardputer.c turns the SAR-ADC noise source on at boot and
// tracks it in this flag. Fail closed if it is ever off.
extern volatile bool cardputer_entropy_active;
static bool chip_trng_read(uint32_t *out)
{
    if(!cardputer_entropy_active) {
        return false;
    }
    *out = esp_random();
    return true;
}

#elif defined(MICROPY_PY_STM)
# if MICROPY_HW_ENABLE_RNG != 1 && NGU_STM32_EXTERNAL_RNG_GET != 1
#  error "MICROPY_HW_ENABLE_RNG=1 or NGU_STM32_EXTERNAL_RNG_GET=1 required"
# endif
// MicroPython's ports/stm32/rng.c returns zero on a peripheral timeout. An
// external provider uses the same interface, so reject zero for both paths.
extern uint32_t rng_get(void);
static bool chip_trng_read(uint32_t *out)
{
    uint32_t word = rng_get();
    if(!word) {
        return false;
    }
    *out = word;
    return true;
}

#elif defined(__APPLE__) || defined(__FreeBSD__)
# include <stdlib.h>
static bool chip_trng_read(uint32_t *out)
{
    *out = arc4random();
    return true;
}

#elif defined(__linux__)
# include <sys/random.h>
static bool chip_trng_read(uint32_t *out)
{
    return getrandom(out, sizeof(*out), 0) == (ssize_t)sizeof(*out);
}

#else
# error "No hardware or OS entropy source is defined for this target"
#endif
