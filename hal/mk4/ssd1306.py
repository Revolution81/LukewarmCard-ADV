# ssd1306.py - Cardputer port, Mk4/Mk5 variant: stands in for COLDCARD's
# SSD1306 OLED driver.
#
# COLDCARD's own display.py (the Mk4/Mk5 screen code) runs unmodified on top
# of this. It draws into the same 128x64 1-bit framebuffer the real OLED uses
# (framebuf MONO_VLSB, 1024 bytes); show() pushes that buffer to the
# Cardputer's 240x135 colour LCD, scaled in C by lcd.send_mono().
#
# The OLED-only extras are emulated:
#   contrast()          -> LCD backlight level
#   invert()            -> swap foreground/background colours
#   poweroff/poweron()  -> backlight off/on
#   busy_bar()          -> the bottom 8 rows show the pattern (the OLED scrolls
#                          it in hardware; here it is drawn once, not animated)
#
import framebuf, lcd, cp_board, features

_W, _H = cp_board.LCD_W, cp_board.LCD_H

def _geometry():
    # where the 128x64 picture goes on the LCD: (x, y, w, h)
    if features.MK4_SCREEN == 'actual':
        return ((_W - 128) // 2, (_H - 64) // 2, 128, 64)
    # 'fit': full width, 2x tall (240x128, 15:8 horizontally)
    return (0, (_H - 128) // 2, _W, 128)


class SSD1306(framebuf.FrameBuffer):
    def __init__(self, width, height, is_mk5):
        self.width = width
        self.height = height
        self.is_mk5 = is_mk5
        self.pages = self.height // 8
        self.buffer = bytearray(1024)
        super().__init__(self.buffer, self.width, self.height, framebuf.MONO_VLSB)

        self.dev = cp_board.lcd_dev()
        self.fg = features.MK4_FG_COLOR
        self.bg = features.MK4_BG_COLOR
        self.inverted = False
        self.geom = _geometry()
        self.init_display()

    def init_display(self):
        # black out the whole LCD once; borders around the picture stay black
        lcd.fill_rect(self.dev, 0, 0, _W, _H, self.bg)
        self.fill(0)
        self.show()
        self.poweron()

    def poweroff(self):
        cp_board.backlight(0)

    def poweron(self):
        cp_board.backlight(255)

    def contrast(self, contrast):
        # COLDCARD: 0x00 = dim .. 0xff = bright (very similar on the OLED).
        # Keep the LCD readable at the dim end.
        cp_board.backlight(max(64, min(255, contrast)))

    def invert(self, invert):
        self.inverted = bool(invert & 1)
        self.show()

    def show(self):
        x, y, w, h = self.geom
        fg, bg = (self.bg, self.fg) if self.inverted else (self.fg, self.bg)
        lcd.send_mono(self.dev, x, y, w, h, self.buffer, self.width, self.height, fg, bg)

    def busy_bar(self, enable, pattern):
        if enable:
            # pattern: one byte per column for the last 8 rows (page 7)
            self.buffer[7*self.width:8*self.width] = pattern
            self.show()
        # disable: caller redraws the screen (display.busy_bar -> show)


class SSD1306_SPI(SSD1306):
    # same constructor as COLDCARD's driver; the bus/pins are not used here
    def __init__(self, width, height, spi=None, dc=None, res=None, cs=None, is_mk5=False):
        super().__init__(width, height, is_mk5)

# EOF
