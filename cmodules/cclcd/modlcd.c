// Cardputer port of COLDCARD Q's "lcd" helper module (stm32/COLDCARD_Q1/modlcd.c).
//
// Same Python API as the Q1 version:
//     lcd.send_packed(dev, x, y, w, h, palette, pixels)
//     lcd.send_qr(dev, x, y, w, expand, scan_w, packed_data, trim_lines)
//     lcd.fill_rect(dev, x, y, w, h, pixel)
//
// Difference: instead of a raw STM32 SPI handle, "dev" is any Python object
// with two methods:
//     dev._set_window(x, y, w, h)
//     dev.write_data(buf)
// The pixel expansion (the slow part) stays in C; only the bus I/O goes
// through Python. This lets the identical code run on the ESP32 (real ST7789)
// and in the desktop test harness (fake framebuffer).
//
#include <string.h>
#include "py/runtime.h"
#include "py/objarray.h"

#define SWAB16(x) ((uint16_t)((((x) & 0xff) << 8) | (((x) >> 8) & 0xff)))

// biggest chunk we push per write_data() call
#define CHUNK_BYTES 2048

static void dev_set_window(mp_obj_t dev, int x, int y, int w, int h) {
    mp_obj_t dest[6];
    mp_load_method(dev, MP_QSTR__set_window, dest);
    dest[2] = MP_OBJ_NEW_SMALL_INT(x);
    dest[3] = MP_OBJ_NEW_SMALL_INT(y);
    dest[4] = MP_OBJ_NEW_SMALL_INT(w);
    dest[5] = MP_OBJ_NEW_SMALL_INT(h);
    mp_call_method_n_kw(4, 0, dest);
}

static void dev_write(mp_obj_t dev, const uint8_t *buf, size_t len) {
    // memoryview over caller's (stack) buffer; callee must not keep it
    mp_obj_t mv = mp_obj_new_memoryview('B', len, (void *)buf);
    mp_obj_t dest[3];
    mp_load_method(dev, MP_QSTR_write_data, dest);
    dest[2] = mv;
    mp_call_method_n_kw(1, 0, dest);
}

static void dev_write_repeated(mp_obj_t dev, int count, const uint8_t *line, size_t line_len) {
    // send the same scan line "count" times, batching lines to cut call overhead
    if(count <= 0 || !line_len) return;

    int per = CHUNK_BYTES / line_len;
    if(per < 1) per = 1;
    if(per > count) per = count;

    if(per == 1) {
        for(int i=0; i<count; i++) dev_write(dev, line, line_len);
        return;
    }

    // static, not from the Python heap: filling a rectangle must not fail
    // when the heap is nearly full
    static uint8_t chunk[CHUNK_BYTES];
    for(int i=0; i<per; i++) memcpy(chunk + i*line_len, line, line_len);

    while(count > 0) {
        int n = (count < per) ? count : per;
        dev_write(dev, chunk, n * line_len);
        count -= n;
    }
}

