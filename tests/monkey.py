#!/usr/bin/env python3
# monkey.py - random-keypress stress test ("monkey test") for the desktop
# build: logs in, then presses random keys for a while, wandering through the
# menus, and reports any crash ("Yikes"), Python traceback or memory error.
#
#   tests/monkey.py mk4 <runs> <keys per run> [heapsize] [cc-mpy]
#
# Each run starts from a copy of a work dir that has a PIN and seed set up
# (made once with flows 01 + 02). Seeds are fixed (run number), so a failing
# run can be replayed exactly.
import os, sys, random, shutil, subprocess, tempfile, re

PORT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
variant = sys.argv[1]
runs = int(sys.argv[2])
nkeys = int(sys.argv[3])
heap = sys.argv[4] if len(sys.argv) > 4 else '320k'
if variant != 'mk4':
    sys.exit('this kit has the Keypad edition only (mk4)')
M = sys.argv[5] if len(sys.argv) > 5 else os.path.join(PORT, 'build', 'host-mk4', 'cc-mpy')
FLOWS = os.path.join(PORT, 'tests', 'flows-mk4')

# keys: Mk5 keypad (5/8/7/9 are the arrows)
KEYS = ['y'] * 6 + ['x'] * 4 + list('5577889') + list('0123456789')
LOGIN = open(os.path.join(FLOWS, '12_main_identity.txt')).read().split('pick ')[0]

# keys that only scare the test (power-off style halts are fine, but avoid
# typing whole PIN-change sequences by chance: none needed)
BAD = re.compile(r'Yikes|Traceback|MemoryError|\[FAIL\]')

base = tempfile.mkdtemp(prefix='monkey-')
seedwork = os.path.join(base, 'seeded')
os.makedirs(seedwork)
env = dict(os.environ, CP_WORK=seedwork)
for fl in ('01_set_pin.txt', '02_import_seed.txt'):
    env['CP_SCRIPT'] = os.path.join(FLOWS, fl)
    subprocess.run([M, '-X', 'heapsize=' + heap, '-m', 'host_main'], env=env, cwd=base,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)

bad_runs = 0
for r in range(runs):
    rnd = random.Random(1000 + r)
    work = os.path.join(base, 'run%d' % r)
    shutil.copytree(seedwork, work, ignore=shutil.ignore_patterns('*.sock'))
    script = os.path.join(base, 'run%d.txt' % r)
    with open(script, 'w') as f:
        f.write(LOGIN)
        f.write('\nwait 800\n')
        for i in range(nkeys):
            f.write('key %s\nwait %d\n' % (rnd.choice(KEYS), rnd.choice((60, 120, 250))))
            if i % 100 == 99:
                f.write('mem\n')
        f.write('wait 1500\nmem\nquit\n')
    env = dict(os.environ, CP_WORK=work, CP_SCRIPT=script)
    try:
        p = subprocess.run([M, '-X', 'heapsize=' + heap, '-m', 'host_main'], env=env, cwd=base,
                           capture_output=True, text=True, errors='replace',
                           timeout=60 + nkeys)
        out = p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b'').decode(errors='replace') + '\n[TIMEOUT]'
    open(script + '.log', 'w').write(out)
    hits = [ln for ln in out.split('\n') if BAD.search(ln)]
    mems = re.findall(r'\[mem\][^\n]*', out)
    status = 'ok' if not hits and '[TIMEOUT]' not in out else 'PROBLEM'
    if status != 'ok':
        bad_runs += 1
    print('run %2d: %s  %s  %s' % (r, status, mems[-1] if mems else '',
                                    ('first: ' + hits[0][:90]) if hits else ''))
print('%d of %d runs had problems. Logs: %s' % (bad_runs, runs, base))
sys.exit(1 if bad_runs else 0)
