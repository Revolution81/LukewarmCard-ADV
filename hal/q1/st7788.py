# st7788.py - Cardputer port of COLDCARD Q's LCD driver.
#
# Same class name and methods as shared/st7788.py (so lcd_display.py is reused),
# but the pixel bus is cp_board.lcd_dev(): the ST7789 on the device, or a fake
# framebuffer in the desktop test build. Heavy lifting is in the C "lcd" module.
#
import lcd, cp_board

class _Backlight:
    def on(self):
        cp_board.backlight(255)
    def off(self):
        cp_board.backlight(0)
    def intensity(self, v):
        cp_board.backlight(v)

class ST7788:
    instance = None

    def __init__(self):
        self.spi = cp_board.lcd_dev()       # passed as "dev" to the lcd module
        self.backlight = _Backlight()
        self.backlight.on()
        ST7788.instance = self

    def fill_screen(self, pixel=0x0000):
        self.fill_rect(0, 0, cp_board.LCD_W, cp_board.LCD_H, pixel)

    def show_zpixels(self, x, y, w, h, zpixels):
        import uzlib
        data = uzlib.decompress(zpixels, -10)
        self.spi._set_window(x, y, w, h)
        self.spi.write_data(data)

    def show_pal_pixels(self, x, y, w, h, palette, pixels):
        lcd.send_packed(self.spi, x, y, w, h, palette, pixels)

    def show_qr_data(self, x, y, w, expand, scan_w, packed_data, trim_lines=0):
        lcd.send_qr(self.spi, x, y, w, expand, scan_w, packed_data, trim_lines)

    def fill_rect(self, x, y, w, h, pixel=0x0000):
        if not w or not h:
            return
        lcd.fill_rect(self.spi, x, y, w, h, pixel)

# EOF
