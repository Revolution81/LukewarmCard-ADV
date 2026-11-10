# cp_entropy.py - Cardputer port: the random bytes a real COLDCARD gets from
# its secure-element chips (callgate.read_rng(1) and read_rng(2), behind
# ckcc.gate(26)).
#
# COLDCARD makes a new seed as
#     sha256d(MCU random 32 bytes + SE1 random 32 bytes + SE2 random 8 bytes)
# and also reseeds its random generator from SE1 + SE2 at every power-up
# (mk4.rng_seeding). That code is unchanged here; only where the "SE" bytes
# come from differs:
#
#     SE1 share = SHA-256( tag | 32 bytes chip RNG | microphone samples )
#     SE2 share = SHA-256( tag | 32 bytes chip RNG | motion-sensor samples )
#
# The ESP32-S3's hardware random generator is always part of every share and
# is mandatory: if it is not running, this raises and no seed is made
# (cp_board.rng_bytes fails closed). The sensors add independent physical
# noise on top. A sensor that is missing or fails its health check is simply
# left out of that share (it then equals today's chip-only share) and the
# reason is recorded for the Entropy Sources screen; it never blocks a seed.
#
# Mixing through SHA-256 means a bad or even hostile sensor can't make the
# result worse than the chip RNG alone.
import cp_board
from cp_hashlib import sha256

CHIP = 'Chip RNG'
_MAP = {1: 'mic', 2: 'imu'}

_sources = None
# name -> (ok: True/False/None, detail); None = not tried yet
_status = {}

def _get_sources():
    global _sources
    if _sources is None:
        try:
            _sources = cp_board.entropy_sources()
        except Exception as exc:
            print('entropy sources: %r' % exc)
            _sources = {}
    return _sources

def _collect(key, update):
    # feed one sensor's samples to update(); record how it went
    src = _get_sources().get(key)
    if src is None:
        _status[key] = (None, 'not on this build')
        return False
    try:
        _status[key] = (True, src.collect(update))
        return True
    except Exception as exc:
        # includes cp_sensors.Unhealthy: samples were mixed in (harmless,
        # the chip RNG is in there too) but reported as not counted
        msg = str(exc) or exc.__class__.__name__
        _status[key] = (False, msg)
        print('entropy %s: %s' % (key, msg))
        return False

def share(source, n):
    # bytes standing in for secure element `source` (1 or 2), n bytes long
    key = _MAP[source]
    chip = bytearray(32)
    cp_board.rng_bytes(chip)                # raises if the TRNG isn't on
    if len(set(chip)) < 8:
        raise RuntimeError('chip RNG failed health check')
    _status[CHIP] = (True, 'OK')

    h = sha256()
    h.update(b'cardputer-se')
    h.update(bytes((source,)))
    h.update(chip)
    _collect(key, h.update)
    return h.digest()[:n]

def status():
    # [(label, ok, detail)] for the Entropy Sources screen
    out = []
    for key, label in ((CHIP, CHIP), ('mic', 'Microphone'), ('imu', 'Motion sensor')):
        ok, detail = _status.get(key, (None, 'not used yet'))
        out.append((label, ok, detail))
    return out

def test_all():
    # run every source once now (for the screen), returns status()
    for s in (1, 2):
        share(s, 8)
    return status()

# EOF
