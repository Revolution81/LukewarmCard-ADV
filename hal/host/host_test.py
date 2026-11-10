# host_test.py - desktop test harness: run the firmware headless, drive it
# with a script of key presses, capture screenshots and memory use.
#
# Script lines (CP_SCRIPT file):
#   wait <ms>            pause
#   key <NAME|char>      one key: ENTER ESC UP DOWN LEFT RIGHT DEL TAB SPACE or a char
#   type <text>          several keys
#   waitfor <s> <text>   wait up to <s> seconds for <text> on screen
#   pick <label>         move to a menu item by its label (real up/down keys), select it
#   words <w1 w2 ...>    Mk4/Mk5: enter seed words through the letter menus
#   shot <name>          save screen to $CP_WORK/shots/<name>.rgb565
#   screen               print the text on screen
#   mem                  print gc free/alloc
#   expect <text>        fail unless text is on screen
#   quit                 stop
#
import os, sys, gc
import cp_board
import uasyncio as asyncio

NAMES = {
    'ENTER': '\r', 'ESC': '\x1b', 'UP': '\x0b', 'DOWN': '\x0a', 'LEFT': '\x03',
    'RIGHT': '\x0c', 'DEL': '\x08', 'TAB': '\t', 'SPACE': ' ', 'QR': '\x11',
}

PEAK = [0]

# Mk4/Mk5 variant: the OLED code draws pixels only, so record the strings
# display.py draws (cleared on clear(), clear_rect(), restore()) to give the
# scripts something to "expect". Test-only; the firmware itself is unchanged.
_TEXT = {}          # (y, x) -> msg
_SAVED = {}

def _hook_mk4_display():
    import display
    D = display.Display
    if getattr(D, '_cp_hooked', False):
        return
    o_text, o_clear, o_clear_rect = D.text, D.clear, D.clear_rect
    o_save, o_restore = D.save, D.restore

    def text(self, x, y, msg, *a, **kw):
        rv = o_text(self, x, y, msg, *a, **kw)
        try:
            yy = y if (y is not None and y >= 0) else 99
            _TEXT[(yy, x if (x is not None and x >= 0) else 0)] = str(msg)
        except Exception:
            pass
        return rv
    def clear(self):
        _TEXT.clear()
        return o_clear(self)
    def clear_rect(self, x, y, w, h):
        for k in [k for k in _TEXT if y <= k[0] < y + h]:
            del _TEXT[k]
        return o_clear_rect(self, x, y, w, h)
    def save(self):
        _SAVED.clear(); _SAVED.update(_TEXT)
        return o_save(self)
    def restore(self):
        _TEXT.clear(); _TEXT.update(_SAVED)
        return o_restore(self)

    D.text, D.clear, D.clear_rect, D.save, D.restore = text, clear, clear_rect, save, restore
    D._cp_hooked = True

def screen_text():
    from glob import dis
    if not hasattr(dis, 'next_buf'):
        # Mk4/Mk5 variant: one line per drawn string, top to bottom
        lines, last_y = [], None
        for (y, x) in sorted(_TEXT):
            if y == last_y:
                lines[-1] += '  ' + _TEXT[(y, x)]
            else:
                lines.append(_TEXT[(y, x)])
            last_y = y
        return '\n'.join(lines)
    rows = []
    for row in dis.next_buf:
        rows.append(''.join(chr(c & 0xffff) if 32 <= (c & 0xffff) < 0xfff0 else ' ' for c in row).rstrip())
    return '\n'.join(rows)

async def _press(ch):
    import glob
    glob.numpad.inject(ch)
    await asyncio.sleep_ms(60)

async def _pick(label):
    import cp_buildinfo
    from ux import the_ux
    mk4 = getattr(cp_buildinfo, 'VARIANT', 'q1') == 'mk4'
    down, up, ok = ('8', '5', 'y') if mk4 else ('\x0a', '\x0b', '\r')
    m = the_ux.top_of_stack()
    labels = [getattr(i, 'label', None) for i in getattr(m, 'items', [])]
    if label not in labels:
        print('[FAIL] pick %r: not in menu %r' % (label, labels))
        sys.exit(2)
    want = labels.index(label)
    for _ in range(len(labels) + 5):
        if m.cursor == want:
            break
        await _press(down if m.cursor < want else up)
    if m.cursor != want:
        print('[FAIL] pick %r: cursor stuck at %d' % (label, m.cursor))
        sys.exit(2)
    await _press(ok)
    await asyncio.sleep_ms(150)

