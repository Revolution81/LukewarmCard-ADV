// Cardputer ADV hardware helpers that need C (ESP32-S3 only).
//
//   cardputer.entropy(on)      enable/disable the SAR-ADC true-entropy source
//   cardputer.entropy()        -> bool, is it on?
//   cardputer.rng_bytes(buf)   fill buf with hardware random; raises if entropy off
//   cardputer.chip_id()        -> bytes(6), factory MAC (used as a device id only)
//   cardputer.usb_state()      -> 0 no host, 1 set up by a host and active,
//                                 2 suspended (cable pulled, or PC asleep)
//
// Radios (WiFi/BLE) are compiled out of this firmware. Without RF running,
// esp_random() is only pseudo-random unless bootloader_random_enable() is on,
// see ESP-IDF "Random Number Generation" docs. libngu's RNG backend checks
// cardputer_entropy_active and refuses to produce bytes while it is false.
//
#include <stdbool.h>
#include "py/runtime.h"
#include "esp_random.h"
#include "esp_mac.h"
#include "bootloader_random.h"
#if MICROPY_HW_ENABLE_USBDEV
#include "tusb.h"
#endif

volatile bool cardputer_entropy_active = false;

static mp_obj_t cp_entropy(size_t n_args, const mp_obj_t *args) {
    if(n_args == 1) {
        bool on = mp_obj_is_true(args[0]);
        if(on && !cardputer_entropy_active) {
            bootloader_random_enable();
            cardputer_entropy_active = true;
        } else if(!on && cardputer_entropy_active) {
            cardputer_entropy_active = false;
            bootloader_random_disable();
        }
    }
    return mp_obj_new_bool(cardputer_entropy_active);
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(cp_entropy_obj, 0, 1, cp_entropy);

static mp_obj_t cp_rng_bytes(mp_obj_t buf_in) {
    mp_buffer_info_t buf;
    mp_get_buffer_raise(buf_in, &buf, MP_BUFFER_WRITE);
    if(!cardputer_entropy_active) {
        mp_raise_msg(&mp_type_RuntimeError, MP_ERROR_TEXT("entropy source off"));
    }
    esp_fill_random(buf.buf, buf.len);
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_1(cp_rng_bytes_obj, cp_rng_bytes);

static mp_obj_t cp_chip_id(void) {
    uint8_t mac[6] = {0};
    esp_read_mac(mac, ESP_MAC_EFUSE_FACTORY);
    return mp_obj_new_bytes(mac, 6);
}
static MP_DEFINE_CONST_FUN_OBJ_0(cp_chip_id_obj, cp_chip_id);

static mp_obj_t cp_usb_state(void) {
    // The S3's USB has no VBUS sensing on this board, so an unplugged cable
    // shows up as "suspended" (no bus activity) rather than "unmounted".
    int st = 0;
    #if MICROPY_HW_ENABLE_USBDEV
    if (tud_mounted()) {
        st = tud_suspended() ? 2 : 1;
    }
    #endif
    return MP_OBJ_NEW_SMALL_INT(st);
}
static MP_DEFINE_CONST_FUN_OBJ_0(cp_usb_state_obj, cp_usb_state);

static const mp_rom_map_elem_t cp_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),   MP_ROM_QSTR(MP_QSTR_cardputer) },
    { MP_ROM_QSTR(MP_QSTR_entropy),    MP_ROM_PTR(&cp_entropy_obj) },
    { MP_ROM_QSTR(MP_QSTR_rng_bytes),  MP_ROM_PTR(&cp_rng_bytes_obj) },
    { MP_ROM_QSTR(MP_QSTR_chip_id),    MP_ROM_PTR(&cp_chip_id_obj) },
    { MP_ROM_QSTR(MP_QSTR_usb_state),  MP_ROM_PTR(&cp_usb_state_obj) },
};
static MP_DEFINE_CONST_DICT(cp_module_globals, cp_module_globals_table);

const mp_obj_module_t cardputer_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&cp_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_cardputer, cardputer_module);
