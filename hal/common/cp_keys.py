# cp_keys.py - Cardputer ADV key matrix: TCA8418 key numbers -> key names.
#
# Shared by keyboard.py (Q variant) and mempad.py (Mk4/Mk5 variant). Kept free
# of COLDCARD imports, since the Mk4 build's charcodes.py has no Q-only keys.
#
# Layout (from M5Stack / cardputer-adv crate):
#   `  1 2 3 4 5 6 7 8 9 0 - = Bksp
#   Tab q w e r t y u i o p [ ] \\
#   Fn Shft a s d f g h j k l ; ' Enter
#   Ctrl Opt Alt z x c v b n m , . / Space
#
_LAYOUT = (
    ('`','1','2','3','4','5','6','7','8','9','0','-','=','BKSP'),
    ('TAB','q','w','e','r','t','y','u','i','o','p','[',']','\\'),
    ('FN','SHIFT','a','s','d','f','g','h','j','k','l',';',"'",'ENTER'),
    ('CTRL','OPT','ALT','z','x','c','v','b','n','m',',','.','/',' '),
)
def key_name(number):
    # TCA8418 key number (row*10 + col + 1) -> layout name, or None
    idx = number - 1
    if not (0 <= idx < 80):
        return None
    r, c = idx // 10, idx % 10
    if c >= 8:
        return None
    lr, lc = c % 4, r * 2 + (1 if c >= 4 else 0)
    if lc >= 14:
        return None
    return _LAYOUT[lr][lc]

# EOF