async def _word(word):
    # Mk4/Mk5 seed-word entry: walk the letter menus (a- / ab- / abandon)
    from ux import the_ux
    for _ in range(12):
        m = the_ux.top_of_stack()
        labels = [getattr(i, 'label', '') for i in getattr(m, 'items', [])]
        if word in labels:
            await _pick(word)
            return
        pre = [l for l in labels if l.endswith('-') and word.startswith(l[:-1])]
        if not pre:
            print('[FAIL] word %r: no prefix in %r' % (word, labels))
            sys.exit(2)
        await _pick(max(pre, key=len))
    print('[FAIL] word %r: too deep' % word)
    sys.exit(2)

# ---- backup password helpers (Mk4/Mk5 backup + restore tests) ----
# The 12-word backup password is saved in the work folder, because the
# restore happens in a separate run (like after a reinstall).
def _wordfile():
    import cp_board
    return cp_board.WORK + '/backup-words.txt'

def _numbered_words(txt):
    found = {}
    for ln in txt.split('\n'):
        ln = ln.strip()
        num, sep, w = ln.partition(': ')
        if sep and num.isdigit() and w and w.isalpha() and w.islower():
            found[int(num)] = w
    return found

async def _learnwords():
    # read the numbered words off the story on screen, scrolling down
    found = _numbered_words(screen_text())
    for _ in range(40):
        if len(found) >= 12:
            break
        await _press('8')
        await asyncio.sleep_ms(80)
        found.update(_numbered_words(screen_text()))
    if sorted(found) != list(range(1, 13)):
        print('[FAIL] learnwords: got %r' % found)
        sys.exit(2)
    words = [found[i] for i in range(1, 13)]
    open(_wordfile(), 'w').write(' '.join(words))
    # back to the top of the story
    for _ in range(40):
        await _press('5')
    print('[learned] 12 words')

async def _quiz():
    # answer COLDCARD's "Word N is?" quiz with the learned words
    words = open(_wordfile()).read().split()
    n_done = 0
    for _ in range(30):
        txt = screen_text()
        title = [ln for ln in txt.split('\n') if ln.startswith('Word ') and ln.endswith(' is?')]
        if not title:
            break
        n = int(title[0].split()[1])
        opts = {}
        for ln in txt.split('\n'):
            num, sep, w = ln.strip().partition(': ')
            if sep and num in ('1', '2', '3'):
                opts[num] = w
        right = [k for k, w in opts.items() if w == words[n - 1]]
        if right:
            key = right[0]
        else:
            # correct option not drawn on screen: it's the one not listed
            key = [k for k in '123' if k not in opts][0]
        await _press(key)
        await asyncio.sleep_ms(400)
        n_done += 1
    print('[quiz] answered %d' % n_done)

