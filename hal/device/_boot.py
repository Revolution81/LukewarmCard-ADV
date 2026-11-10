# _boot.py - Cardputer COLDCARD port: first frozen code run by MicroPython.
# Replaces the ESP32 port's _boot.py (no "/" filesystem, no REPL/boot.py).
import gc, micropython, cp_buildinfo
gc.threshold(4096)

if not cp_buildinfo.IS_DEV:
    # Release builds: Ctrl-C over USB must not break out to a Python prompt
    # (which could read keys from RAM after login).
    micropython.kbd_intr(-1)
try:
    import cc_boot          # does not return
except BaseException as exc:
    import sys
    sys.print_exception(exc)
    try:
        from glob import dis
        dis.fullscreen("Fatal error", line2=repr(exc)[:60])
    except Exception:
        pass
    import cp_board
    cp_board.halt()
