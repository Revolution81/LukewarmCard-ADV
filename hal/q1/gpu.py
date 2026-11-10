# gpu.py - Cardputer port: stand-in for COLDCARD Q's graphics co-processor.
#
# On the Q, a small STM32C0 draws the blinking text cursor and the "busy"
# animation. The Cardputer has no such chip, so the cursor is drawn directly
# (static, not blinking) and the busy bar is a simple static stripe.
#
from font_iosevka import CELL_W, CELL_H, COL_TEXT

class GPUAccess:
    def __init__(self):
        self.cursor = None

    def take_spi(self):
        # returns True if an animation was running and is now stopped
        return False

    def give_spi(self):
        pass

    def have_spi(self):
        return True

    def get_version(self):
        return 'none'

    def upgrade_if_needed(self):
        pass

    async def reflash_gpu_ux(self):
        pass

    def show_test_pattern(self):
        pass

    def busy_bar(self, enable):
        from st7788 import ST7788
        import lcd_display as ld
        d = ST7788.instance
        if not d:
            return
        h = ld.PROGRESS_BAR_H
        d.fill_rect(0, ld.HEIGHT - h, ld.WIDTH, h, ld.COL_DARK_TEXT if enable else 0)

    def cursor_off(self):
        pass

    def cursor_at(self, x, y, cur_type):
        from st7788 import ST7788
        import lcd_display as ld
        d = ST7788.instance
        if not d:
            return
        px = ld.LEFT_MARGIN + x * CELL_W
        py = ld.TOP_MARGIN + y * CELL_H
        w = CELL_W * (2 if (cur_type & ld.CURSOR_DW_Mask) else 1)
        typ = cur_type & 0x0f
        c = COL_TEXT
        if typ == ld.CURSOR_SOLID:
            # underline bar: keeps the character readable
            d.fill_rect(px, py + CELL_H - 2, w, 2, c)
        else:
            # outline box (also used for menu cursor)
            d.fill_rect(px, py, w, 1, c)
            d.fill_rect(px, py + CELL_H - 1, w, 1, c)
            d.fill_rect(px, py, 1, CELL_H, c)
            d.fill_rect(px + w - 1, py, 1, CELL_H, c)

# EOF