static mp_obj_t send_packed(size_t n_args, const mp_obj_t *args) {
    // 4-bit packed palette-ized pixels (fonts): unpack and send
    mp_obj_t dev = args[0];
    mp_int_t x = mp_obj_get_int(args[1]);
    mp_int_t y = mp_obj_get_int(args[2]);
    mp_int_t w = mp_obj_get_int(args[3]);
    mp_int_t h = mp_obj_get_int(args[4]);

    mp_buffer_info_t palette, pixels;
    mp_get_buffer_raise(args[5], &palette, MP_BUFFER_READ);
    mp_get_buffer_raise(args[6], &pixels, MP_BUFFER_READ);

    if(palette.len != 16*2) mp_raise_ValueError(MP_ERROR_TEXT("palette"));
    if(w <= 0 || h <= 0 || w > 64 || h > 64) mp_raise_ValueError(MP_ERROR_TEXT("size"));
    if(pixels.len * 2 < (size_t)(w * h)) mp_raise_ValueError(MP_ERROR_TEXT("pixels"));

    const uint8_t *pal = palette.buf;
    uint8_t fb[(w * h * 2) + 4];
    const uint8_t *p = pixels.buf;
    uint8_t *o = fb;
    size_t npairs = (w * h + 1) / 2;
    for(size_t i=0; i<npairs; i++, p++, o+=4) {
        uint8_t px1 = (*p >> 4) * 2;
        uint8_t px2 = (*p & 0xf) * 2;
        o[0] = pal[px1];
        o[1] = pal[px1+1];
        o[2] = pal[px2];
        o[3] = pal[px2+1];
    }

    dev_set_window(dev, x, y, w, h);
    dev_write(dev, fb, w*h*2);

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(send_packed_obj, 7, 7, send_packed);

static mp_obj_t send_qr(size_t n_args, const mp_obj_t *args) {
    // packed QR bitmap -> black/white squares, expanded, with 1-module border
    const uint16_t COL_WHITE = 0xffff;
    const uint16_t COL_BLACK = 0x0000;

    mp_obj_t dev = args[0];
    mp_int_t x = mp_obj_get_int(args[1]);
    mp_int_t y = mp_obj_get_int(args[2]);
    mp_int_t w = mp_obj_get_int(args[3]);
    mp_int_t expand = mp_obj_get_int(args[4]);
    mp_int_t scan_w = mp_obj_get_int(args[5]);

    mp_buffer_info_t boxes;
    mp_get_buffer_raise(args[6], &boxes, MP_BUFFER_READ);
    if(boxes.len != (size_t)((scan_w*w) / 8)) mp_raise_ValueError(MP_ERROR_TEXT("qr len"));

    mp_int_t trim_lines = mp_obj_get_int(args[7]);
    if(trim_lines && expand == 1) mp_raise_ValueError(MP_ERROR_TEXT("trim"));
    if(expand < 1 || w < 1 || (w+2)*expand > 400) mp_raise_ValueError(MP_ERROR_TEXT("qr size"));

    const int W = (w+2) * expand;
    uint16_t line[W];
    for(int i=0; i<W; i++) line[i] = COL_WHITE;

    // top and bottom white borders
    dev_set_window(dev, x, y, W, expand);
    dev_write_repeated(dev, expand, (const uint8_t *)line, sizeof(line));
    dev_set_window(dev, x, y+W-expand-trim_lines, W, expand);
    dev_write_repeated(dev, expand, (const uint8_t *)line, sizeof(line));

    // body
    dev_set_window(dev, x, y+expand, W, (expand*w)-trim_lines);

    const uint8_t *ptr = boxes.buf;
    for(int Y=0; Y < w; Y++, ptr += (scan_w/8)) {
        const uint8_t *p = ptr;
        for(int X=0; X<w; ) {
            for(uint8_t m = 0x80; m && (X < w); m >>= 1) {
                uint16_t here = ((*p) & m) ? COL_BLACK : COL_WHITE;
                for(int r=0; r<expand; r++) {
                    line[((1+X)*expand) + r] = here;
                }
                X++;
            }
            p++;
        }

        if(trim_lines && Y && ((Y % 23) == 0)) {
            trim_lines--;
            dev_write_repeated(dev, expand-1, (const uint8_t *)line, sizeof(line));
        } else {
            dev_write_repeated(dev, expand, (const uint8_t *)line, sizeof(line));
        }
    }

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(send_qr_obj, 8, 8, send_qr);

static mp_obj_t fill_rect(size_t n_args, const mp_obj_t *args) {
    mp_obj_t dev = args[0];
    mp_int_t x = mp_obj_get_int(args[1]);
    mp_int_t y = mp_obj_get_int(args[2]);
    mp_int_t w = mp_obj_get_int(args[3]);
    mp_int_t h = mp_obj_get_int(args[4]);
    mp_int_t pixel = mp_obj_get_int(args[5]);

    if(w <= 0 || h <= 0) return mp_const_none;
    if(w > 400) mp_raise_ValueError(MP_ERROR_TEXT("w"));

    uint16_t line[w];
    for(int i=0; i<w; i++) line[i] = SWAB16(pixel);

    dev_set_window(dev, x, y, w, h);
    dev_write_repeated(dev, h, (const uint8_t *)line, sizeof(line));

    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(fill_rect_obj, 6, 6, fill_rect);

static mp_obj_t send_mono(size_t n_args, const mp_obj_t *args) {
    // Cardputer, Mk4/Mk5 variant: send a 1-bit MONO_VLSB framebuffer (the
    // Mk4/Mk5 OLED's memory layout) scaled to out_w x out_h, nearest neighbour.
    //   lcd.send_mono(dev, x, y, out_w, out_h, src, src_w, src_h, fg, bg)
    mp_obj_t dev = args[0];
    mp_int_t x = mp_obj_get_int(args[1]);
    mp_int_t y = mp_obj_get_int(args[2]);
    mp_int_t ow = mp_obj_get_int(args[3]);
    mp_int_t oh = mp_obj_get_int(args[4]);
    mp_buffer_info_t src;
    mp_get_buffer_raise(args[5], &src, MP_BUFFER_READ);
    mp_int_t sw = mp_obj_get_int(args[6]);
    mp_int_t sh = mp_obj_get_int(args[7]);
    uint16_t fg = SWAB16(mp_obj_get_int(args[8]));
    uint16_t bg = SWAB16(mp_obj_get_int(args[9]));

    if(ow <= 0 || oh <= 0 || ow > 400 || oh > 400) mp_raise_ValueError(MP_ERROR_TEXT("size"));
    if(sw <= 0 || sh <= 0 || (sh % 8)) mp_raise_ValueError(MP_ERROR_TEXT("src size"));
    if(src.len < (size_t)(sw * sh / 8)) mp_raise_ValueError(MP_ERROR_TEXT("src"));

    const uint8_t *s = src.buf;
    uint16_t line[ow];
    dev_set_window(dev, x, y, ow, oh);

    int oy = 0;
    while(oy < oh) {
        int sy = (oy * sh) / oh;
        // how many output rows come from this same source row
        int n = 1;
        while(oy + n < oh && ((oy + n) * sh) / oh == sy) n++;

        const uint8_t *page = s + (sy >> 3) * sw;
        uint8_t mask = 1 << (sy & 7);
        for(int ox=0; ox<ow; ox++) {
            int sx = (ox * sw) / ow;
            line[ox] = (page[sx] & mask) ? fg : bg;
        }
        dev_write_repeated(dev, n, (const uint8_t *)line, sizeof(line));
        oy += n;
    }
    return mp_const_none;
}
static MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(send_mono_obj, 10, 10, send_mono);

static const mp_rom_map_elem_t lcd_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__),     MP_ROM_QSTR(MP_QSTR_lcd) },
    { MP_ROM_QSTR(MP_QSTR_send_mono),    MP_ROM_PTR(&send_mono_obj) },
    { MP_ROM_QSTR(MP_QSTR_send_packed),  MP_ROM_PTR(&send_packed_obj) },
    { MP_ROM_QSTR(MP_QSTR_fill_rect),    MP_ROM_PTR(&fill_rect_obj) },
    { MP_ROM_QSTR(MP_QSTR_send_qr),      MP_ROM_PTR(&send_qr_obj) },
};
static MP_DEFINE_CONST_DICT(lcd_module_globals, lcd_module_globals_table);

const mp_obj_module_t cc_lcd_module = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t *)&lcd_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_lcd, cc_lcd_module);