async def run_script(path):
    import cp_board
    os.mkdir(cp_board.WORK + '/shots') if 'shots' not in os.listdir(cp_board.WORK) else None
    import cp_buildinfo
    if getattr(cp_buildinfo, 'VARIANT', 'q1') == 'mk4':
        # first time this task runs: asyncio has just started, only the
        # splash has been drawn, so every UI screen gets recorded
        _hook_mk4_display()
    # let boot finish
    await asyncio.sleep_ms(300)
    lines = open(path).read().split('\n')
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith('#'):
            continue
        cmd, _, arg = ln.partition(' ')
        if cmd == 'wait':
            await asyncio.sleep_ms(int(arg))
        elif cmd == 'key':
            await _press(NAMES.get(arg, arg))
        elif cmd == 'type':
            for ch in arg:
                await _press(ch)
        elif cmd == 'pick':
            # move the cursor of the menu on screen to the item labelled
            # <arg> using the real up/down keys, then select it
            await _pick(arg)
        elif cmd == 'words':
            # Mk4/Mk5: enter seed words through the letter menus
            for w in arg.split():
                await _word(w)
        elif cmd == 'waitfor':
            # waitfor <seconds> <text>: wait until <text> is on screen
            secs, _, want = arg.partition(' ')
            for _ in range(int(secs) * 5):
                if want in screen_text():
                    break
                await asyncio.sleep_ms(200)
            else:
                print('[FAIL] waitfor %r' % want)
                print(screen_text())
                sys.exit(2)
            print('[ok] %s' % want)
        elif cmd == 'learnwords':
            await _learnwords()
        elif cmd == 'quiz':
            await _quiz()
        elif cmd == 'bkwords':
            # Mk4/Mk5: type the learned backup password into the letter menus
            for w in open(_wordfile()).read().split():
                await _word(w)
        elif cmd in ('vdput', 'vdget', 'vdls', 'vdrm'):
            # the computer's side of the Virtual Disk: put/get files inside
            # the disk image as if over USB (cp_vdisk.py)
            #   vdput <local file> <name>   vdget <name> <local file>   vdls
            #   vdrm <name>...  (delete, like the computer would)
            import cp_vdisk, utime
            args = arg.split()
            vd = cp_vdisk.DISK
            os.mount(vd, '/_vdh', readonly=(cmd not in ('vdput', 'vdrm')))
            try:
                if cmd == 'vdput':
                    with open(args[0], 'rb') as fi:
                        data = fi.read()
                    with open('/_vdh/' + args[1], 'wb') as fo:
                        fo.write(data)
                elif cmd == 'vdrm':
                    for a in args:
                        try:
                            os.remove('/_vdh/' + a)
                        except OSError:
                            pass
                elif cmd == 'vdget':
                    with open('/_vdh/' + args[0], 'rb') as fi:
                        data = fi.read()
                    with open(args[1], 'wb') as fo:
                        fo.write(data)
                else:
                    print('[vdisk] ' + ' '.join(sorted(os.listdir('/_vdh'))))
            finally:
                os.umount('/_vdh')
            if cmd in ('vdput', 'vdrm'):
                vd.t_host = utime.ticks_ms()
                vd.dirty = True             # like host writes over USB
            print('[vdisk] %s %s' % (cmd, ' '.join(args)))
        elif cmd == 'cardout':
            # pull the SD card (see cp_board.sd_block_device)
            open(cp_board.WORK + '/card-out', 'w').close()
            print('[card] out')
        elif cmd == 'cardin':
            try:
                os.remove(cp_board.WORK + '/card-out')
            except OSError:
                pass
            print('[card] in')
        elif cmd == 'shot':
            await asyncio.sleep_ms(50)
            cp_board.lcd_dev().save(cp_board.WORK + '/shots/' + arg + '.rgb565')
            print('[shot] ' + arg)
        elif cmd == 'screen':
            print('[screen]\n' + screen_text() + '\n[/screen]')
        elif cmd == 'py':
            # run one line of Python inside the firmware (desktop tests only)
            try:
                exec(arg, globals())
            except Exception as e:
                import sys as _sys
                _sys.print_exception(e)
        elif cmd == 'ovcclear':
            # forget COLDCARD's (bounded, 128 entries) list of seen UTXO
            # amounts, so a leak test isn't confused by it filling up
            from history import OutptValueCache
            OutptValueCache.clear()
        elif cmd == 'probe':
            # sizes of long-lived containers (leak hunting)
            import glob as _g
            try:
                from asyncio import core as _c
                nq = sum(1 for _ in _c._task_queue.heap) if hasattr(_c._task_queue, 'heap') else -1
            except Exception:
                nq = -2
            out = []
            vd = getattr(_g, 'VD', None)
            if vd:
                out.append('vd.ignore=%d vd.contents=%d' % (len(vd.ignore), len(vd.contents)))
            try:
                from glob import settings as _s
                import ujson
                out.append('settings=%dB keys=%d' % (len(ujson.dumps(_s.current)), len(_s.current)))
                out.append(','.join('%s:%d' % (k, len(ujson.dumps(v))) for k, v in _s.current.items()))
            except Exception as e:
                out.append('settings? %r' % e)
            try:
                from imptask import IMPT
                out.append('impt=%d' % len(IMPT.tasks))
            except Exception:
                pass
            try:
                from ux import the_ux
                out.append('uxstack=%d' % len(the_ux.stack))
            except Exception:
                pass
            out.append('tasks=%d' % nq)
            print('[probe] ' + ' '.join(out))
        elif cmd == 'mem':
            gc.collect()
            print('[mem] %s free=%d alloc=%d' % (arg, gc.mem_free(), gc.mem_alloc()))
            import micropython
            micropython.qstr_info()
        elif cmd == 'expect':
            if arg not in screen_text():
                print('[FAIL] expected %r on screen:\n%s' % (arg, screen_text()))
                sys.exit(2)
            print('[ok] ' + arg)
        elif cmd == 'quit':
            print('[quit]')
            sys.exit(0)
        else:
            print('[?] ' + ln)
    print('[end of script]')
    sys.exit(0)

async def _peak_watch():
    while True:
        a = gc.mem_alloc()
        if a > PEAK[0]:
            PEAK[0] = a
        await asyncio.sleep_ms(5)

def start():
    script = os.getenv('CP_SCRIPT')
    if script:
        asyncio.create_task(run_script(script))

# EOF
